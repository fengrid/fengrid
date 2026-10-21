"""Extended export suite — the reason nobody needs a conversion site or
a photo editor for icon work.

Shared by import (SVG rasterisation) and export:
  - render_svg: Qt SVG → PNG (thread-safe: QSvgRenderer + QImage)
  - tint: recolor a raster through its alpha channel (the "Photoshop
    color filter across some icons" case — one pass, alpha preserved)
  - export_icons: MULTI-format batch with resize/tint/batch-ops/script
  - export_fonts_web: webfont packaging (woff2/woff via fontTools) +
    variant packages with a relative-URL @font-face stylesheet
  - color_codes: HEX/HSL/RGB/CMYK text lists (txt/csv/md)
  - export_snippets: bundle/vscode/masscode/plain files
  - export_bundle / import_manifest: library·collection·project bundles
    (JSON manifest + files, round-trippable)

Every batch function is a plain generator-style loop (ONE file in
memory at a time), takes progress( done, total ) and should_stop().
Script hooks run argv lists through an INJECTABLE runner — never a
shell, tests never spawn processes.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import zipfile
from pathlib import Path

from . import export as core_export
from .export import ExportError, FORMATS as ICON_FORMATS

BUNDLE_MANIFEST = "fengrid-bundle.json"
BUNDLE_VERSION = 1


# ── SVG rasterisation (Qt-free callers use Pillow rasters) ───────────
def render_svg(src: str | Path, dest: str | Path, size: int = 512) -> Path:
    """SVG → PNG at `size`² via Qt (QSvgRenderer is usable off the main
    thread; painting into a QImage touches no GUI state)."""
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    renderer = QSvgRenderer(str(src))
    if not renderer.isValid():
        raise ExportError(f"cannot render SVG: {src}")
    img = QImage(int(size), int(size), QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    renderer.render(p, QRectF(0, 0, size, size))
    p.end()
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not img.save(str(dest)):
        raise ExportError(f"cannot write {dest}")
    return dest


def tint_image(src: str | Path, color: str) -> Path:
    """Recolor THROUGH THE ALPHA CHANNEL — keeps glyph shapes, drops
    every original hue (works for any monochrome-ish icon; multi-color
    artwork keeps only its alpha silhouette, which is the documented
    behavior of a tint, not a hue-shift). Writes `src.tint.png`."""
    from PIL import Image

    src = Path(src)
    r, g, b = _parse_color(color)
    with Image.open(src) as im:
        im = im.convert("RGBA")
        solid = Image.new("RGBA", im.size, (r, g, b, 255))
        solid.putalpha(im.getchannel("A"))
        out = src.with_name(src.stem + ".tint.png")
        solid.save(out, format="PNG")
    return out


def _parse_color(color: str) -> tuple[int, int, int]:
    from .colors import hex2rgb
    c = (color or "").strip()
    if c.startswith("rgb("):
        nums = [int(x.strip()) for x in c[4:-1].split(",")[:3]]
        return tuple(max(0, min(255, n)) for n in nums)  # type: ignore
    return hex2rgb(c if c.startswith("#") else "#" + c)


# ── icons ────────────────────────────────────────────────────────────
def export_icons(rows: list[dict], dest_dir: str | Path, *,
                 fmts: list[str], size: int | None = None,
                 tint: str = "", script: str = "",
                 script_enabled: bool = False,
                 runner=None, progress=None,
                 should_stop=None) -> dict:
    """Batch icon export into EVERY selected format.

    rows: [{name, path, ext}] (or any dict with those keys)
    script: argv template with {in}/{out} placeholders, executed per
            OUTPUT file through `runner` (defaults to subprocess argv,
            no shell). Failures are collected, never abort the batch.
    """
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    fmts = [f.lower().replace("jpg", "jpeg") for f in fmts if f]
    fmts = [f for f in fmts if f in ICON_FORMATS] or ["png"]
    report = {"files": 0, "written": 0, "failed": 0, "errors": [],
              "outputs": []}
    for i, row in enumerate(rows):
        if should_stop is not None and should_stop():
            report["errors"].append("cancelled")
            break
        src = Path(str(row.get("path", "")))
        stem = str(row.get("name") or src.stem or "icon")
        work = None
        try:
            if not src.is_file():
                raise FileNotFoundError(str(src))
            work = src
            if src.suffix.lower() == ".svg":
                tmp = dest / (".render-" + re.sub(r"[^A-Za-z0-9._-]", "_",
                                                  stem)[:60] + ".png")
                render_svg(src, tmp, size or 512)
                work = tmp
            if tint:
                t = tint_image(work, tint)
                if work != src and work != t:
                    Path(work).unlink(missing_ok=True)
                work = t
            for fmt in fmts:
                out = core_export.export(work, dest, stem, fmt, size)
                report["outputs"].append(str(out))
                report["written"] += 1
                if script_enabled and script.strip():
                    _run_script(script, out, runner, report)
        except Exception as e:
            report["failed"] += 1
            if len(report["errors"]) < 20:
                report["errors"].append(f"{stem}: {e}")
        finally:
            if work is not None and work != src:
                Path(work).unlink(missing_ok=True)
        if progress is not None:
            progress(i + 1, len(rows))
    report["files"] = len(rows)
    return report


def _run_script(template: str, out_path, runner, report) -> None:
    """Batch operation on an exported file: template tokens {in} {out}
    {dir} {name}. argv only — shlex, never shell=True."""
    out_path = Path(out_path)
    try:
        argv = [a.format(**{"in": str(out_path), "out": str(out_path),
                            "dir": str(out_path.parent),
                            "name": out_path.stem})
                for a in shlex.split(template)]
    except (ValueError, KeyError) as e:
        report["failed"] += 1
        report["errors"].append(f"script template: {e}")
        return
    if not argv:
        return
    run = runner if runner is not None else _default_runner
    try:
        code = run(argv)
        if code not in (0, None):
            report["failed"] += 1
            report["errors"].append(f"script exit {code}: {out_path.name}")
    except Exception as e:
        report["failed"] += 1
        report["errors"].append(f"script: {e}")


def _default_runner(argv: list) -> int:
    import subprocess
    proc = subprocess.run(argv, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL, timeout=120)
    return proc.returncode


# ── fonts: webfonts + variant packages ───────────────────────────────
def convert_font(src: str | Path, dest_dir: str | Path,
                 flavor: str) -> Path:
    """TTF/OTF → woff2 | woff (fontTools; brotli ships with the venv
    for woff2). ttf/otf = straight copy."""
    from fontTools.ttLib import TTFont

    src, dest_dir = Path(src), Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / (src.stem + "." + flavor)
    if flavor in ("ttf", "otf"):
        if src.suffix.lower().lstrip(".") == flavor:
            out.write_bytes(src.read_bytes())
            return out
        flavor_in = "otf" if src.suffix.lower() == ".otf" else "ttf"
        out = dest_dir / (src.stem + "." + flavor_in)
        out.write_bytes(src.read_bytes())
        return out
    if flavor not in ("woff", "woff2"):
        raise ExportError(f"unknown font format: {flavor}")
    font = TTFont(str(src))
    font.flavor = flavor
    tmp = out.with_suffix(out.suffix + ".tmp")
    font.save(str(tmp))
    font.close()
    os.replace(tmp, out)
    return out


def export_fonts_web(con, family: str, dest_dir: str | Path, *,
                     fmts: list[str] | None = None,
                     weights: list[int] | None = None,
                     progress=None) -> dict:
    """Variant package: every (or weight-filtered) file of the family,
    converted to the chosen web formats, zipped with a stylesheet whose
    URLs are RELATIVE (portable — the css/zip export used file:// URIs,
    which break the moment the folder moves)."""
    from . import fonts as core_fonts

    fmts = [f for f in (fmts or ["woff2"]) if f in ("woff2", "woff",
                                                    "ttf", "otf")] \
        or ["woff2"]
    files = core_fonts.family_files(con, family)
    if weights:
        files = [f for f in files
                 if int(f.get("weight") or 400) in weights]
    if not files:
        raise ExportError(f"no font files for {family!r}")
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", family).strip("_") or "fonts"
    out = dest_dir / f"{stem}-webfonts.zip"
    css_rules = []
    written = 0
    for i, meta in enumerate(files):
        p = Path(meta["path"])
        if not p.is_file():
            continue
        weight = int(meta.get("weight") or 400)
        style = "italic" if meta.get("italic") else "normal"
        fam = (meta.get("family") or family).replace('"', '\\"')
        srcs = []
        for fmt in fmts:
            conv = convert_font(p, dest_dir / ".webfonts-stage", fmt)
            written += 1
            srcs.append(f"url(\"../fonts/{conv.name}\") format(\"{fmt}\")")
        css_rules.append(
            "@font-face {\n"
            f"  font-family: \"{fam}\";\n"
            "  src: " + ",\n       ".join(srcs) + ";\n"
            f"  font-weight: {weight};\n"
            f"  font-style: {style};\n"
            "  font-display: swap;\n}")
        if progress is not None:
            progress(i + 1, len(files))
    stage = dest_dir / ".webfonts-stage"
    tmp = out.with_suffix(".zip.tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        if stage.exists():
            for f in sorted(stage.iterdir()):
                zf.write(f, f"fonts/{f.name}")
        zf.writestr("css/fonts.css",
                    f"/* fengrid webfonts — {family} */\n\n"
                    + "\n\n".join(css_rules) + "\n")
        zf.writestr("README.txt",
                    f"{family} — webfont package (fengrid)\n\n"
                    "fonts/ holds the converted files; css/fonts.css has\n"
                    "relative @font-face rules. Respect each font's\n"
                    "license when redistributing.\n")
    os.replace(tmp, out)
    import shutil as _sh
    _sh.rmtree(stage, ignore_errors=True)
    return {"path": str(out), "files": written,
            "styles": len(css_rules)}


# ── colors: code lists ───────────────────────────────────────────────
def rgb_to_cmyk(hexv: str) -> tuple[float, float, float, float]:
    from .colors import hex2rgb
    r, g, b = (v / 255.0 for v in hex2rgb(hexv))
    k = 1 - max(r, g, b)
    if k >= 1.0:
        return (0.0, 0.0, 0.0, 100.0)
    c = (1 - r - k) / (1 - k)
    m = (1 - g - k) / (1 - k)
    y = (1 - b - k) / (1 - k)
    return (round(c * 100, 1), round(m * 100, 1), round(y * 100, 1),
            round(k * 100, 1))


def color_code_lines(hexes: list[str], names: list[str] | None = None,
                     fmt: str = "txt") -> str:
    """HEX / HSL / RGB / CMYK list — the thing people open conversion
    sites for. fmt: txt | csv | md."""
    from .colors import hex2rgb, rgb2hsl

    rows = []
    for i, h in enumerate(hexes):
        r, g, b = hex2rgb(h)
        hh, ss, ll = rgb2hsl(r, g, b)
        c, m, y, k = rgb_to_cmyk(h)
        label = (names[i] if names and i < len(names)
                 else f"color-{i + 1:02d}")
        # rgb2hsl returns h in degrees, s/l ALREADY in 0..100
        rows.append({
            "name": label, "hex": h.upper(),
            "rgb": f"rgb({r}, {g}, {b})",
            "hsl": f"hsl({round(hh)}, {round(ss)}%, "
                   f"{round(ll)}%)",
            "cmyk": f"cmyk({c}%, {m}%, {y}%, {k}%)",
        })
    if fmt == "csv":
        head = "name,hex,rgb,hsl,cmyk"
        body = "\n".join(
            f"{_csvq(r['name'])},{r['hex']},{_csvq(r['rgb'])},"
            f"{_csvq(r['hsl'])},{_csvq(r['cmyk'])}" for r in rows)
        return head + "\n" + body + "\n"
    if fmt == "md":
        head = "| name | hex | rgb | hsl | cmyk |\n" \
               "|------|-----|-----|-----|------|"
        body = "\n".join(
            f"| {r['name']} | `{r['hex']}` | `{r['rgb']}` | "
            f"`{r['hsl']}` | `{r['cmyk']}` |" for r in rows)
        return head + "\n" + body + "\n"
    return "\n".join(
        f"{r['name']}: {r['hex']}  {r['rgb']}  {r['hsl']}  {r['cmyk']}"
        for r in rows) + "\n"


def _csvq(s: str) -> str:
    return f'"{s}"' if any(ch in s for ch in ',"\n') else s


# ── snippets ─────────────────────────────────────────────────────────
def export_snippets(rows: list[dict], dest_dir: str | Path, *,
                    kind: str = "bundle") -> dict:
    """rows: [{id,title,language,description,tags,html,css,js}].
    kind: bundle (fengrid json) | vscode (.code-snippets) |
          masscode (json) | files (one file per language)."""
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    written = []
    if kind == "vscode":
        out = dest / "fengrid.code-snippets"
        body = {}
        for r in rows:
            body[r["title"]] = {
                "scope": _vscode_scope(r.get("language", "")),
                "prefix": r["title"][:24].lower().replace(" ", "-"),
                "body": (r.get("html") or r.get("css") or r.get("js")
                         or "").split("\n"),
                "description": r.get("description", ""),
            }
        out.write_text(json.dumps(body, indent=2), encoding="utf-8")
        written.append(str(out))
    elif kind == "masscode":
        out = dest / "snippets-masscode.json"
        out.write_text(json.dumps([
            {"name": r["title"], "code": r.get("html") or r.get("css")
             or r.get("js") or "", "language": r.get("language", "web")}
            for r in rows], indent=2), encoding="utf-8")
        written.append(str(out))
    elif kind == "files":
        for r in rows:
            lang = (r.get("language") or "web").lower()
            code = (r.get("html") or r.get("css") or r.get("js") or "")
            ext = {"web": "html", "html": "html", "css": "css",
                   "js": "js", "markdown": "md", "md": "md"}.get(lang, "txt")
            safe = re.sub(r"[^A-Za-z0-9._-]+", "-", r["title"]).strip("-")
            out = dest / f"{safe or 'snippet'}.{ext}"
            out.write_text(code, encoding="utf-8")
            written.append(str(out))
    else:  # bundle
        out = dest / "fengrid-snippets.json"
        out.write_text(json.dumps({
            "fengrid": "snippets", "version": BUNDLE_VERSION,
            "snippets": [dict(r) for r in rows]}, indent=2),
            encoding="utf-8")
        written.append(str(out))
    return {"written": len(written), "outputs": written}


def _vscode_scope(lang: str) -> str:
    return {"html": "html, css, javascript", "css": "css",
            "js": "javascript", "javascript": "javascript",
            "markdown": "markdown", "md": "markdown"}.get(
        (lang or "").lower(), "")


# ── bundles: libraries · collections · projects ──────────────────────
def export_bundle(con, dest_dir: str | Path, *, scope: str,
                  with_files: bool = True, progress=None) -> dict:
    """scope: 'library' | 'collection:<id>' | 'project:<id>' — a zip of
    fengrid-bundle.json + the referenced files (portable library)."""
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    entries, label = _bundle_rows(con, scope)
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", label).strip("-") or "library"
    out = dest / f"{slug}.fengrid.zip"
    manifest = {
        "fengrid": "bundle", "version": BUNDLE_VERSION, "scope": scope,
        "label": label,
        "assets": entries,
        "collections": [dict(r) for r in con.execute(
            "SELECT id, name FROM collection ORDER BY id")],
        "tags": [dict(r) for r in con.execute(
            "SELECT id, name FROM tag ORDER BY id")],
    }
    # per-asset tag links (only for bundled assets)
    ids = [e["id"] for e in entries]
    links = []
    for i in range(0, len(ids), 400):
        chunk = ids[i:i + 400]
        q = ",".join("?" * len(chunk))
        for r in con.execute(
                f"SELECT it.item_id AS id, t.name AS tag FROM item_tag it"
                f" JOIN tag t ON t.id = it.tag_id"
                f" WHERE it.item_kind IN ('icon','font')"
                f" AND it.item_id IN ({q})",
                chunk):
            links.append(dict(r))
    manifest["tag_links"] = links
    # collection membership for bundled assets (round-trip)
    coll_links = []
    for i in range(0, len(ids), 400):
        chunk = ids[i:i + 400]
        q = ",".join("?" * len(chunk))
        for r in con.execute(
                f"SELECT cr.collection_id AS cid, cr.item_id AS id,"
                f" c.name AS collection FROM collection_ref cr"
                f" JOIN collection c ON c.id = cr.collection_id"
                f" WHERE cr.item_kind IN ('icon','font')"
                f" AND cr.item_id IN ({q})", chunk):
            coll_links.append({"collection": r["collection"],
                               "id": r["id"]})
    manifest["collection_links"] = coll_links
    if scope.startswith("project:"):
        pid = int(scope.split(":", 1)[1])
        prow = con.execute(
            "SELECT name, description, settings FROM projects"
            " WHERE id = ?", (pid,)).fetchone()
        if prow:
            manifest["project"] = {"name": prow[0],
                                   "description": prow[1],
                                   "settings": prow[2]}
    tmp = out.with_suffix(".zip.tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(BUNDLE_MANIFEST, json.dumps(manifest, indent=1))
        if with_files:
            for i, e in enumerate(entries):
                p = Path(e["path"])
                if p.is_file():
                    zf.write(p, f"files/{e['id']}_{p.name}")
                if progress is not None:
                    progress(i + 1, len(entries))
    os.replace(tmp, out)
    return {"path": str(out), "assets": len(entries), "label": label}


def _bundle_rows(con, scope: str) -> tuple[list[dict], str]:
    cols = ("id, name, path, kind, theme, context, ext, family, style,"
            " weight, italic")
    acols = ("a.id AS id, a.name AS name, a.path AS path, a.kind AS kind,"
             " a.theme AS theme, a.context AS context, a.ext AS ext,"
             " a.family AS family, a.style AS style, a.weight AS weight,"
             " a.italic AS italic")   # joined branches: id is ambiguous
    if scope.startswith("collection:"):
        cid = int(scope.split(":", 1)[1])
        name = con.execute("SELECT name FROM collection WHERE id=?",
                           (cid,)).fetchone()
        rows = [dict(r) for r in con.execute(
            f"SELECT {acols} FROM asset a JOIN collection_ref cr"
            " ON cr.item_kind='icon' AND cr.item_id=a.id"
            " WHERE cr.collection_id=? ORDER BY a.id", (cid,))]
        return rows, (name[0] if name else f"collection-{cid}")
    if scope.startswith("project:"):
        pid = int(scope.split(":", 1)[1])
        name = con.execute("SELECT name FROM projects WHERE id=?",
                           (pid,)).fetchone()
        rows = [dict(r) for r in con.execute(
            f"SELECT {acols} FROM asset a JOIN project_asset pa"
            " ON pa.asset_id=a.id WHERE pa.project_id=? ORDER BY a.id",
            (pid,))]
        return rows, (name[0] if name else f"project-{pid}")
    rows = [dict(r) for r in con.execute(
        f"SELECT {cols} FROM asset ORDER BY id")]
    return rows, "library"


def read_bundle(zip_path: str | Path) -> dict:
    """Validate + parse a bundle (manifest only — files stream later)."""
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        if BUNDLE_MANIFEST not in names:
            raise ExportError("not a fengrid bundle (no manifest)")
        data = json.loads(zf.read(BUNDLE_MANIFEST).decode("utf-8"))
    if data.get("fengrid") != "bundle":
        raise ExportError("not a fengrid bundle")
    return data
