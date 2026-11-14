"""Snippet store: CRUD + import from VSCode / massCode (code pane, M3).

Ports server/snippet_import.py 1:1 (jsonc_loads, map_language, the VSCode
and massCode readers) and adds the SQLite CRUD that 0.x served over
/api/snippets. Same schema and semantics as the 0.x snippets.db so a
user's existing store imports losslessly.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys

from . import db as core_db
from pathlib import Path

# --------------------------------------------------------------------------
# language mapping — maps source language names to a fengrid field
# ('html', 'css', 'js') plus the fiddle language ('web' or 'markdown').
# Unmapped languages keep their code in the JS pane and record the raw
# language as a tag so it stays discoverable.
# --------------------------------------------------------------------------
_LANG_MAP = {
    "html": ("html", "web"), "htm": ("html", "web"), "xhtml": ("html", "web"),
    "vue": ("html", "web"), "svelte": ("html", "web"),
    "css": ("css", "web"), "scss": ("css", "web"), "sass": ("css", "web"),
    "less": ("css", "web"), "postcss": ("css", "web"),
    "javascript": ("js", "web"), "js": ("js", "web"),
    "typescript": ("js", "web"), "ts": ("js", "web"),
    "javascriptreact": ("js", "web"), "jsx": ("js", "web"),
    "typescriptreact": ("js", "web"), "tsx": ("js", "web"),
    "json": ("js", "web"), "jsonc": ("js", "web"), "json5": ("js", "web"),
    "markdown": ("html", "markdown"), "md": ("html", "markdown"),
    "plaintext": ("html", "web"), "text": ("html", "web"),
    "shell": ("js", "web"), "sh": ("js", "web"), "bash": ("js", "web"),
    "python": ("js", "web"), "py": ("js", "web"),
    "go": ("js", "web"), "rust": ("js", "web"),
    "c": ("js", "web"), "cpp": ("js", "web"), "java": ("js", "web"),
    "yaml": ("js", "web"), "yml": ("js", "web"), "toml": ("js", "web"),
    "xml": ("html", "web"), "svg": ("html", "web"),
    "diff": ("js", "web"), "sql": ("js", "web"),
    "ini": ("js", "web"), "properties": ("js", "web"),
    "dockerfile": ("js", "web"), "makefile": ("js", "web"),
}


def map_language(raw):
    """(field, fiddle_language, raw_or_None) — raw is tagged when unmapped."""
    if not raw:
        return "html", "web", None
    key = str(raw).strip().lower()
    if key in _LANG_MAP:
        field, fid = _LANG_MAP[key]
        return field, fid, None
    # prefix match, longest names first so 'javascriptreact' doesn't hit
    # 'javascript'. Short keys (c, go, py, sh, ts…) are exact-only: a 1-2
    # char prefix would swallow almost anything ("cobol" → "c") and lose
    # the lang: tag the docstring promises.
    for known in sorted(_LANG_MAP, key=len, reverse=True):
        if len(known) < 3:
            continue
        if key.startswith(known) and len(key) > len(known):
            field, fid = _LANG_MAP[known]
            return field, fid, None
    return "js", "web", str(raw).strip().lower().replace(" ", "-")


# --------------------------------------------------------------------------
# Editor language suite — the dropdown (and / command) in the snippet
# editor. "web" keeps the three-tab HTML/CSS/JS fiddle; "markdown" gets a
# live GitHub-styled preview; every other entry is a single-body language
# whose code lives in the field `language_field()` returns. The snippet
# schema stays html/css/js, so 0.x stores and VSCode/massCode imports
# round-trip unchanged — imports keep the legacy "web" fiddle mapping and
# the user can retag the language from the dropdown afterwards.
# --------------------------------------------------------------------------
EDITOR_LANGUAGES = [
    ("web", None),
    ("markdown", "html"),
    ("python", "js"),
    ("shell", "js"),
    ("javascript", "js"),
    ("typescript", "js"),
    ("go", "js"),
    ("rust", "js"),
    ("c", "js"),
    ("cpp", "js"),
    ("csharp", "js"),
    ("java", "js"),
    ("kotlin", "js"),
    ("swift", "js"),
    ("ruby", "js"),
    ("php", "js"),
    ("lua", "js"),
    ("perl", "js"),
    ("r", "js"),
    ("haskell", "js"),
    ("scala", "js"),
    ("dart", "js"),
    ("powershell", "js"),
    ("sql", "js"),
    ("yaml", "js"),
    ("toml", "js"),
    ("json", "js"),
    ("dockerfile", "js"),
    ("makefile", "js"),
    ("diff", "js"),
    ("ini", "js"),
    ("plaintext", "js"),
    ("xml", "html"),
    ("svg", "html"),
    ("css", "css"),
    ("scss", "css"),
]

_LANG_FIELD = dict(EDITOR_LANGUAGES)


def editor_languages() -> list[str]:
    """Language keys offered by the snippet editor dropdown, in order."""
    return [k for k, _ in EDITOR_LANGUAGES]


def language_field(lang: str) -> str | None:
    """Body field for an editor language: None for the web fiddle (which
    has three fields), else the single html/css/js field it edits."""
    key = (lang or "").strip().lower()
    if key not in _LANG_FIELD:
        key = "web"
    return _LANG_FIELD[key]


# --------------------------------------------------------------------------
# JSONC — VSCode snippet files allow // and /* */ comments and trailing
# commas. A small state machine strips comments while respecting string
# literals (so "http://…" survives), then trailing commas are removed.
# --------------------------------------------------------------------------
def jsonc_loads(text):
    out = []
    i, n = 0, len(text)
    in_str = False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(c)
        i += 1
    cleaned = re.sub(r",(\s*[}\]])", r"\1", "".join(out))
    return json.loads(cleaned)


def _body_text(body):
    """VSCode body: list of lines (or a plain string)."""
    if isinstance(body, list):
        return "\n".join(str(x) for x in body)
    return str(body or "")


def _norm_tags(*sources):
    tags = []
    for src in sources:
        if isinstance(src, list):
            items = src
        elif isinstance(src, str):
            items = src.split(",")
        else:
            items = []
        for t in items:
            t = str(t).strip()
            if t and t.lower() not in [x.lower() for x in tags]:
                tags.append(t)
    return ", ".join(tags)


def parse_vscode(text, default_lang=""):
    """Yield fengrid snippet dicts from a VSCode snippets file."""
    data = jsonc_loads(text)
    if not isinstance(data, dict):
        raise ValueError("not a VSCode snippets file (expected a JSON object)")
    out = []
    for name, sn in data.items():
        if not isinstance(sn, dict):
            continue
        body = _body_text(sn.get("body", ""))
        if not body.strip():
            continue
        scope = sn.get("scope") or default_lang or ""
        first = str(scope).split(",")[0].strip()
        field, fid, raw = map_language(first)
        fields = {"html": "", "css": "", "js": ""}
        fields[field] = body
        tags = _norm_tags(sn.get("prefix"), raw and "lang:" + raw)
        out.append({
            "title": str(sn.get("title") or name).strip() or "Untitled snippet",
            "description": str(sn.get("description") or "").strip(),
            "language": fid,
            "html": fields["html"], "css": fields["css"], "js": fields["js"],
            "tags": tags,
        })
    return out


# VSCode default snippet folders per OS — mirrors server/snippet_import.py.
VSCode_DIRS = [
    "~/.config/Code/User/snippets",
    "~/.config/VSCodium/User/snippets",
    "~/.config/Code - OSS/User/snippets",
    "~/.config/Cursor/User/snippets",
    "~/.local/share/code/User/snippets",  # flatpak
    "~/Library/Application Support/Code/User/snippets",
]


def parse_masscode_db(path):
    """Yield fengrid snippet dicts from a massCode db.sqlite file."""
    conn = sqlite3.connect("file:%s?mode=ro" % Path(path).as_posix(), uri=True)
    conn.row_factory = sqlite3.Row
    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        if "snippets" not in tables:
            raise ValueError("not a massCode database (no snippets table)")
        cols = {r[1] for r in conn.execute("PRAGMA table_info(snippets)").fetchall()}

        # tag lookup varies: a tags JSON column (of tag IDs), or a join table
        tag_col = "tags" if "tags" in cols else None
        tag_join = None
        if tag_col is None:
            for cand in ("snippet_tags", "snippets_tags"):
                if cand in tables:
                    tag_join = cand
                    break
        # the id→name map is needed in BOTH modes: the JSON column stores
        # tag IDs, not names
        tag_names = {}
        if "tags" in tables:
            try:
                tag_names = {r["id"]: r["name"] for r in conn.execute(
                    "SELECT id, name FROM tags").fetchall()}
            except sqlite3.Error:
                pass

        name_col = ("name" if "name" in cols else
                    ("title" if "title" in cols else None))
        if name_col is None:
            raise ValueError("massCode snippets table has no name/title column")
        content_col = ("content" if "content" in cols else
                       ("text" if "text" in cols else None))
        if content_col is None:
            raise ValueError("massCode snippets table has no content column")

        rows = conn.execute("SELECT * FROM snippets").fetchall()
        out = []
        for row in rows:
            if "is_deleted" in cols and row["is_deleted"]:
                continue
            title = str(row[name_col] or "Untitled snippet").strip() \
                or "Untitled snippet"
            tags = []
            if tag_col and row[tag_col]:
                try:
                    raw_tags = json.loads(row[tag_col])
                    if isinstance(raw_tags, list):
                        ids = [t for t in raw_tags
                               if isinstance(t, (int, float))]
                        tags = [tag_names.get(int(i), "") for i in ids]
                        tags = [t for t in tags if t]
                except (ValueError, TypeError):
                    tags = []
            elif tag_join:
                try:
                    ids = [r["tag_id"] for r in conn.execute(
                        "SELECT tag_id FROM %s WHERE snippet_id = ?" % tag_join,
                        (row["id"],)).fetchall()]
                    tags = [tag_names.get(i, "") for i in ids]
                    tags = [t for t in tags if t]
                except (sqlite3.Error, KeyError):
                    pass

            content = row[content_col] or ""
            frag_langs = []
            try:
                frags = json.loads(content)
                if not isinstance(frags, list):
                    frags = []
            except (ValueError, TypeError):
                frags = []
            fields = {"html": "", "css": "", "js": ""}
            for frag in frags:
                if not isinstance(frag, dict):
                    continue
                lang = str(frag.get("language") or frag.get("label") or "")
                value = str(frag.get("value") or "")
                if not value.strip():
                    continue
                field, fid, raw = map_language(lang)
                fields[field] += (("\n" if fields[field] else "") + value)
                frag_langs.append((field, fid, raw, lang))
            if not fields["html"] and not fields["css"] and not fields["js"]:
                # plain-text row (older massCode): single JS pane
                fields["js"] = str(content or "")
                frag_langs.append(("js", "web", "plaintext", "text"))
            all_tags = _norm_tags(*tags, *(r for f, _, r, _ in frag_langs if r))
            lang_set = {fid for _, fid, _, _ in frag_langs}
            language = "markdown" if "markdown" in lang_set else "web"
            description = ""
            if "description" in cols and row["description"]:
                description = str(row["description"]).strip()
            out.append({
                "title": title,
                "description": description,
                "language": language,
                "html": fields["html"], "css": fields["css"],
                "js": fields["js"],
                "tags": all_tags,
            })
        return out
    finally:
        conn.close()


def import_file(kind, path):
    """Read a snippet file/db and return a list of fengrid snippet dicts."""
    p = Path(path).expanduser()
    if not p.is_file():
        raise ValueError("no such file: %s" % path)
    if kind == "vscode":
        return parse_vscode(p.read_text(encoding="utf-8", errors="replace"))
    if kind == "masscode":
        return parse_masscode_db(p)
    raise ValueError("unknown import kind: %s (use vscode or masscode)" % kind)


def infer_snippet_kind(path):
    """Guess the import kind from the file extension (#98).

    massCode stores snippets in SQLite databases (.sqlite/.db); VS Code
    uses JSON-derived formats (.code-snippets / .json). Anything else
    defaults to vscode — the parse error message names the real problem
    when the guess is wrong.
    """
    suffix = Path(path).suffix.lower()
    if suffix in (".sqlite", ".db", ".sqlite3"):
        return "masscode"
    return "vscode"


# --------------------------------------------------------------------------
# VS Code snippet location scan (#98) — discovers snippet files at the
# default User/snippets folders for VS Code and its common variants, so
# the Settings import row can offer a one-click scan instead of making
# the user navigate to the config directory by hand.
# --------------------------------------------------------------------------
_VSCODE_VARIANTS = ("Code", "Code - Insiders", "VSCodium", "Cursor")
_SNIPPET_EXTS = {".code-snippets", ".json"}


def scan_vscode_snippets():
    """Find snippet files at VS Code's default locations (#98).

    Scans the User/snippets folder for each VS Code variant (Code,
    Insiders, VSCodium, Cursor) under the platform's config root.
    Returns a list of dicts {app, name, path} for each .code-snippets
    or .json file found. Empty list when none exist — the user can
    always point at any file manually from the Settings import row.
    """
    home = Path.home()
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", str(home / "AppData" / "Roaming"))
        bases = [Path(appdata)]
    elif sys.platform == "darwin":
        bases = [home / "Library" / "Application Support"]
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME", str(home / ".config"))
        bases = [Path(xdg)]

    out = []
    for base in bases:
        for variant in _VSCODE_VARIANTS:
            root = base / variant / "User" / "snippets"
            if not root.is_dir():
                continue
            for f in sorted(root.iterdir()):
                if (not f.is_file() or f.suffix.lower() not in _SNIPPET_EXTS
                        or f.name.startswith(".")):
                    continue
                out.append({"app": variant, "name": f.stem, "path": str(f)})
    return out


# --------------------------------------------------------------------------
# SQLite CRUD — the schema itself lives in core.db (SCHEMA), so any
# connect() path guarantees the snippet tables exist before this module is
# used. CRUD here is intentionally schema-free.
# --------------------------------------------------------------------------
def list_snippets(con, q="", lang="", sort="updated", collection_id=None,
                  starred_only=False):
    """(id, title, description, language, tags, created, updated) rows."""
    sql = ("SELECT s.id, s.title, s.description, s.language, s.tags,"
           " s.created, s.updated FROM snippet s")
    join = ""
    where, args = [], []
    if collection_id is not None:
        join += (" JOIN collection_ref cr ON cr.item_kind = 'snippet'"
                 " AND cr.item_id = s.id")
        where.append("cr.collection_id = ?")
        args.append(collection_id)
    if starred_only:
        join += (" JOIN collection_ref sr ON sr.item_kind = 'snippet'"
                 " AND sr.item_id = s.id"
                 " AND sr.collection_id = (SELECT id FROM collection"
                 " WHERE name = 'Starred Assets')")
    if q:
        like = "%" + q.lower() + "%"
        where.append("(lower(s.title) LIKE ? OR lower(s.description) LIKE ?"
                     " OR lower(s.tags) LIKE ? OR lower(s.html) LIKE ?"
                     " OR lower(s.css) LIKE ? OR lower(s.js) LIKE ?)")
        args += [like] * 6
    if lang:
        where.append("s.language = ?")
        args.append(lang)
    if where:
        sql += join + " WHERE " + " AND ".join(where)
    else:
        sql += join
    order = {"updated": "s.updated DESC, s.id DESC",
             "created": "s.created DESC, s.id DESC",
             "title": "s.title COLLATE NOCASE ASC, s.id ASC"}.get(
                 sort, "s.updated DESC, s.id DESC")
    sql += " ORDER BY " + order
    return con.execute(sql, args).fetchall()


def tag_cloud(con, limit=20):
    rows = con.execute(
        "SELECT tags FROM snippet WHERE tags != ''").fetchall()
    counts: dict[str, int] = {}
    for (tags,) in rows:
        for t in tags.split(","):
            t = t.strip()
            if t:
                counts[t] = counts.get(t, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))
    return ranked[:limit]


def get_snippet(con, sid):
    return con.execute(
        "SELECT id, title, description, language, html, css, js, tags,"
        " created, updated FROM snippet WHERE id = ?", (sid,)).fetchone()


def create_snippet(con, title, description, language, html, css, js, tags):
    cur = con.execute(
        "INSERT INTO snippet (title, description, language, html, css, js,"
        " tags, guid) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (title, description, language, html, css, js, tags,
         core_db.new_guid()))
    con.commit()
    return cur.lastrowid


def update_snippet(con, sid, title, description, language, html, css, js, tags):
    con.execute(
        "UPDATE snippet SET title = ?, description = ?, language = ?,"
        " html = ?, css = ?, js = ?, tags = ?,"
        " updated = datetime('now', 'localtime') WHERE id = ?",
        (title, description, language, html, css, js, tags, sid))
    con.commit()


def delete_snippet(con, sid) -> None:
    con.execute("DELETE FROM snippet WHERE id = ?", (sid,))
    con.commit()


# --------------------------------------------------------------------------
# Markdown → HTML (snippet preview). A compact GitHub-flavoured subset:
# headings, hr, fenced code (with language tag), blockquotes, pipe tables,
# ordered/unordered lists, inline code / bold / italic / strikethrough,
# links and images, paragraphs. No dependencies — the renderer ships in
# the frozen bundle.
# --------------------------------------------------------------------------
def _md_inline(text: str) -> str:
    """Inline markdown: code, bold, italic, strike, links, images.
    URLs and display text are HTML-escaped before attribute/frame
    interpolation — a crafted URL (e.g. `http://x"><script>`) must
    never break out of src/href (SEC-2)."""
    esc = (lambda s: s.replace("&", "&amp;").replace('"', "&quot;")
           .replace("<", "&lt;").replace(">", "&gt;"))
    text = re.sub(r"`([^`]+)`", lambda m: "<code>" + esc(m.group(1))
                  + "</code>", text)
    text = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)\)",
                  lambda m: '<img src="' + esc(m.group(2))
                  + '" alt="' + esc(m.group(1)) + '">', text)
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)",
                  lambda m: '<a href="' + esc(m.group(2)) + '">'
                  + esc(m.group(1)) + "</a>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", lambda m: "<strong>"
                  + esc(m.group(1)) + "</strong>", text)
    text = re.sub(r"__([^_]+)__", lambda m: "<strong>"
                  + esc(m.group(1)) + "</strong>", text)
    text = re.sub(r"(?<!\*)\*([^*\s][^*]*)\*(?!\*)", lambda m: "<em>"
                  + esc(m.group(1)) + "</em>", text)
    text = re.sub(r"_([^_\s][^_]*)_(?!\w)", lambda m: "<em>"
                  + esc(m.group(1)) + "</em>", text)
    text = re.sub(r"~~([^~]+)~~", lambda m: "<del>"
                  + esc(m.group(1)) + "</del>", text)
    return text


def _md_table(rows: list[str]) -> str:
    """A pipe table: row 0 header, row 1 alignment dashes, rest body."""
    cells = lambda r: [c.strip() for c in r.strip().strip("|").split("|")]
    head = cells(rows[0])
    body = [cells(r) for r in rows[2:]]
    out = ["<table>", "<thead>", "<tr>"]
    out += [f"<th>{_md_inline(c)}</th>" for c in head]
    out += ["</tr>", "</thead>", "<tbody>"]
    for r in body:
        out.append("<tr>")
        out += [f"<td>{_md_inline(c)}</td>" for c in r]
        out.append("</tr>")
    out += ["</tbody>", "</table>"]
    return "".join(out)


def markdown_html(md: str) -> str:
    """Render a GitHub-flavoured markdown fragment to HTML."""
    md = (md or "").replace("\r\n", "\n")
    lines = md.split("\n")
    out: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()

        # fenced code block
        fence = re.match(r"^(```+|~~~+)\s*(\S*)$", stripped)
        if fence:
            fence_tok, lang = fence.group(1)[:3], fence.group(2)
            block = []
            i += 1
            while i < n and not lines[i].strip().startswith(fence_tok):
                block.append(lines[i])
                i += 1
            i += 1  # closing fence (or EOF)
            cls = f' class="language-{lang}"' if lang else ""
            body = _md_inline("\n".join(block)) if lang == "html" else \
                "\n".join(block)
            body = body.replace("&", "&amp;").replace("<", "&lt;") \
                       .replace(">", "&gt;")
            out.append(f"<pre><code{cls}>{body}</code></pre>")
            continue

        # pipe table (header + alignment row + >=1 body row)
        if (stripped.startswith("|") and i + 1 < n
                and re.match(r"^\s*\|?[\s:|-]+\|?\s*$", lines[i + 1])
                and "-" in lines[i + 1]):
            rows = [line]
            i += 1
            while i < n and lines[i].strip().startswith("|"):
                rows.append(lines[i])
                i += 1
            if len(rows) >= 3:
                out.append(_md_table(rows))
                continue

        # heading
        h = re.match(r"^(#{1,6})\s+(.*?)(\s+#+\s*)?$", stripped)
        if h:
            lvl = len(h.group(1))
            out.append(f"<h{lvl}>{_md_inline(h.group(2))}</h{lvl}>")
            i += 1
            continue

        # hr
        if re.match(r"^(\*\s*){3,}$|^(-\s*){3,}$|^(_\s*){3,}$", stripped):
            out.append("<hr>")
            i += 1
            continue

        # blockquote
        if stripped.startswith(">"):
            block = []
            while i < n and lines[i].strip().startswith(">"):
                block.append(lines[i].strip()[1:].strip())
                i += 1
            out.append(f"<blockquote>{markdown_html(chr(10).join(block))}"
                       f"</blockquote>")
            continue

        # lists (one indent level; ul/ol mixed by marker)
        li = re.match(r"^(\s*)([-*+]|\d+\.)\s+(.*)$", line)
        if li:
            ordered = bool(re.match(r"^\d+\.", li.group(2)))
            tag = "ol" if ordered else "ul"
            items = []
            while i < n:
                m = re.match(r"^(\s*)([-*+]|\d+\.)\s+(.*)$", lines[i])
                if not m or bool(re.match(r"^\d+\.", m.group(2))) != ordered:
                    break
                items.append(f"<li>{_md_inline(m.group(3))}</li>")
                i += 1
            out.append(f"<{tag}>{''.join(items)}</{tag}>")
            continue

        # blank line closes a paragraph
        if not stripped:
            i += 1
            continue

        # paragraph: consecutive non-empty, non-structural lines
        para = [stripped]
        i += 1
        while i < n:
            s2 = lines[i].strip()
            if (not s2 or s2.startswith("#") or s2.startswith(">")
                    or s2.startswith("|") or s2.startswith("```")
                    or s2.startswith("~~~")
                    or re.match(r"^([-*+]|\d+\.)\s+", s2)):
                break
            para.append(s2)
            i += 1
        out.append(f"<p>{_md_inline('<br>'.join(para))}</p>")

    return "\n".join(out)


# GitHub-markdown-flavoured stylesheet, tokenised for dark/light. The
# palette follows github.com's primer values (both modes), scoped to the
# preview surface only — user CSS can override by editing the snippet's
# markdown (the renderer honours <style> in raw HTML blocks too).
_MD_CSS = """
:root {
  --bg: %(bg)s; --fg: %(fg)s; --border: %(border)s;
  --muted: %(muted)s; --code-bg: %(codebg)s; --accent: %(accent)s;
}
body { margin: 0; padding: 24px; background: var(--bg); color: var(--fg);
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica,
  Arial, sans-serif; font-size: 16px; line-height: 1.6;
  word-wrap: break-word; }
h1, h2, h3, h4, h5, h6 { margin: 24px 0 16px; font-weight: 600;
  line-height: 1.25; }
h1 { font-size: 2em; border-bottom: 1px solid var(--border);
  padding-bottom: .3em; }
h2 { font-size: 1.5em; border-bottom: 1px solid var(--border);
  padding-bottom: .3em; }
h3 { font-size: 1.25em; } h4 { font-size: 1em; }
p { margin: 0 0 16px; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
code { font-family: ui-monospace, SFMono-Regular, 'SF Mono', Consolas,
  'Liberation Mono', Menlo, monospace; font-size: 85%%; padding: .2em .4em;
  background: var(--code-bg); border-radius: 6px; }
pre { background: var(--code-bg); border-radius: 6px; padding: 16px;
  overflow: auto; line-height: 1.45; }
pre code { padding: 0; background: transparent; font-size: 100%%; }
blockquote { margin: 0 0 16px; padding: 0 1em; color: var(--muted);
  border-left: .25em solid var(--border); }
table { border-collapse: collapse; margin-bottom: 16px; display: block;
  overflow: auto; }
th, td { border: 1px solid var(--border); padding: 6px 13px; }
th { font-weight: 600; background: var(--code-bg); }
tr:nth-child(2n) { background: var(--code-bg); }
img { max-width: 100%%; }
hr { height: 1px; border: 0; background: var(--border); margin: 24px 0; }
ul, ol { margin: 0 0 16px; padding-left: 2em; }
del { color: var(--muted); }
"""

_MD_THEMES = {
    False: {   # light — GitHub light
        "bg": "#ffffff", "fg": "#1f2328", "border": "#d0d7de",
        "muted": "#656d76", "codebg": "#f6f8fa", "accent": "#0969da",
    },
    True: {    # dark — GitHub dark dimmed
        "bg": "#0d1117", "fg": "#e6edf3", "border": "#30363d",
        "muted": "#8b949e", "codebg": "#161b22", "accent": "#2f81f7",
    },
}


def markdown_doc(md: str, dark: bool = False) -> str:
    """Full HTML document for the preview pane: GitHub-style CSS for the
    requested mode wrapping markdown_html(md)."""
    css = _MD_CSS % _MD_THEMES[bool(dark)]
    return ("<!DOCTYPE html><html><head><meta charset='utf-8'>"
            "<style>" + css + "</style></head><body>"
            + markdown_html(md) + "</body></html>")
