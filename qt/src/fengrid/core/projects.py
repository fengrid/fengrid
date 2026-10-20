"""Projects core: the design-token coordinator and its export archive.

Port of the 0.x projects.html configurator + serve.py _export_project,
adapted to the Qt core's data model: icon/font assets are rows of the
library `asset` table (absolute paths, family metadata on font rows)
instead of files in an install tree. The generated outputs — tokens.css,
fonts.css, icons.css, icons.js, the boilerplate index.html, snippet pages,
palettes.json, manifest.json — match the 0.x exporter.

The live preview renders the SAME boilerplate (build_site_html with inline
CSS), so what you see is what exports.
"""

from __future__ import annotations

import io
import json
import re
import sqlite3
import tarfile
import time
import zipfile
from pathlib import Path

DEFAULT_SETTINGS = {
    "prefix": "fg",
    "iconSize": 32,
    "colors": {
        "bg": "", "surface": "", "ink": "", "muted": "",
        "accent": "", "border": "", "radius": 10,
    },
    "paletteId": None,
    "type": {"body": "", "heading": "", "baseSize": 16, "scale": 1.25},
    "preview": {"mode": "site", "snippetId": None},
}

ASSET_KINDS = ("icon", "font", "snippet", "palette")

_FONT_FORMATS = {"ttf": "truetype", "otf": "opentype", "woff": "woff",
                 "woff2": "woff2"}


# --------------------------------------------------------------- persistence

def list_projects(con: sqlite3.Connection, q: str = "", tag: str = "") -> list[dict]:
    sql = ("SELECT id, name, description, tags, created, updated"
           " FROM projects")
    wh, args = [], []
    if q:
        wh.append("(name LIKE ? OR description LIKE ? OR tags LIKE ?)")
        args += ["%" + q + "%"] * 3
    if tag:
        wh.append("(',' || tags || ',') LIKE ?")
        args.append("%," + tag + ",%")
    if wh:
        sql += " WHERE " + " AND ".join(wh)
    sql += " ORDER BY updated DESC"
    rows = [dict(r) for r in con.execute(sql, args).fetchall()]
    for r in rows:
        r["asset_count"] = con.execute(
            "SELECT COUNT(*) AS c FROM project_asset WHERE project_id = ?",
            (r["id"],)).fetchone()["c"]
    return rows


def create_project(con: sqlite3.Connection, name: str,
                   description: str = "", tags: str = "") -> int:
    cur = con.execute(
        "INSERT INTO projects (name, description, tags, settings)"
        " VALUES (?,?,?,?)",
        (name.strip() or "Untitled project", description, tags,
         json.dumps(DEFAULT_SETTINGS)))
    con.commit()
    return int(cur.lastrowid or 0)


def get_project(con: sqlite3.Connection, pid: int) -> dict | None:
    row = con.execute("SELECT * FROM projects WHERE id = ?", (pid,)).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["settings"] = json.loads(d["settings"] or "{}")
    d["assets"] = list_assets(con, pid)
    return d


def list_assets(con: sqlite3.Connection, pid: int) -> list[dict]:
    return [dict(r) for r in con.execute(
        "SELECT id, asset_kind, asset_id, label FROM project_asset"
        " WHERE project_id = ? ORDER BY asset_kind, id", (pid,)).fetchall()]


def update_project(con: sqlite3.Connection, pid: int, name=None,
                   description=None, tags=None, settings=None) -> None:
    fields, args = [], []
    if name is not None:
        fields.append("name = ?"); args.append(name)
    if description is not None:
        fields.append("description = ?"); args.append(description)
    if tags is not None:
        fields.append("tags = ?"); args.append(tags)
    if settings is not None:
        fields.append("settings = ?"); args.append(json.dumps(settings))
    if not fields:
        return
    fields.append("updated = datetime('now')")
    args.append(pid)
    con.execute("UPDATE projects SET " + ", ".join(fields) + " WHERE id = ?",
                args)
    con.commit()


def delete_project(con: sqlite3.Connection, pid: int) -> None:
    con.execute("DELETE FROM project_asset WHERE project_id = ?", (pid,))
    con.execute("DELETE FROM projects WHERE id = ?", (pid,))
    con.commit()


def add_asset(con: sqlite3.Connection, pid: int, kind: str, asset_id: int,
              label: str = "") -> bool:
    """Attach an existing library row (asset/snippet/palette) to a project.

    Returns False when the kind is unknown or the row does not exist —
    the 0.x server validated the same way before INSERT OR IGNORE.
    """
    if kind not in ASSET_KINDS:
        return False
    if kind in ("icon", "font"):
        row = con.execute("SELECT id FROM asset WHERE id = ? AND kind = ?",
                          (asset_id, kind)).fetchone()
    elif kind == "snippet":
        row = con.execute("SELECT id FROM snippet WHERE id = ?",
                          (asset_id,)).fetchone()
    else:
        row = con.execute("SELECT id FROM palette WHERE id = ?",
                          (asset_id,)).fetchone()
    if row is None:
        return False
    con.execute(
        "INSERT OR IGNORE INTO project_asset"
        " (project_id, asset_kind, asset_id, label) VALUES (?,?,?,?)",
        (pid, kind, asset_id, label))
    con.execute("UPDATE projects SET updated = datetime('now') WHERE id = ?",
                (pid,))
    con.commit()
    return True


def remove_asset(con: sqlite3.Connection, pid: int, row_id: int) -> None:
    con.execute("DELETE FROM project_asset WHERE id = ? AND project_id = ?",
                (row_id, pid))
    con.commit()


# ------------------------------------------------------------------ resolution

def _resolve_asset(con: sqlite3.Connection, kind: str, asset_id: int):
    """(archive_path, filesystem_path) for an attached library row, or None.

    Icons archive under assets/icons/<name>.<ext>; fonts under
    assets/fonts/<family>/<file> so the @font-face urls are stable.
    """
    row = con.execute(
        "SELECT path, name, ext, family FROM asset WHERE id = ? AND kind = ?",
        (asset_id, kind)).fetchone()
    if row is None:
        return None
    ext = (row["ext"] or "").lstrip(".") or "png"
    if kind == "icon":
        arc = "assets/icons/%s.%s" % (row["name"], ext)
    else:
        family = (row["family"] or row["name"]).replace(" ", "_")
        arc = "assets/fonts/%s/%s.%s" % (family, row["name"], ext)
    return arc, row["path"]


def _palette_rows(con, ids: list[int]) -> list[dict]:
    out = []
    for pid in ids:
        row = con.execute("SELECT * FROM palette WHERE id = ?",
                          (pid,)).fetchone()
        if row is None:
            continue
        colors = [r["hex"] for r in con.execute(
            "SELECT hex FROM palette_color WHERE palette_id = ?"
            " ORDER BY position", (pid,)).fetchall()]
        out.append({"id": row["id"], "name": row["name"], "colors": colors})
    return out


# ------------------------------------------------------------------- generator

def _gather(con, project) -> dict:
    """Collect every row the generator needs, in asset order."""
    pid = project["id"]
    assets = list_assets(con, pid)
    palettes, snippets, icons, fonts = [], [], [], []
    for a in assets:
        kind, aid = a["asset_kind"], a["asset_id"]
        if kind == "palette":
            rows = _palette_rows(con, [aid])
            if rows:
                palettes.append(rows[0])
        elif kind == "snippet":
            row = con.execute("SELECT * FROM snippet WHERE id = ?",
                              (aid,)).fetchone()
            if row:
                snippets.append(dict(row))
        else:
            r = _resolve_asset(con, kind, aid)
            if r:
                (icons if kind == "icon" else fonts).append((a, r))
    return {"assets": assets, "palettes": palettes,
            "snippets": snippets, "icons": icons, "fonts": fonts}


def _slug(raw: str, fallback: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", (raw or "").lower()).strip("-") \
        or fallback


def build_tokens(prefix: str, s: dict, palettes: list[dict]) -> tuple[list[str], dict]:
    """The :root token block + the resolved role colors (also reused by the
    live preview). Roles fall back positionally to the first palette, then
    to the 0.x dark defaults."""
    cols = s.get("colors") or {}
    typ = s.get("type") or {}
    pal0 = palettes[0]["colors"] if palettes else []

    def role(key, pal_idx, default):
        v = cols.get(key)
        if v:
            return v
        return pal0[pal_idx] if pal_idx < len(pal0) else default

    roles = {
        "bg": role("bg", 0, "#101418"),
        "surface": role("surface", 1, "#161B21"),
        "accent": role("accent", 2, "#39B8C4"),
        "muted": role("muted", 3, "#93A3B0"),
        "ink": role("ink", 4, "#E7EDF2"),
        "border": role("border", 1, "#2A333B"),
    }
    radius = int(cols.get("radius", 10) or 10)
    base_px = int(typ.get("baseSize", 16) or 16)
    try:
        ratio = float(typ.get("scale", 1.25) or 1.25)
    except (TypeError, ValueError):
        ratio = 1.25

    lines = [":root {"]
    for name in ("bg", "surface", "ink", "muted", "accent", "border"):
        lines.append("  --%s-%s: %s;" % (prefix, name, roles[name]))
    lines.append("  --%s-radius: %dpx;" % (prefix, radius))
    lines.append("  --%s-font-body: %s;" % (prefix, typ.get("_bodyStack", "system-ui, sans-serif")))
    lines.append("  --%s-font-head: %s;" % (prefix, typ.get("_headStack", typ.get("_bodyStack", "system-ui, sans-serif"))))
    for name, mult in (("fs-small", -0.25), ("fs-base", 0), ("fs-h3", 1),
                       ("fs-h2", 2), ("fs-h1", 3), ("fs-hero", 4)):
        lines.append("  --%s-%s: %spx;"
                     % (prefix, name, round(base_px * (ratio ** mult), 1)))
    for pal in palettes:
        base = _slug(pal.get("name"), "palette")
        for i, c in enumerate(pal["colors"]):
            lines.append("  --%s-%s-%d: %s;" % (prefix, base, i + 1, c))
    lines.append("}")
    return lines, roles


def _font_faces(fonts: list) -> tuple[list[str], dict]:
    """@font-face lines + family -> [(arcname, format)] map."""
    fam_files: dict[str, list] = {}
    lines = []
    for a, (arcname, abspath) in fonts:
        ext = Path(abspath).suffix.lower().lstrip(".")
        fmt = _FONT_FORMATS.get(ext, "truetype")
        family = (a.get("label") or
                  (Path(abspath).parent.name.replace("_", " ")))
        fam_files.setdefault(family, []).append((arcname, fmt))
        lines.append(
            "@font-face { font-family: '%s'; src: url('%s') format('%s'); }"
            % (family.replace("'", "\\'"), arcname, fmt))
    return lines, fam_files


def _stack_for(fam, fam_files, fallback):
    if fam:
        return "'%s', %s" % (fam.replace("'", "\\'"), fallback)
    return fallback


def build_site_html(con, project: dict, g: dict, inline_css: bool = False) -> str:
    """The boilerplate site — the live preview AND the exported index.html."""
    s = project.get("settings") or {}
    prefix = _slug(str(s.get("prefix", "fg")), "fg")
    icon_px = int(s.get("iconSize", 32) or 32)
    typ = s.get("type") or {}
    pv = s.get("preview") or {}
    palettes, icons, fonts = g["palettes"], g["icons"], g["fonts"]

    fonts_css, fam_files = _font_faces(fonts)
    body_fam = typ.get("body") or (sorted(fam_files)[0] if fam_files else "")
    head_fam = typ.get("heading") or body_fam
    body_stack = _stack_for(body_fam, fam_files, "system-ui, sans-serif")
    head_stack = (_stack_for(head_fam, fam_files, body_stack)
                  if head_fam != body_fam else body_stack)
    s.setdefault("type", {})
    s["type"]["_bodyStack"] = body_stack
    s["type"]["_headStack"] = head_stack
    tokens, roles = build_tokens(prefix, s, palettes)
    s["type"].pop("_bodyStack", None)
    s["type"].pop("_headStack", None)

    icons_css = []
    for a, (arcname, _) in icons:
        stem = Path(arcname).stem
        cls = _slug(a.get("label") or stem, "icon")
        icons_css.append(".%s-%s { background-image: url('%s'); }"
                         % (prefix, cls, arcname))
    icons_js = ("window.%sIcons = {\n  %s\n};\n" % (
        prefix, ",\n  ".join('  "%s": "%s"' % (Path(arc).stem, arc)
                             for _, (arc, _) in icons))
        if icons else "window.%sIcons = {};\n" % prefix)

    icon_imgs = "\n".join(
        '        <div class="icon" style="background-image:url(\'%s\')" title="%s"></div>'
        % (arc, Path(arc).stem) for _, (arc, _) in icons[:6])
    swatches = "\n".join(
        '      <div class="swatch" style="background:%s"><span>%s</span></div>'
        % (c, c) for pal in palettes for c in pal["colors"])
    desc = (project.get("description") or
            "A starter site generated from this project's design tokens.")
    ratio = float(typ.get("scale", 1.25) or 1.25)
    base_px = int(typ.get("baseSize", 16) or 16)

    links = ("<link rel=\"stylesheet\" href=\"css/tokens.css\">\n"
             "<link rel=\"stylesheet\" href=\"css/fonts.css\">\n"
             "<link rel=\"stylesheet\" href=\"css/icons.css\">")
    if inline_css:
        links = ("<style>\n" + "\n".join(tokens) + "\n"
                 + "\n".join(fonts_css) + "\n" + "\n".join(icons_css)
                 + "\n</style>")

    template = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{project["name"]} — generated by fengrid</title>
{links}
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:var(--{prefix}-bg); color:var(--{prefix}-ink);
         font-family:var(--{prefix}-font-body); font-size:var(--{prefix}-fs-base); line-height:1.6; }}
  h1, h2, h3 {{ font-family:var(--{prefix}-font-head); line-height:1.2; margin:0 0 .5em; }}
  .wrap {{ max-width: 960px; margin: 0 auto; padding: 0 24px; }}
  .site-head {{ display:flex; align-items:center; gap:20px; padding:16px 0;
                border-bottom:1px solid var(--{prefix}-border); }}
  .brand {{ font-weight:700; font-size:var(--{prefix}-fs-h3); }}
  .site-head nav {{ display:flex; gap:16px; margin-left:auto; color:var(--{prefix}-muted); }}
  .btn {{ display:inline-block; padding:10px 22px; border-radius:var(--{prefix}-radius);
          font-size:var(--{prefix}-fs-small); text-decoration:none; cursor:pointer; border:1px solid transparent; }}
  .btn-primary {{ background:var(--{prefix}-accent); color:var(--{prefix}-bg); }}
  .btn-ghost {{ border-color:var(--{prefix}-border); color:var(--{prefix}-ink); }}
  .hero {{ padding:64px 0 48px; }}
  .hero h1 {{ font-size:var(--{prefix}-fs-hero); }}
  .hero p {{ color:var(--{prefix}-muted); max-width:52ch; font-size:var(--{prefix}-fs-h3); }}
  .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr));
            gap:16px; padding:24px 0 48px; }}
  .card {{ background:var(--{prefix}-surface); border:1px solid var(--{prefix}-border);
           border-radius:var(--{prefix}-radius); padding:20px; }}
  .card h3 {{ font-size:var(--{prefix}-fs-h3); }}
  .card p {{ color:var(--{prefix}-muted); margin:0; }}
  .icon {{ width:{icon_px}px; height:{icon_px}px; background-size:contain;
           background-repeat:no-repeat; background-position:center; margin-bottom:10px; }}
  .type-spec {{ padding:32px 0; border-top:1px solid var(--{prefix}-border); }}
  .type-spec h1 {{ font-size:var(--{prefix}-fs-h1); }}
  .type-spec h2 {{ font-size:var(--{prefix}-fs-h2); }}
  .type-spec h3 {{ font-size:var(--{prefix}-fs-h3); }}
  .type-spec .small {{ font-size:var(--{prefix}-fs-small); color:var(--{prefix}-muted); }}
  .pal {{ padding:32px 0; border-top:1px solid var(--{prefix}-border); }}
  .swatches {{ display:flex; flex-wrap:wrap; gap:10px; margin-top:12px; }}
  .swatch {{ width:96px; height:64px; border-radius:var(--{prefix}-radius); display:flex;
             align-items:flex-end; justify-content:center; padding-bottom:6px;
             font:11px/1 monospace; color:rgba(255,255,255,.85);
             text-shadow:0 1px 2px rgba(0,0,0,.5); }}
  footer {{ border-top:1px solid var(--{prefix}-border); padding:20px 0 40px;
            color:var(--{prefix}-muted); font-size:var(--{prefix}-fs-small); }}
</style>
</head>
<body>
  <div class="wrap">
    <header class="site-head">
      <span class="brand">{project["name"]}</span>
      <nav><span>Overview</span><span>Components</span><span>Type</span></nav>
      <a class="btn btn-primary" href="#">Get started</a>
    </header>
    <section class="hero">
      <h1>{project["name"]}</h1>
      <p>{desc}</p>
      <p><a class="btn btn-primary" href="#">Primary action</a>
         <a class="btn btn-ghost" href="#">Secondary</a></p>
    </section>
    <section class="cards">
      <div class="card">
{icon_imgs or '        <div class="icon"></div>'}
        <h3>Components</h3>
        <p>Cards, buttons, and forms styled by the tokens above.</p>
      </div>
      <div class="card">
        <h3>Typography</h3>
        <p>Type set on a {ratio:g} modular scale from a {base_px}px base.</p>
      </div>
      <div class="card">
        <h3>Palette</h3>
        <p>{len(palettes[0]["colors"]) if palettes else 0} palette colors available as custom properties.</p>
      </div>
    </section>
    <section class="type-spec">
      <h1>Heading one</h1>
      <h2>Heading two</h2>
      <h3>Heading three</h3>
      <p>Body copy renders in the body family at the base size. The quick
         brown fox jumps over the lazy dog.</p>
      <p class="small">Small text for captions and metadata.</p>
    </section>
    <section class="pal">
      <h2>Palette</h2>
      <div class="swatches">
{swatches or '      <div class="swatch">no palette</div>'}
      </div>
    </section>
    <footer>Generated by fengrid — {time.strftime("%Y-%m-%d")}</footer>
  </div>
  <script src="js/icons.js"></script>
</body>
</html>
"""
    return template


def build_snippet_page(con, project, g, prefix) -> tuple[str, str] | None:
    """The snippet-driven preview page (export + live preview 'snippet' mode)."""
    s = project.get("settings") or {}
    pv = s.get("preview") or {}
    if str(pv.get("mode") or "") != "snippet" or not pv.get("snippetId"):
        return None
    row = con.execute("SELECT * FROM snippet WHERE id = ?",
                      (int(pv["snippetId"]),)).fetchone()
    if row is None:
        return None
    sn = dict(row)
    slug = _slug(str(sn["title"] or ""), "preview-snippet")
    page = ("<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\">\n"
            "<title>%s — fengrid preview</title>\n"
            "<link rel=\"stylesheet\" href=\"../css/tokens.css\">\n"
            "<link rel=\"stylesheet\" href=\"../css/fonts.css\">\n"
            "<link rel=\"stylesheet\" href=\"../css/icons.css\">\n"
            "<style>body{margin:0;padding:32px;background:var(--%s-bg);"
            "color:var(--%s-ink);font-family:var(--%s-font-body);}</style>\n"
            "</head>\n<body>\n%s\n<style>\n%s\n</style>\n<script>\n%s\n</script>\n"
            "</body>\n</html>\n"
            % (sn["title"], prefix, prefix, prefix, sn.get("html", ""),
               sn.get("css", ""), sn.get("js", "")))
    return "snippets/%s.html" % slug, page


def build_manifest(con, project, g) -> dict:
    s = project.get("settings") or {}
    return {
        "name": project["name"],
        "description": project.get("description", ""),
        "tags": project.get("tags", ""),
        "settings": {k: v for k, v in s.items()},
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "generator": "fengrid",
        "assets": [{"type": a["asset_kind"], "id": a["asset_id"],
                    "label": a.get("label", "")} for a in g["assets"]],
        "palettes": [{"name": p["name"], "colors": p["colors"]}
                     for p in g["palettes"]],
    }


def export_project(con, project: dict, dest: str, fmt: str = "zip") -> dict:
    """Write the distributable archive; returns {path, files, bytes}."""
    g = _gather(con, project)
    s = project.get("settings") or {}
    prefix = _slug(str(s.get("prefix", "fg")), "fg")

    fonts_css, fam_files = _font_faces(g["fonts"])
    typ = s.get("type") or {}
    body_fam = typ.get("body") or (sorted(fam_files)[0] if fam_files else "")
    head_fam = typ.get("heading") or body_fam
    body_stack = _stack_for(body_fam, fam_files, "system-ui, sans-serif")
    head_stack = (_stack_for(head_fam, fam_files, body_stack)
                  if head_fam != body_fam else body_stack)
    tokens, _ = build_tokens(prefix, {**s, "type": {**typ,
                                                    "_bodyStack": body_stack,
                                                    "_headStack": head_stack}},
                             g["palettes"])

    icons_css = [".%s-%s { background-image: url('%s'); }" % (
        prefix, _slug(a.get("label") or Path(arc).stem, "icon"), arc)
        for a, (arc, _) in g["icons"]]
    icons_js = ("window.%sIcons = {\n  %s\n};\n" % (
        prefix, ",\n  ".join('  "%s": "%s"' % (Path(arc).stem, arc)
                             for _, (arc, _) in g["icons"]))
        if g["icons"] else "window.%sIcons = {};\n" % prefix)

    template = build_site_html(con, project, g, inline_css=False)
    snippet_entry = build_snippet_page(con, project, g, prefix)
    manifest = build_manifest(con, project, g)

    manifest["settings"] = {k: v for k, v in (project.get("settings") or {}).items()}
    readme = "# %s\n\n%s\n\nGenerated by fengrid (%s).\n\n" % (
        project["name"], project.get("description") or "",
        manifest["generated"])
    readme += ("## Contents\n\n"
               "- `index.html` — boilerplate site driven by the design tokens\n"
               "- `css/tokens.css` — design tokens: color roles, radius, type scale, font stacks\n"
               "- `css/fonts.css` — @font-face rules for the selected families\n"
               "- `css/icons.css` — icon classes\n"
               "- `js/icons.js` — icon name map\n"
               "- `assets/` — the selected files\n"
               "- `manifest.json` — project specification and configuration\n")
    if snippet_entry:
        readme += ("- `%s` — the snippet chosen as the preview source, wrapped"
                   " in the tokens\n" % snippet_entry[0])

    fmt = "targz" if str(fmt) in ("targz", "tar.gz", "tgz") else "zip"
    entries: list[tuple[str, "str | bytes"]] = [
        ("manifest.json", json.dumps(manifest, indent=2)),
        ("README.md", readme),
        ("css/tokens.css", "\n".join(tokens) + "\n"),
        ("js/icons.js", icons_js),
        ("index.html", template),
   ]
    if fonts_css:
        entries.append(("css/fonts.css", "\n".join(fonts_css) + "\n"))
    if icons_css:
        entries.append(("css/icons.css", "\n".join(icons_css) + "\n"))
    if snippet_entry:
        entries.append(snippet_entry)
    if g["palettes"]:
        entries.append(("palettes.json", json.dumps(
            [{"name": p["name"], "colors": p["colors"]} for p in g["palettes"]],
            indent=2)))
    for i, sn in enumerate(g["snippets"]):
        entries.append((
            "snippets/%02d-%s.html" % (i + 1, _slug(sn["title"], "snippet")),
            "<!DOCTYPE html>\n<!-- %s\n%s -->\n%s" % (
                sn["title"], sn.get("description", ""), sn.get("html", ""))))
    for a, (arcname, abspath) in g["icons"] + g["fonts"]:
        entries.append((arcname, Path(abspath).read_bytes()))

    dest_path = Path(dest)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "zip":
        with zipfile.ZipFile(dest_path, "w", zipfile.ZIP_DEFLATED) as z:
            for name, data in entries:
                z.writestr(name, data)
    else:
        with tarfile.open(dest_path, "w:gz") as t:
            for name, data in entries:
                raw = data if isinstance(data, bytes) else data.encode("utf-8")
                info = tarfile.TarInfo(name)
                info.size = len(raw)
                info.mtime = int(time.time())
                t.addfile(info, io.BytesIO(raw))
    return {"path": str(dest_path), "files": len(entries),
            "bytes": dest_path.stat().st_size}
