"""Native export pipeline — the Qt-side replacement for serve.py /convert.

Parity notes (vs the 0.x endpoint, serve.py:169-220):
- Same format set: png, jpeg, webp, ico, pdf, gif, tiff, bmp.
- Same size clamp: 8..1024, plus "orig".
- ImageMagick is invoked via argv there; here Pillow does the conversion
  natively, so export works without the LAN server.
- SVG sources must be rasterised upstream (the Qt bridge renders via
  QSvgRenderer to a temp PNG first); this module raises on raw SVG input.
- .xpm has no Pillow path — raise ExportError; the bridge falls back to
  ImageMagick via argv when `magick`/`convert` exists (improvement note #4
  in docs/review/2026-current-state-review.md).
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from PIL import Image

FORMATS = {
    "png": "PNG", "jpeg": "JPEG", "jpg": "JPEG", "webp": "WEBP",
    "bmp": "BMP", "gif": "GIF", "tiff": "TIFF", "pdf": "PDF", "ico": "ICO",
}


class ExportError(Exception):
    pass


def export(src: str | Path, dest_dir: str | Path, stem: str, fmt: str,
           size: int | str | None = None) -> Path:
    """Convert src to fmt at size (or original), writing next to dest_dir.

    Returns the output path. Atomic per-file: writes a temp then replaces.
    """
    fmt = fmt.lower()
    if fmt == "jpg":
        fmt = "jpeg"
    if fmt not in FORMATS:
        raise ExportError(f"unsupported format: {fmt}")
    if size not in (None, "orig") and not (8 <= int(size) <= 1024):
        raise ExportError("size must be 8..1024 (or 'orig')")

    ext = os.path.splitext(str(src))[1].lower()
    if ext == ".svg":
        raise ExportError("SVG must be rendered before export (bridge handles it)")
    if ext == ".xpm":
        magick = shutil.which("magick") or shutil.which("convert")
        if magick:
            return _export_xpm(src, dest_dir, stem, fmt, size, magick)
        raise ExportError(".xpm export needs ImageMagick (not installed)")

    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", stem)[:80] or "icon"
    out = dest_dir / f"{safe}.{fmt}"

    with Image.open(src) as im:
        if size not in (None, "orig"):
            im = im.resize((int(size), int(size)), Image.Resampling.LANCZOS)
        im = _convert_for(fmt, im)
        tmp = out.with_suffix(out.suffix + ".tmp")
        if fmt == "ico":
            side = max(im.size)
            sizes = [(s, s) for s in (256, 128, 64, 48, 32, 16) if s <= side]
            im.save(tmp, format="ICO", sizes=sizes or [(16, 16)])
        else:
            im.save(tmp, format=FORMATS[fmt])
        os.replace(tmp, out)
    return out


def _convert_for(fmt: str, im: Image.Image) -> Image.Image:
    if fmt in ("jpeg", "pdf", "bmp"):
        return im.convert("RGB")
    if fmt == "gif":
        return im.convert("P", palette=Image.Palette.ADAPTIVE, colors=256)
    return im


def _export_xpm(src, dest_dir, stem, fmt, size, magick) -> Path:
    """ImageMagick fallback for .xpm (argv only — never through a shell,
    matching the 0.x /convert security posture, serve.py:176-178)."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", stem)[:80] or "icon"
    tmp_png = dest_dir / f".{safe}.xpm-conv.png"
    import subprocess
    subprocess.run([magick, str(src), str(tmp_png)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        return export(tmp_png, dest_dir, stem, fmt, size)
    finally:
        tmp_png.unlink(missing_ok=True)
