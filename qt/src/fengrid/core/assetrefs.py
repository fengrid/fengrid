"""Asset reference links — the [[ … ]] namespace used in Snippets and
Project code.

Three reference forms, resolved against the library database:

  [[ slug ]]                                  unique user slug (fastest)
  [[ GUID ]]                                  the generated GUID (stable)
  [[ type/namespace/collection/asset name ]]  path form — type is one of
      icon/font/code/image/video/audio/doc/data/docs/file/spatial/
      timeseries/markdown, namespace is the library (icon theme /
      source root), collection an owning collection or context, and
      the last segment the asset name.

Expansion rewrites each reference to a URL the app understands:
`fengrid-asset://<absolute file path>` for file-backed assets (the
hardened WebEngine scheme handler serves exactly those whitelisted
paths) or `fengrid://open/<kind>/<id>` for virtual objects (snippets,
palettes) that have no file. Unresolved references are left untouched
so users can see the broken link instead of silently dropped content.
"""

from __future__ import annotations

import re

from . import db as core_db

REF_RE = re.compile(r"\[\[\s*([^\[\]]+?)\s*\]\]")

UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

# user-facing type segment → tracked kind
TYPE_ALIASES = {
    "icon": "icon", "icons": "icon",
    "font": "font", "fonts": "font",
    "code": "snippet", "snippet": "snippet", "snippets": "snippet",
    "image": "image", "images": "image", "img": "image",
    "video": "video", "videos": "video",
    "audio": "audio", "sound": "audio",
    "doc": "doc", "docs": "doc", "document": "doc",
    "data": "data",
    "file": "file", "files": "file",
    "spatial": "spatial", "gis": "spatial", "gps": "spatial",
    "timeseries": "timeseries", "ts": "timeseries",
    "markdown": "markdown", "md": "markdown",
}


def resolve(con, ref: str) -> dict | None:
    """Resolve one reference string to a locator dict:
    {kind, id, guid, path, slug} — or None when nothing matches."""
    ref = (ref or "").strip()
    if not ref:
        return None
    # GUID form
    if UUID_RE.match(ref):
        hit = core_db.lookup_by_guid(con, ref)
        if hit:
            return _hydrate(con, hit["kind"], hit["id"])
        return None
    # path form: type/... segments
    if "/" in ref:
        return _resolve_path(con, ref)
    # slug form
    hit = core_db.lookup_by_slug(con, ref)
    if hit:
        return _hydrate(con, hit["kind"], hit["id"])
    return None


def _hydrate(con, kind: str, item_id: int) -> dict | None:
    from . import kinds as core_kinds
    if kind in core_kinds.ALL_KINDS:
        row = con.execute(
            "SELECT id, path, name, guid, slug FROM asset"
            " WHERE id = ? AND kind = ?", (item_id, kind)).fetchone()
        if row is None:
            return None
        return {"kind": kind, "id": row["id"], "path": row["path"],
                "name": row["name"], "guid": row["guid"],
                "slug": row["slug"] or ""}
    table = {"snippet": "snippet", "palette": "palette",
             "project": "projects"}.get(kind)
    if table is None:
        return None
    row = con.execute(
        f"SELECT id, guid, slug FROM {table} WHERE id = ?",
        (item_id,)).fetchone()
    if row is None:
        return None
    return {"kind": kind, "id": row["id"], "path": None, "guid": row["guid"],
            "slug": row["slug"] or ""}


def _resolve_path(con, ref: str) -> dict | None:
    parts = [p.strip() for p in ref.split("/") if p.strip()]
    if not parts:
        return None
    kind_seg = TYPE_ALIASES.get(parts[0].lower(), parts[0].lower())
    name = parts[-1]
    middles = parts[1:-1]
    if kind_seg == "file":
        kind_seg = None                      # any asset-table kind
    asset_kinds = None
    if kind_seg is None:
        from . import kinds as core_kinds
        asset_kinds = tuple(core_kinds.ALL_KINDS)
    elif kind_seg in ("snippet", "palette", "project"):
        # virtual objects: title/name match only
        table = {"snippet": "snippet", "palette": "palette",
                 "project": "projects"}[kind_seg]
        col = "title" if kind_seg == "snippet" else "name"
        row = con.execute(
            f"SELECT id, guid, slug FROM {table} WHERE lower({col}) = ?",
            (name.lower(),)).fetchone()
        if row is None:
            return None
        return {"kind": kind_seg, "id": row["id"], "path": None,
                "name": name, "guid": row["guid"], "slug": row["slug"] or ""}
    else:
        asset_kinds = (kind_seg,)

    # candidate file-backed assets by kind + name (case-insensitive)
    marks = ",".join("?" * len(asset_kinds))
    rows = con.execute(
        f"SELECT id, kind, path, name, guid, slug, theme, context"
        f" FROM asset WHERE kind IN ({marks}) AND lower(name) = ?",
        (*asset_kinds, name.lower())).fetchall()
    if not rows:
        return None
    if len(middles) <= 1 and len(rows) == 1:
        return _row_hit(rows[0])
    # score candidates against the middle segments (theme, context,
    # collection membership — the user's namespace/collection path)
    lower_middles = [m.lower() for m in middles]
    best, best_score = None, -1
    for r in rows:
        score = 0
        theme = (r["theme"] or "").lower()
        context = (r["context"] or "").lower()
        if theme in lower_middles:
            score += 2
        if context in lower_middles:
            score += 2
        for m in lower_middles:
            if con.execute(
                    "SELECT 1 FROM collection_ref cr JOIN collection c"
                    " ON c.id = cr.collection_id"
                    " WHERE cr.item_kind = ? AND cr.item_id = ?"
                    " AND lower(c.name) = ?", (r["kind"], r["id"],
                                               m)).fetchone():
                score += 1
        if score > best_score:
            best, best_score = r, score
    return _row_hit(best) if best is not None else None


def _row_hit(r) -> dict:
    return {"kind": r["kind"], "id": r["id"], "path": r["path"],
            "name": r["name"], "guid": r["guid"], "slug": r["slug"] or ""}


def url_for(hit: dict, scheme: str = "fengrid-asset") -> str:
    """The URL a [[ ref ]] expands to in rendered HTML."""
    if hit.get("path"):
        return f"{scheme}://{hit['path']}"
    return f"fengrid://open/{hit['kind']}/{hit['id']}"


def expand(con, text: str, scheme: str = "fengrid-asset") -> tuple[str, list]:
    """Rewrite every [[ … ]] reference in `text`. Returns
    (expanded_text, unresolved_refs). Unresolved refs are left as-is."""
    unresolved: list[str] = []

    def sub(m: re.Match) -> str:
        ref = m.group(1)
        hit = resolve(con, ref)
        if hit is None:
            unresolved.append(ref)
            return m.group(0)            # keep the visible broken link
        return url_for(hit, scheme)

    return REF_RE.sub(sub, text or ""), unresolved
