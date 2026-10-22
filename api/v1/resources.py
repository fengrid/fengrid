"""Endpoint handlers for the Fengrid REST API v1.

A route table maps (method, path-pattern) → handler(context, **params).
Handlers receive an `Api` context object (db path, data dir, scheduler)
and return plain dicts; the server wraps them in the JSON envelope.

Imports stay Qt-free: everything binds to `fengrid.core` directly, so
the API can run headless on a machine without a display.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import time
from pathlib import Path

try:
    from fengrid.core import backup as core_backup
    from fengrid.core import colors as core_colors
    from fengrid.core import db as core_db
    from fengrid.core import exportplus as xp
    from fengrid.core import ingest
    from fengrid.core import projects as core_projects
    from fengrid.core import snippets as core_snippets
    from fengrid.core import taxonomy
except ImportError:                              # run from a plain checkout
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "qt" / "src"))
    from fengrid.core import backup as core_backup
    from fengrid.core import colors as core_colors
    from fengrid.core import db as core_db
    from fengrid.core import exportplus as xp
    from fengrid.core import ingest
    from fengrid.core import projects as core_projects
    from fengrid.core import snippets as core_snippets
    from fengrid.core import taxonomy

from .middleware import ApiError


def version_fallback() -> str:
    """Resolve the app version after resources.py fixed up sys.path."""
    from fengrid import __version__
    return __version__

# asset kinds that live in the `asset` table vs their own tables
_ASSET_KINDS = ("icon", "font")


# ─────────────────────────────────────────────────────────── context
class Api:
    """Per-process API state: paths, connection factory, scheduler."""

    def __init__(self, db_path: str, data_dir: str | None = None,
                 scheduler=None):
        self.db_path = str(Path(db_path).resolve())
        self.data_dir = data_dir or str(Path(self.db_path).parent)
        self.scheduler = scheduler
        self.started = time.time()

    def con(self) -> sqlite3.Connection:
        return core_db.connect(self.db_path)

    def job(self, kind, fn, **kw):
        if self.scheduler is None:
            # synchronous fallback (in-process use / tests without server)
            try:
                return {"id": "sync", "state": "done", "result": fn()}
            except Exception as e:                     # noqa: BLE001
                raise ApiError(500, "job_failed", str(e))
        j = self.scheduler.submit(kind, fn, **kw)
        return {"id": j.id, "state": j.state, "kind": kind}


# ─────────────────────────────────────────────── helpers (shared shapes)
def _row_dict(row) -> dict:
    return {k: row[k] for k in row.keys()}


def _require_kind(kind: str) -> str:
    if kind not in ("icon", "font", "palette", "snippet", "project"):
        raise ApiError(400, "bad_kind",
                       "kind must be icon|font|palette|snippet|project")
    return kind


def _item_row(con, kind: str, item_id: int) -> dict:
    """Canonical row for any asset kind (labels normalised to `name`)."""
    if kind in _ASSET_KINDS:
        r = con.execute("SELECT * FROM asset WHERE id = ? AND kind = ?",
                        (item_id, kind)).fetchone()
        if r is None:
            raise ApiError(404, "not_found", f"{kind} {item_id} not found")
        d = _row_dict(r)
        d["name"] = d.get("name") or Path(d.get("path") or "").stem
        return d
    table = "palette" if kind == "palette" else (
        "snippet" if kind == "snippet" else "projects")
    r = con.execute(f"SELECT * FROM {table} WHERE id = ?",
                    (item_id,)).fetchone()
    if r is None:
        raise ApiError(404, "not_found", f"{kind} {item_id} not found")
    d = _row_dict(r)
    d["name"] = d.get("name") or d.get("title")
    return d


def _describe(con, kind: str, item_id: int) -> dict:
    d = _item_row(con, kind, item_id)
    d["kind"] = kind
    d["tags"] = core_db.tags_for(con, item_id, kind=kind) \
        if kind != "project" else []
    if kind != "project":
        d["starred"] = core_db.is_starred(con, item_id, kind=kind)
        d["custom_fields"] = {f["name"]: f["value"]
                              for f in taxonomy.asset_field_values(
                                  con, item_id, kind=kind)}
        d["collections"] = [
            {"id": r["collection_id"], "name": r["cname"]}
            for r in con.execute(
                "SELECT cr.collection_id, c.name AS cname FROM"
                " collection_ref cr JOIN collection c ON"
                " c.id = cr.collection_id WHERE cr.item_kind = ?"
                " AND cr.item_id = ?", (kind, item_id))]
    if kind in _ASSET_KINDS and d.get("path") and Path(d["path"]).exists():
        st = Path(d["path"]).stat()
        d["file"] = {"path": d["path"], "bytes": st.st_size,
                     "mtime": st.st_mtime}
    if kind == "snippet":
        d["language"] = d.get("language")
    if kind == "palette":
        d["colors"] = [r["hex"] for r in con.execute(
            "SELECT hex FROM palette_color WHERE palette_id = ?"
            " ORDER BY position", (item_id,))]
    return d


def _list_assets(con, kind: str, q: str, collection_id, starred: bool,
                 limit: int, offset: int) -> dict:
    if kind == "palette":
        rows = core_colors.list_palettes(con, q=q,
                                         collection_id=collection_id,
                                         starred_only=starred)
        items = [_row_dict(r) | {"kind": "palette"} for r in rows]
    elif kind == "snippet":
        rows = core_snippets.list_snippets(con, q=q,
                                           collection_id=collection_id,
                                           starred_only=starred)
        items = [_row_dict(r) | {"kind": "snippet"} for r in rows]
    elif kind in _ASSET_KINDS:
        where, params = ["a.kind = ?"], [kind]
        join = ""
        if q:
            where.append("a.name LIKE ?")
            params.append(f"%{q}%")
        if starred:
            join += (" JOIN item_tag st ON st.item_kind = a.kind"
                     " AND st.item_id = a.id"
                     " JOIN tag t ON t.id = st.tag_id AND t.name = 'starred'")
        if collection_id is not None:
            join += (" JOIN collection_ref cr ON cr.item_kind = a.kind"
                     " AND cr.item_id = a.id")
            where.append("cr.collection_id = ?")
            params.append(collection_id)
        rows = con.execute(
            f"SELECT a.* FROM asset a{join} WHERE {' AND '.join(where)}"
            " ORDER BY a.name COLLATE NOCASE LIMIT ? OFFSET ?",
            params + [limit, offset]).fetchall()
        items = []
        for r in rows:
            d = _row_dict(r)
            d["name"] = d.get("name") or Path(d.get("path") or "").stem
            d["kind"] = kind
            items.append(d)
    else:
        raise ApiError(400, "bad_kind",
                       "list needs kind=icon|font|palette|snippet")
    return {"items": items, "count": len(items), "kind": kind,
            "offset": offset, "limit": limit}


# ────────────────────────────────────────────────────────────── routes
def health(ctx: Api, body: dict) -> dict:
    from fengrid import __version__
    return {"ok": True, "version": __version__, "api": "v1",
            "uptime": round(time.time() - ctx.started, 1)}


def inventory(ctx: Api, body: dict) -> dict:
    """Aggregate counts — the 'what do I have' view."""
    con = ctx.con()
    try:
        out: dict = {"assets": {}, "starred": {}, "collections": 0,
                     "libraries": 0, "projects": 0, "tags": 0,
                     "sources": 0, "watch_folders": 0}
        for kind, table in (("icon", "asset"), ("font", "asset"),
                            ("palette", "palette"), ("snippet", "snippet")):
            if kind in _ASSET_KINDS:
                out["assets"][kind] = con.execute(
                    "SELECT COUNT(*) FROM asset WHERE kind = ?",
                    (kind,)).fetchone()[0]
            else:
                out["assets"][kind] = con.execute(
                    f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            out["starred"][kind] = con.execute(
                "SELECT COUNT(*) FROM item_tag it JOIN tag t"
                " ON t.id = it.tag_id WHERE t.name='starred'"
                " AND it.item_kind = ?", (kind,)).fetchone()[0]
        out["collections"] = con.execute(
            "SELECT COUNT(*) FROM collection").fetchone()[0]
        out["libraries"] = con.execute(
            "SELECT COUNT(*) FROM library_view").fetchone()[0]
        out["projects"] = con.execute(
            "SELECT COUNT(*) FROM projects").fetchone()[0]
        out["tags"] = con.execute("SELECT COUNT(*) FROM tag").fetchone()[0]
        out["sources"] = con.execute(
            "SELECT COUNT(*) FROM source").fetchone()[0]
        try:
            out["watch_folders"] = con.execute(
                "SELECT COUNT(*) FROM watch").fetchone()[0]
        except sqlite3.OperationalError:
            out["watch_folders"] = 0
        return out
    finally:
        con.close()


def assets_list(ctx: Api, body: dict, params: dict) -> dict:
    con = ctx.con()
    try:
        kind = _require_kind(params.get("kind") or "icon")
        starred = (params.get("starred") or "").lower() in ("1", "true", "yes")
        coll = params.get("collection")
        collection_id = int(coll) if coll and coll.isdigit() else None
        limit = min(int(params.get("limit") or 100), 500)
        offset = max(int(params.get("offset") or 0), 0)
        return _list_assets(con, kind, params.get("q") or "",
                            collection_id, starred, limit, offset)
    finally:
        con.close()


def assets_describe(ctx: Api, body: dict, kind: str, item_id: int) -> dict:
    con = ctx.con()
    try:
        return _describe(con, _require_kind(kind), int(item_id))
    finally:
        con.close()


def assets_patch(ctx: Api, body: dict, kind: str, item_id: int) -> dict:
    """Edit/update/save: rename, re-tag, set custom fields."""
    kind = _require_kind(kind)
    con = ctx.con()
    try:
        _item_row(con, kind, int(item_id))          # 404 when missing
        name = body.get("name")
        if kind in _ASSET_KINDS and name:
            con.execute("UPDATE asset SET name = ? WHERE id = ?",
                        (str(name), int(item_id)))
        elif kind == "palette" and name:
            con.execute("UPDATE palette SET name = ? WHERE id = ?",
                        (str(name), int(item_id)))
        elif kind == "snippet" and (name or body.get("title")):
            con.execute("UPDATE snippet SET title = ? WHERE id = ?",
                        (str(name or body["title"]), int(item_id)))
        if isinstance(body.get("tags"), list):
            core_db.sync_item_tags(con, int(item_id), kind,
                                   ",".join(str(t) for t in body["tags"]))
        for fname, value in (body.get("fields") or {}).items():
            fr = con.execute("SELECT id FROM asset_field WHERE name = ?",
                             (fname,)).fetchone()
            if fr is None:
                raise ApiError(400, "unknown_field",
                               f"no custom field named '{fname}'")
            taxonomy.set_field_value(con, int(item_id), fr[0], str(value),
                                     kind=kind)
        con.commit()
        return _describe(con, kind, int(item_id))
    finally:
        con.close()


def assets_star(ctx: Api, body: dict, kind: str, item_id: int) -> dict:
    kind = _require_kind(kind)
    con = ctx.con()
    try:
        core_db.set_starred(con, int(item_id),
                            bool(body.get("on", True)), kind=kind)
        return {"id": int(item_id), "kind": kind,
                "starred": core_db.is_starred(con, int(item_id), kind=kind)}
    finally:
        con.close()


def assets_tags(ctx: Api, body: dict, kind: str, item_id: int) -> dict:
    kind = _require_kind(kind)
    tags = body.get("tags")
    if not isinstance(tags, list):
        raise ApiError(400, "bad_request", "body needs tags: [..]")
    con = ctx.con()
    try:
        core_db.sync_item_tags(con, int(item_id), kind,
                               ",".join(str(t) for t in tags))
        return {"id": int(item_id), "kind": kind,
                "tags": core_db.tags_for(con, int(item_id), kind=kind)}
    finally:
        con.close()


def assets_collect(ctx: Api, body: dict, kind: str, item_id: int) -> dict:
    kind = _require_kind(kind)
    cid = int(body.get("collection_id") or 0)
    if not cid:
        raise ApiError(400, "bad_request", "collection_id required")
    con = ctx.con()
    try:
        ref_id = core_db.add_collection_ref(con, cid, kind, int(item_id))
        return {"ref_id": ref_id, "collection_id": cid,
                "kind": kind, "item_id": int(item_id)}
    finally:
        con.close()


def assets_uncollect(ctx: Api, body: dict, kind: str, item_id: int,
                     ref_id: int) -> dict:
    con = ctx.con()
    try:
        core_db.remove_collection_ref(con, int(ref_id))
        return {"removed": int(ref_id)}
    finally:
        con.close()


def assets_copy(ctx: Api, body: dict, kind: str, item_id: int) -> dict:
    """Copy/duplicate an item: file-level for icons/fonts (new indexed
    asset), row-level for palettes/snippets."""
    kind = _require_kind(kind)
    con = ctx.con()
    try:
        src = _item_row(con, kind, int(item_id))
        now = time.time()
        if kind in _ASSET_KINDS:
            p = src.get("path") or ""
            if not p or not Path(p).exists():
                raise ApiError(409, "file_missing",
                               f"source file missing: {p}")
            dest = Path(p).with_name(Path(p).stem + "-copy" + Path(p).suffix)
            i = 1
            while dest.exists():
                dest = Path(p).with_name(
                    f"{Path(p).stem}-copy{i}{Path(p).suffix}")
                i += 1
            shutil.copy2(p, dest)
            cur = con.execute(
                "INSERT INTO asset(source_id, kind, path, name, theme,"
                " context, ext, size_px, width, height, bytes, colorspace,"
                " color_count, mono, mtime, family, style, weight, italic)"
                " SELECT source_id, kind, ?, ?, theme, context, ext,"
                " size_px, width, height, bytes, colorspace, color_count,"
                " mono, ?, family, style, weight, italic"
                " FROM asset WHERE id = ?",
                (str(dest), dest.stem, now, int(item_id)))
            new_id = int(cur.lastrowid or 0)
            for t in core_db.tags_for(con, int(item_id), kind=kind):
                core_db.add_tag(con, new_id, t, kind=kind)
            con.commit()
            return {"copied": {"id": new_id, "kind": kind,
                               "path": str(dest)}}
        table = "palette" if kind == "palette" else "snippet"
        if kind == "palette":
            cur = con.execute(
                "INSERT INTO palette(name, tags, created, updated)"
                " VALUES (?, ?, ?, ?)",
                (src["name"] + " copy", src.get("tags"), now, now))
            new_pal = int(cur.lastrowid or 0)
            con.execute(
                "INSERT INTO palette_color(palette_id, position, hex,"
                " locked) SELECT ?, position, hex, locked FROM"
                " palette_color WHERE palette_id = ?",
                (new_pal, int(item_id)))
        else:
            cur = con.execute(
                "INSERT INTO snippet(title, description, language, tags,"
                " html, css, js, created, updated)"
                " SELECT title || ' copy', description, language, tags,"
                " html, css, js, ?, ? FROM snippet WHERE id = ?",
                (now, now, int(item_id)))
        new_id = int(cur.lastrowid or 0) if kind != "palette" else new_pal
        for t in core_db.tags_for(con, int(item_id), kind=kind):
            core_db.add_tag(con, new_id, t, kind=kind)
        con.commit()
        return {"copied": {"id": new_id, "kind": kind}}
    finally:
        con.close()


def assets_ingest(ctx: Api, body: dict) -> dict:
    """Ingest/import: files, zip, or a whole folder → job."""
    paths = body.get("paths") or []
    mode = body.get("mode") or "copy"
    if mode not in ("copy", "link"):
        raise ApiError(400, "bad_mode", "mode must be copy|link")
    if body.get("zip_path"):
        zp = str(body["zip_path"])
        if not Path(zp).exists():
            raise ApiError(404, "not_found", f"no such file: {zp}")

        def run():
            rep = ingest.import_zip(zp, ctx.data_dir, mode=mode)
            rep["last_export_dir"] = rep.get("dest")
            return rep
        return ctx.job("import", run)
    if body.get("folder"):
        folder = str(body["folder"])
        if not Path(folder).is_dir():
            raise ApiError(404, "not_found", f"no such folder: {folder}")

        def run():
            return ingest.import_folder(folder, mode=mode)
        return ctx.job("import", run)
    real = [p for p in paths if Path(p).exists()]
    if not real:
        raise ApiError(400, "bad_request",
                       "body needs paths: [..] (existing files),"
                       " zip_path, or folder")

    def run():
        rep = ingest.import_files(real, ctx.data_dir, mode=mode)
        rep["last_export_dir"] = rep.get("dest")
        return rep
    return ctx.job("import", run)


def assets_export(ctx: Api, body: dict) -> dict:
    """Export: scope = icons|fonts|palettes|snippets|bundle, with the
    same extended per-type options the app exposes."""
    scope = body.get("scope") or "bundle"
    dest = body.get("dest") or str(Path(ctx.data_dir) / "exports"
                                   / f"api-{int(time.time())}")
    opts = body.get("opts") or {}
    Path(dest).mkdir(parents=True, exist_ok=True)

    if scope == "icons":
        paths = body.get("paths") or []
        if not paths:
            raise ApiError(400, "bad_request", "icons export needs paths")

        def run():
            rows = [{"name": Path(p).stem, "path": p} for p in paths]
            return xp.export_icons(
                rows, dest, fmts=list(opts.get("formats") or ["png"]),
                size=(int(opts["size"])
                      if str(opts.get("size", "orig")) not in
                      ("orig", "", "None") else None),
                tint=str(opts.get("tint", "")),
                script=str(opts.get("script", "")),
                script_enabled=bool(opts.get("script_enabled")))
    elif scope == "fonts":
        family = body.get("family")
        if not family:
            raise ApiError(400, "bad_request", "fonts export needs family")

        def run():
            with ctx.con() as con:
                return xp.export_fonts_web(
                    con, family, dest,
                    fmts=list(opts.get("formats") or ["woff2"]),
                    weights=opts.get("weights") or None)
    elif scope == "palettes":
        name = body.get("name")
        hexes = body.get("colors") or []
        if not name or not hexes:
            raise ApiError(400, "bad_request",
                           "palettes export needs name + colors")

        def run():
            written = []
            for k in list(opts.get("formats") or ["css", "json"]):
                if k in ("txt", "csv", "md"):
                    out = Path(dest) / f"{name}.{k}"
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_text(xp.color_code_lines(list(hexes),
                                                       None, k),
                                   encoding="utf-8")
                    written.append(str(out))
                else:
                    written.append(core_colors.write_exports(
                        name, list(hexes), dest, k))
            return {"written": len(written), "outputs": written,
                    "dest": dest}
    elif scope == "snippets":
        kind = opts.get("snippet_kind") or "zip"

        def run():
            with ctx.con() as con:
                cols = ("id, title, language, description, tags,"
                        " html, css, js")
                ids = body.get("ids") or []
                if ids:
                    qm = ",".join("?" * len(ids))
                    rows = [dict(r) for r in con.execute(
                        f"SELECT {cols} FROM snippet WHERE id IN ({qm})",
                        list(ids))]
                else:
                    rows = [dict(r) for r in con.execute(
                        f"SELECT {cols} FROM snippet ORDER BY title")]
            return xp.export_snippets(rows, dest, kind=kind)
    elif scope == "bundle":
        with_files = bool(body.get("with_files", True))

        def run():
            with ctx.con() as con:
                return xp.export_bundle(con, dest, scope=body.get("subset")
                                        or "all", with_files=with_files)
    else:
        raise ApiError(400, "bad_scope",
                       "scope must be icons|fonts|palettes|snippets|bundle")

    def wrap():
        rep = run()          # noqa: F821 — bound per scope branch above
        if isinstance(rep, dict):
            rep.setdefault("dest", dest)
        return rep
    return ctx.job("export", wrap)


def collections_list(ctx: Api, body: dict) -> dict:
    con = ctx.con()
    try:
        return {"items": core_db.collection_tree(con)}
    finally:
        con.close()


def collections_create(ctx: Api, body: dict) -> dict:
    name = (body.get("name") or "").strip()
    if not name:
        raise ApiError(400, "bad_request", "name required")
    con = ctx.con()
    try:
        cid = core_db.create_sub_collection(
            con, name,
            parent_id=int(body.get("parent_id") or 0),
            tags=body.get("tags") or "")
        return {"id": cid, "name": name}
    finally:
        con.close()


def collections_describe(ctx: Api, body: dict, cid: int) -> dict:
    con = ctx.con()
    try:
        row = con.execute("SELECT * FROM collection WHERE id = ?",
                          (int(cid),)).fetchone()
        if row is None:
            raise ApiError(404, "not_found", f"collection {cid} not found")
        d = _row_dict(row)
        d["refs"] = core_db.refs_for(con, int(cid))
        return d
    finally:
        con.close()


def collections_delete(ctx: Api, body: dict, cid: int) -> dict:
    con = ctx.con()
    try:
        core_db.delete_collection(con, int(cid))
        return {"deleted": int(cid)}
    finally:
        con.close()


def collections_refs(ctx: Api, body: dict, cid: int) -> dict:
    con = ctx.con()
    try:
        return {"items": core_db.refs_for(con, int(cid))}
    finally:
        con.close()


def collections_add_ref(ctx: Api, body: dict, cid: int) -> dict:
    kind = _require_kind(body.get("kind") or "icon")
    item_id = int(body.get("item_id") or 0)
    if not item_id:
        raise ApiError(400, "bad_request", "item_id required")
    con = ctx.con()
    try:
        ref_id = core_db.add_collection_ref(con, int(cid), kind, item_id)
        return {"ref_id": ref_id}
    finally:
        con.close()


def libraries_list(ctx: Api, body: dict) -> dict:
    """Saved library views (tag-driven smart subsets)."""
    con = ctx.con()
    try:
        items = []
        for v in taxonomy.list_library_views(con):
            d = _row_dict(v)
            d["asset_ids"] = taxonomy.library_view_assets(con, d["id"])
            items.append(d)
        return {"items": items}
    finally:
        con.close()


def libraries_create(ctx: Api, body: dict) -> dict:
    name = (body.get("name") or "").strip()
    if not name:
        raise ApiError(400, "bad_request", "name required")
    con = ctx.con()
    try:
        vid = taxonomy.create_library_view(
            con, name, body.get("tags") or "",
            match_all=bool(body.get("match_all", False)))
        return {"id": vid, "name": name}
    finally:
        con.close()


def tags_list(ctx: Api, body: dict) -> dict:
    con = ctx.con()
    try:
        rows = con.execute(
            "SELECT t.id, t.name, COUNT(it.item_id) AS uses FROM tag t"
            " LEFT JOIN item_tag it ON it.tag_id = t.id"
            " GROUP BY t.id ORDER BY t.name COLLATE NOCASE").fetchall()
        return {"items": [_row_dict(r) for r in rows]}
    finally:
        con.close()


def tags_rename(ctx: Api, body: dict, name: str) -> dict:
    new = (body.get("new") or "").strip()
    if not new:
        raise ApiError(400, "bad_request", "new name required")
    con = ctx.con()
    try:
        changed = core_db.rename_tag(con, name, new)
        if not changed:
            raise ApiError(404, "not_found", f"tag '{name}' not found")
        return {"renamed": name, "to": new}
    finally:
        con.close()


def tags_delete(ctx: Api, body: dict, name: str) -> dict:
    con = ctx.con()
    try:
        if not core_db.delete_tag(con, name):
            raise ApiError(404, "not_found", f"tag '{name}' not found")
        return {"deleted": name}
    finally:
        con.close()


def fields_list(ctx: Api, body: dict) -> dict:
    con = ctx.con()
    try:
        return {"items": taxonomy.list_fields(con)}
    finally:
        con.close()


def fields_create(ctx: Api, body: dict) -> dict:
    con = ctx.con()
    try:
        fid = taxonomy.create_field(con, body.get("name") or "",
                                    body.get("type") or "text",
                                    body.get("options"))
        return {"id": fid}
    except ValueError as e:
        raise ApiError(400, "bad_field", str(e))
    finally:
        con.close()


def fields_delete(ctx: Api, body: dict, fid: int) -> dict:
    con = ctx.con()
    try:
        taxonomy.delete_field(con, int(fid))
        return {"deleted": int(fid)}
    finally:
        con.close()


def projects_list(ctx: Api, body: dict) -> dict:
    con = ctx.con()
    try:
        return {"items": core_projects.list_projects(con, q=body.get("q")
                                                     or "")}
    finally:
        con.close()


def projects_describe(ctx: Api, body: dict, pid: int) -> dict:
    con = ctx.con()
    try:
        p = core_projects.get_project(con, int(pid))
        if p is None:
            raise ApiError(404, "not_found", f"project {pid} not found")
        p["assets"] = core_projects.list_assets(con, int(pid))
        return p
    finally:
        con.close()


def backups_list(ctx: Api, body: dict) -> dict:
    dest = Path(ctx.data_dir) / "backups"
    if not dest.is_dir():
        return {"items": []}
    items = []
    for p in sorted(dest.glob("*.tar.gz"), key=lambda x: -x.stat().st_mtime):
        items.append({"name": p.name, "bytes": p.stat().st_size,
                      "path": str(p), "mtime": p.stat().st_mtime})
    return {"items": items}


def backup_create(ctx: Api, body: dict) -> dict:
    dest = body.get("dest") or str(Path(ctx.data_dir) / "backups")

    def run():
        return core_backup.backup(ctx.db_path, dest)
    return ctx.job("backup", run)


def backup_restore(ctx: Api, body: dict) -> dict:
    path = str(body.get("path") or "")
    if not Path(path).exists():
        raise ApiError(404, "not_found", f"no such backup: {path}")

    def run():
        return core_backup.restore(path, ctx.db_path)
    return ctx.job("restore", run)


def db_admin(ctx: Api, body: dict, op: str) -> dict:
    """check | vacuum | checkpoint | optimize | rebuild_fts | sweep."""
    if op not in ("check", "vacuum", "checkpoint", "optimize",
                  "rebuild_fts", "sweep"):
        raise ApiError(400, "bad_op", f"unknown db admin op: {op}")

    ops = {
        "check": core_backup.quick_check,
        "vacuum": core_backup.vacuum,
        "checkpoint": core_backup.checkpoint,
        "optimize": getattr(core_backup, "optimize", None)
                    or core_backup.vacuum,
        "rebuild_fts": core_backup.rebuild_fts,
    }
    sweep = getattr(core_backup, "sweep", None)
    if op == "sweep":
        if sweep is None:
            raise ApiError(501, "not_implemented",
                           "orphan sweep not available in this build")

        def run():
            con = ctx.con()
            try:
                return sweep(con)
            finally:
                con.close()
    else:
        fn = ops[op]

        def run():
            con = ctx.con()
            try:
                return fn(con)
            finally:
                con.close()
    return ctx.job(f"db:{op}", run)


def watch_list(ctx: Api, body: dict) -> dict:
    con = ctx.con()
    try:
        rows = con.execute(
            "SELECT * FROM watch_source ORDER BY id").fetchall()
        return {"items": [_row_dict(r) for r in rows]}
    except sqlite3.OperationalError as e:
        raise ApiError(409, "schema_missing",
                       f"watch_source unavailable: {e}")
    finally:
        con.close()


def watch_create(ctx: Api, body: dict) -> dict:
    name = (body.get("name") or "").strip()
    remote = (body.get("remote") or "").strip()
    transport = body.get("transport") or "local"
    if not name or not remote:
        raise ApiError(400, "bad_request", "name and remote required")
    con = ctx.con()
    try:
        cur = con.execute(
            "INSERT INTO watch_source(path, label, transport, interval,"
            " enabled) VALUES (?, ?, ?, ?, 1)",
            (remote, name, transport, int(body.get("interval") or 300)))
        con.commit()
        return {"id": int(cur.lastrowid or 0)}
    except sqlite3.OperationalError as e:
        raise ApiError(409, "schema_missing",
                       f"watch_source unavailable: {e}")
    finally:
        con.close()


def watch_delete(ctx: Api, body: dict, wid: int) -> dict:
    con = ctx.con()
    try:
        con.execute("DELETE FROM watch_source WHERE id = ?", (int(wid),))
        con.execute("DELETE FROM watch_state WHERE watch_id = ?",
                    (int(wid),))
        con.commit()
        return {"deleted": int(wid)}
    finally:
        con.close()


def watch_run(ctx: Api, body: dict, wid: int) -> dict:
    raise ApiError(501, "not_implemented",
                   "watch run-now requires the Qt watch worker;"
                   " schedule it in the app or implement a headless pull"
                   " here (see core.watch.run_pull)")


# ──────────────────────────────────────────────────────────────── jobs
def jobs_list(ctx: Api, body: dict, params: dict) -> dict:
    active = (params.get("active") or "").lower() in ("1", "true", "yes")
    if ctx.scheduler is None:
        return {"items": [], "note": "no scheduler (in-process use)"}
    return {"items": ctx.scheduler.list_jobs(active_only=active)}


def jobs_get(ctx: Api, body: dict, jid: str) -> dict:
    if ctx.scheduler is None:
        raise ApiError(404, "not_found", "no scheduler (in-process use)")
    job = ctx.scheduler.get(jid)
    if job is None:
        raise ApiError(404, "not_found", f"job {jid} not found")
    d = job.to_dict()
    d["result"] = job.result
    return d


def jobs_cancel(ctx: Api, body: dict, jid: str) -> dict:
    if ctx.scheduler is None:
        raise ApiError(404, "not_found", "no scheduler (in-process use)")
    if not ctx.scheduler.cancel(jid):
        raise ApiError(404, "not_found", f"job {jid} not found")
    return {"cancelled": jid}
