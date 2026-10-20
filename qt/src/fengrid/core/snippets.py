"""Snippet store: CRUD + import from VSCode / massCode (code pane, M3).

Ports server/snippet_import.py 1:1 (jsonc_loads, map_language, the VSCode
and massCode readers) and adds the SQLite CRUD that 0.x served over
/api/snippets. Same schema and semantics as the 0.x snippets.db so a
user's existing store imports losslessly.
"""

from __future__ import annotations

import json
import re
import sqlite3
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


# --------------------------------------------------------------------------
# SQLite CRUD — the schema itself lives in core.db (SCHEMA), so any
# connect() path guarantees the snippet tables exist before this module is
# used. CRUD here is intentionally schema-free.
# --------------------------------------------------------------------------
def list_snippets(con, q="", lang="", sort="updated"):
    """(id, title, description, language, tags, created, updated) rows."""
    sql = ("SELECT id, title, description, language, tags, created, updated"
           " FROM snippet")
    where, args = [], []
    if q:
        like = "%" + q.lower() + "%"
        where.append("(lower(title) LIKE ? OR lower(description) LIKE ?"
                     " OR lower(tags) LIKE ? OR lower(html) LIKE ?"
                     " OR lower(css) LIKE ? OR lower(js) LIKE ?)")
        args += [like] * 6
    if lang:
        where.append("language = ?")
        args.append(lang)
    if where:
        sql += " WHERE " + " AND ".join(where)
    order = {"updated": "updated DESC, id DESC",
             "created": "created DESC, id DESC",
             "title": "title COLLATE NOCASE ASC, id ASC"}.get(sort, "updated DESC, id DESC")
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
        "INSERT INTO snippet (title, description, language, html, css, js, tags)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (title, description, language, html, css, js, tags))
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
