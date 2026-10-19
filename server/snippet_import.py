"""Snippet import for fengrid's SQLite store.

Translates two widely used snippet formats into the fengrid schema
(snippets.title / description / language / html / css / js / tags):

- **VSCode snippets** — `.code-snippets` and per-language `.json` files
  (JSONC: comments and trailing commas are allowed). Each snippet's
  `body` array becomes the code text; `scope` picks the target field.
- **massCode** — the app's SQLite database (`db.sqlite`). Content is
  stored per snippet as a JSON array of fragments
  `[{language, label, value}, ...]` (or, on older databases, a plain
  text column); tags are a JSON string array. The reader is defensive
  about column names across massCode versions.

Everything runs locally — no network, no external tools.
"""

import json
import os
import re
import sqlite3


# ----------------------------------------------------------------------
# language mapping — maps source language names to a fengrid field
# ('html', 'css', 'js') plus the fiddle language ('web' or 'markdown').
# Unmapped languages keep their code in the JS pane and record the raw
# language as a tag so it stays discoverable.
# ----------------------------------------------------------------------
_LANG_MAP = {
    "html": ("html", "web"), "htm": ("html", "web"), "xhtml": ("html", "web"),
    "vue": ("html", "web"), "svelte": ("html", "web"),
    "css": ("css", "web"), "scss": ("css", "web"), "sass": ("css", "web"),
    "less": ("css", "web"), "postcss": ("css", "web"),
    "javascript": ("js", "web"), "js": ("js", "web"),
    "typescript": ("js", "web"), "ts": ("js", "web"),
    "javascriptreact": ("js", "web"), "typescriptreact": ("js", "web"),
    "jsx": ("js", "web"), "tsx": ("js", "web"), "coffeescript": ("js", "web"),
    "json": ("js", "web"), "jsonc": ("js", "web"), "json5": ("js", "web"),
    "markdown": ("html", "markdown"), "md": ("html", "markdown"),
    "plaintext": ("html", "web"), "text": ("html", "web"), "plain": ("html", "web"),
}


def map_language(raw):
    """(field, fiddle_language, raw_or_None) — raw is tagged when unmapped."""
    if not raw:
        return "html", "web", None
    key = str(raw).strip().lower()
    if key in _LANG_MAP:
        field, fid = _LANG_MAP[key]
        return field, fid, None
    # long names first so 'javascriptreact' doesn't hit a 'javascript' prefix
    for known, val in _LANG_MAP.items():
        if key.startswith(known) or known.startswith(key) and len(key) > 2:
            field, fid = val
            return field, fid, None
    return "js", "web", str(raw).strip().lower().replace(" ", "-")


# ----------------------------------------------------------------------
# JSONC — VSCode snippet files allow // and /* */ comments and trailing
# commas. A small state machine strips comments while respecting string
# literals (so "http://…" survives), then trailing commas are removed.
# ----------------------------------------------------------------------
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
        first = str(scope).split(",")[0].strip() if scope else ""
        field, fid, raw = map_language(first)
        fields = {"html": "", "css": "", "js": ""}
        fields[field] = body
        tags = _norm_tags(sn.get("prefix"), raw and "lang:" + raw)
        out.append({
            "title": str(sn.get("title") or name).strip() or "Untitled snippet",
            "description": str(sn.get("description") or ""),
            "language": fid,
            "html": fields["html"], "css": fields["css"], "js": fields["js"],
            "tags": tags,
        })
    return out


# ----------------------------------------------------------------------
# massCode SQLite
# ----------------------------------------------------------------------
def parse_masscode_db(path):
    """Yield fengrid snippet dicts from a massCode db.sqlite file."""
    conn = sqlite3.connect("file:%s?mode=ro" % path.replace("?", "%3f"), uri=True)
    conn.row_factory = sqlite3.Row
    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        if "snippets" not in tables:
            raise ValueError("not a massCode database (no snippets table)")
        cols = {r[1] for r in conn.execute("PRAGMA table_info(snippets)").fetchall()}

        # tag lookup varies: a tags JSON column, or a join table
        tag_col = "tags" if "tags" in cols else None
        tag_join = None
        if tag_col is None:
            for cand in ("snippet_tags", "snippets_tags"):
                if cand in tables:
                    tag_join = cand
                    break
        tag_names = {}
        if tag_join and "tags" in tables:
            try:
                for t in conn.execute("SELECT id, name FROM tags").fetchall():
                    tag_names[t["id"]] = t["name"]
            except Exception:
                tag_names = {}

        name_col = "name" if "name" in cols else ("title" if "title" in cols else None)
        if name_col is None:
            raise ValueError("massCode snippets table has no name/title column")
        content_col = "content" if "content" in cols else ("content_text" if "content_text" in cols else None)
        if content_col is None:
            raise ValueError("massCode snippets table has no content column")
        lang_col = "language" if "language" in cols else None
        desc_col = "description" if "description" in cols else None
        deleted_col = "is_deleted" if "is_deleted" in cols else None

        sql = "SELECT * FROM snippets"
        if deleted_col:
            sql += " WHERE " + deleted_col + " = 0"
        out = []
        for row in conn.execute(sql).fetchall():
            title = str(row[name_col] or "Untitled snippet").strip() or "Untitled snippet"
            tags = ""
            if tag_col:
                tags = _norm_tags(_maybe_json(row[tag_col]))
            elif tag_join:
                try:
                    ids = _maybe_json_list(conn.execute(
                        "SELECT tag_id FROM %s WHERE snippet_id = ?" % tag_join,
                        (row["id"],)).fetchall())
                    tags = _norm_tags([tag_names.get(t, str(t)) for t in ids])
                except Exception:
                    tags = ""
            desc = str(row[desc_col] or "") if desc_col else ""
            raw_content = row[content_col]

            fragments = _split_fragments(raw_content, row[lang_col] if lang_col else None)
            fields = {"html": "", "css": "", "js": ""}
            fids, rawlangs = set(), []
            for lang, code in fragments:
                if not code or not str(code).strip():
                    continue
                field, fid, raw = map_language(lang)
                # a fragment joins its field; first-wins on conflicts
                if not fields[field]:
                    fields[field] = str(code)
                if fid:
                    fids.add(fid)
                if raw:
                    rawlangs.append("lang:" + raw)
            if not any(fields.values()):
                continue
            fid = "markdown" if "markdown" in fids else ("web" if fids else "web")
            out.append({
                "title": title, "description": desc, "language": fid,
                "html": fields["html"], "css": fields["css"], "js": fields["js"],
                "tags": _norm_tags(tags, rawlangs),
            })
        return out
    finally:
        conn.close()


def _maybe_json(v):
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return v
    return v


def _maybe_json_list(rows):
    out = []
    for r in rows:
        v = r[0] if not isinstance(r, sqlite3.Row) else r[0]
        out.append(_maybe_json(v) if isinstance(v, str) else v)
    flat = []
    for v in out:
        if isinstance(v, list):
            flat.extend(v)
        else:
            flat.append(v)
    return flat


def _split_fragments(content, fallback_lang):
    """massCode content → [(language, code), ...].

    v4+ stores a JSON array of fragment objects (value/value/code keys);
    older builds store plain text with a language column.
    """
    parsed = _maybe_json(content)
    if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
        frags = []
        for f in parsed:
            code = f.get("value") or f.get("code") or f.get("content") or ""
            lang = f.get("language") or f.get("lang") or ""
            frags.append((lang, code))
        return frags
    if isinstance(parsed, list) and parsed and all(isinstance(x, str) for x in parsed):
        return [(fallback_lang or "", "\n".join(parsed))]
    if isinstance(parsed, dict):
        code = parsed.get("value") or parsed.get("code") or ""
        return [(parsed.get("language") or fallback_lang or "", code)]
    return [(fallback_lang or "", str(content or ""))]


# ----------------------------------------------------------------------
# default search locations
# ----------------------------------------------------------------------
def vscode_default_paths():
    home = os.path.expanduser("~")
    dirs = [
        os.path.join(home, ".config/Code/User/snippets"),
        os.path.join(home, ".config/VSCodium/User/snippets"),
        os.path.join(home, ".config/Code - OSS/User/snippets"),
        os.path.join(home, ".config/Cursor/User/snippets"),
        os.path.join(home, "Library/Application Support/Code/User/snippets"),
        os.path.join(home, "Library/Application Support/VSCodium/User/snippets"),
        os.path.join(home, "AppData/Roaming/Code/User/snippets"),
        os.path.join(home, "AppData/Roaming/VSCodium/User/snippets"),
    ]
    out = []
    for d in dirs:
        if os.path.isdir(d):
            for fn in sorted(os.listdir(d)):
                if fn.endswith((".json", ".code-snippets")):
                    out.append(os.path.join(d, fn))
    return out


def masscode_default_paths():
    home = os.path.expanduser("~")
    cands = [
        os.path.join(home, ".config/massCode/db.sqlite"),
        os.path.join(home, ".config/masscode/db.sqlite"),
        os.path.join(home, "Library/Application Support/massCode/db.sqlite"),
        os.path.join(home, "AppData/Roaming/massCode/db.sqlite"),
        os.path.join(home, "AppData/Roaming/masscode/db.sqlite"),
    ]
    return [p for p in cands if os.path.isfile(p)]
