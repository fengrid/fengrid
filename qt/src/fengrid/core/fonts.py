"""Font discovery, metadata, and export (the Python port of scan-fonts.sh).

fontTools reads the name/OS-2 tables directly — no fc-scan dependency and no
shell (the 0.x fc-scan pipeline needed a trailing \\n in --format or .ttc
files corrupted font-meta.js; fontTools has no such trap).

v1 scope note (recorded): .ttc/.otc collections are indexed once per FILE
with the first face's metadata. Per-face rows would need a face-index column
and a path-uniqueness scheme; revisit if CJK collections matter to a user.

Export ports the 0.x /fonts-export semantics: @font-face CSS (weights from
the OS/2 table, not hardcoded 400) plus a zip of the family's files with a
README — paths must stay under the scanned font roots (no traversal: the
query starts from rows already in the index).
"""

from __future__ import annotations

import glob
import os
import re
import sqlite3
import sys
import zipfile
from pathlib import Path

try:
    from fontTools.ttLib import TTFont
except ImportError:  # pragma: no cover - fontTools is a build requirement
    TTFont = None

_BROTLI: bool | None = None


def brotli_available() -> bool:
    """Cached probe of fontTools' WOFF2 decoder dependency (issue #63).

    fontTools logs an ERROR per WOFF2 file when brotli is missing; callers
    probe once and skip those files quietly instead.
    """
    global _BROTLI
    if _BROTLI is None:
        try:
            from fontTools.ttLib import woff2 as _woff2
            _BROTLI = bool(getattr(_woff2, "haveBrotli", False))
        except Exception:
            _BROTLI = False
    return _BROTLI

FONT_EXTS = {"ttf", "otf", "ttc", "otc", "woff", "woff2"}
_TTC_EXTS = {"ttc", "otc"}
_MAX_FACES = 32


def platform_font_dirs() -> list[Path]:
    """Existing font-source candidate roots (port of scan-fonts.sh defaults)."""
    home = Path.home()
    candidates = [
        "/usr/share/fonts",
        "/usr/local/share/fonts",
        home / ".local/share/fonts",
        home / ".fonts",
        "/usr/share/ttf",
    ]
    if sys.platform == "darwin":
        candidates += ["/Library/Fonts", str(home / "Library/Fonts"),
                       "/System/Library/Fonts"]
    elif sys.platform == "win32":
        windir = os.environ.get("WINDIR", r"C:\Windows")
        candidates += [os.path.join(windir, "Fonts"),
                       os.path.join(os.environ.get("LOCALAPPDATA", ""),
                                    "Microsoft", "Windows", "Fonts")]
    found = []
    for c in candidates:
        if c and Path(c).is_dir():
            found.append(Path(c))
    return found


def iter_font_files(root: str | Path):
    """Yield font files under root (hidden dirs skipped, dangling links dropped)."""
    root = str(root)
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fn in filenames:
            ext = fn.rsplit(".", 1)[-1].lower() if "." in fn else ""
            if ext not in FONT_EXTS:
                continue
            p = os.path.join(dirpath, fn)
            if os.path.isfile(p):
                yield p


def identify_font(path: str | Path) -> dict | None:
    """Best-effort metadata for the first face in a font file (never raises).

    Returns {family, style, weight, italic, faces} or None when the file is
    unreadable or fontTools is unavailable.
    """
    if TTFont is None:
        return None
    ext = os.path.splitext(str(path))[1].lower().lstrip(".")
    if ext == "woff2" and not brotli_available():
        # Issue #63: fontTools logs an ERROR per WOFF2 file when brotli is
        # missing — skip quietly (the row keeps filename + size; scan_fonts
        # counts the skips and notes it once per scan).
        return None
    try:
        if ext in _TTC_EXTS:
            face_count = 0
            for i in range(_MAX_FACES):
                try:
                    TTFont(str(path), fontNumber=i, lazy=True).close()
                except Exception:
                    break
                face_count = i + 1
            if face_count == 0:
                face_count = 1
            face = TTFont(str(path), fontNumber=0, lazy=True)
        else:
            face_count = 1
            face = TTFont(str(path), lazy=True)
        with face:
            name = face["name"]
            # ID 16/17 (typographic family/subfamily) beat ID 1/2 when present
            family = name.getDebugName(16) or name.getDebugName(1)
            style = name.getDebugName(17) or name.getDebugName(2) or "Regular"
            weight = None
            os2 = face.get("OS/2")
            if os2 is not None:
                weight = int(getattr(os2, "usWeightClass", 400) or 400)
            head = face.get("head")
            italic = 0
            if head is not None:
                italic = 1 if (getattr(head, "macStyle", 0) or 0) & 0x2 else 0
            if family is None:  # degenerate name table — fall back to stem
                family = os.path.splitext(os.path.basename(str(path)))[0]
        return dict(family=family.strip() or "Unknown", style=style,
                    weight=weight, italic=italic, faces=face_count)
    except Exception:
        return None


# --------------------------------------------------------------------- export

_CSS_SAFE = re.compile(r"[^A-Za-z0-9 ._-]")
_FORMAT_FOR_EXT = {"ttf": "truetype", "otf": "opentype", "ttc": "truetype-collection",
                   "otc": "opentype-collection", "woff": "woff", "woff2": "woff2"}


def family_files(con: sqlite3.Connection, family: str) -> list[dict]:
    """Indexed files of one family (paths already inside the scan index)."""
    rows = con.execute(
        "SELECT path, family, style, weight, italic, bytes, ext FROM asset"
        " WHERE kind = 'font' AND family = ? ORDER BY weight, style",
        (family,),
    ).fetchall()
    return [dict(r) for r in rows]


def families(con: sqlite3.Connection) -> list[dict]:
    rows = con.execute(
        "SELECT family, COUNT(*) AS n FROM asset WHERE kind = 'font'"
        " AND family IS NOT NULL GROUP BY family ORDER BY family COLLATE NOCASE"
    ).fetchall()
    return [dict(r) for r in rows]


def _css_block(path: Path, meta: dict) -> str:
    fmt = _FORMAT_FOR_EXT.get(meta["ext"], "truetype")
    url = path.as_uri()
    weight = meta["weight"] if meta["weight"] else 400
    style = "italic" if meta["italic"] else "normal"
    fam = meta["family"].replace('"', r"\"")
    return (f"@font-face {{\n  font-family: \"{fam}\";\n  src: url(\"{url}\")"
            f" format(\"{fmt}\");\n  font-weight: {weight};\n"
            f"  font-style: {style};\n}}")


def export_family_css(con: sqlite3.Connection, family: str,
                      dest_dir: str | Path) -> Path:
    """Write fonts.css with one @font-face per file of the family.

    Returns the css path. Raises ValueError when the family is unknown.
    """
    files = family_files(con, family)
    if not files:
        raise ValueError(f"unknown font family: {family}")
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    stem = _CSS_SAFE.sub("_", family).strip() or "fonts"
    out = dest_dir / f"{stem}.css"
    body = [f"/* fengrid — @font-face rules for {family} */"]
    for meta in files:
        body.append(_css_block(Path(meta["path"]), meta))
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text("\n\n".join(body) + "\n", encoding="utf-8")
    os.replace(tmp, out)
    return out


def export_family_zip(con: sqlite3.Connection, family: str,
                      dest_dir: str | Path) -> Path:
    """Zip the family's font files + generated CSS + README (0.x /fonts-export).

    Atomic per-file: temp file then replace, same as core.export.export.
    """
    files = family_files(con, family)
    if not files:
        raise ValueError(f"unknown font family: {family}")
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    stem = _CSS_SAFE.sub("_", family).strip() or "fonts"
    out = dest_dir / f"{stem}-fonts.zip"
    css = export_family_css(con, family, dest_dir)
    tmp = out.with_suffix(out.suffix + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        for meta in files:
            p = Path(meta["path"])
            if p.is_file():
                zf.write(p, f"fonts/{p.name}")
        zf.write(css, "css/fonts.css")
        zf.writestr("README.txt",
                    f"{family}\n\n"
                    "Font files exported from the Fengrid library.\n"
                    "css/fonts.css carries @font-face rules generated from\n"
                    "each file's OS/2 weight and head.macStyle italic bit.\n"
                    "Respect each font's own license when redistributing.\n")
    os.replace(tmp, out)
    return out
