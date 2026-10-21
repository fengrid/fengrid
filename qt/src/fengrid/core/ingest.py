"""Import / ingest pipeline — materialise files, then let the indexer
do what it already does best (fingerprint, upsert, FTS, chunked commits).

Design rules for large batches:
  - NEVER read an archive or file whole: ZipExtFile and files are
    copied through a 64KB buffer; a 2GB zip imports at constant memory.
  - One file is processed at a time; the DB write path is the existing
    indexer.scan (chunked `_CHUNK` commits — no giant transactions).
  - Conversion opens ONE image at a time (Pillow lazy-loads per file).

Modes:
  copy   -> file lands in <data_dir>/imported/<slug>/ (self-contained)
  link   -> a symlink in <data_dir>/links/<slug>/ points at the original
            (needs read permission on the target + symlink support; the
            importer REPORTS per-file permission failures and keeps going)
"""
from __future__ import annotations

import os
import shutil
import zipfile
from pathlib import Path

from . import indexer, patterns

_COPY_BUFSZ = 64 * 1024

ICON_EXTS = {"png", "svg", "bmp", "ico", "webp", "gif", "jpg", "jpeg",
             "tiff", "xpm"}
FONT_EXTS = {"ttf", "otf", "ttc", "otc", "pfb", "woff", "woff2"}
OTHER_EXTS = {"json", "md", "txt", "css", "html", "js", "scss", "svg"}  # snippets etc


class IngestError(Exception):
    pass


def kind_for(name: str) -> str | None:
    ext = Path(name).suffix.lstrip(".").lower()
    if ext in ICON_EXTS:
        return "icon"
    if ext in FONT_EXTS:
        return "font"
    return None


def _target_dir(data_dir: str, mode: str, slug: str) -> Path:
    base = Path(data_dir) / ("links" if mode == "link" else "imported") / slug
    base.mkdir(parents=True, exist_ok=True)
    return base


def _place(src: Path | str, dest: Path, mode: str) -> None:
    """Copy or link ONE file into dest (atomic: tmp then replace)."""
    src = Path(src)
    if mode == "link":
        if not os.access(src, os.R_OK):
            raise PermissionError(f"cannot read {src}")
        if dest.exists() or dest.is_symlink():
            dest.unlink()
        dest.symlink_to(src.resolve())
        return
    tmp = dest.with_name(dest.name + ".part")
    with open(src, "rb") as fi, open(tmp, "wb") as fo:
        shutil.copyfileobj(fi, fo, _COPY_BUFSZ)
    os.replace(tmp, dest)


def import_files(paths: list, data_dir: str, *,
                 mode: str = "copy",
                 convert: str = "none",
                 template: str = "",
                 prefix: str = "",
                 suffix: str = "",
                 find: str = "",
                 repl: str = "",
                 style: str = "none",
                 enum_start: int = 1,
                 enum_pad: int = 2,
                 random_len: int = 6,
                 csv_names: list[str] | None = None,
                 slug: str = "import",
                 progress=None,
                 should_stop=None) -> dict:
    """Materialise individual files. Returns {placed, skipped, failed,
    errors[:20], dest}. Runs on a worker thread (no Qt here)."""
    dest = _target_dir(data_dir, mode, slug)
    report = {"placed": 0, "skipped": 0, "failed": 0, "errors": [],
              "dest": str(dest)}
    for i, raw in enumerate(paths):
        if should_stop is not None and should_stop():
            report["errors"].append("cancelled")
            break
        src = Path(str(raw))
        try:
            if not src.is_file():
                report["skipped"] += 1
                continue
            if kind_for(src.name) is None:
                report["skipped"] += 1
                continue
            name = patterns.build_name(
                src.name, template=template, prefix=prefix, suffix=suffix,
                find=find, repl=repl, style=style, enum_index=i,
                enum_start=enum_start, enum_pad=enum_pad,
                random_len=random_len,
                csv_name=(csv_names[i] if csv_names and i < len(csv_names)
                          else ""))
            name = patterns.uniquify(dest, name)
            final = dest / name
            if convert not in ("", "none", "keep") and kind_for(name) == "icon":
                # conversion produces its own stem/extension
                final = _convert_in_place(src, dest, name, convert)
            else:
                _place(src, final, mode)
            report["placed"] += 1
        except PermissionError as e:
            report["failed"] += 1
            if len(report["errors"]) < 20:
                report["errors"].append(str(e))
        except Exception as e:      # keep importing — one bad file ≠ abort
            report["failed"] += 1
            if len(report["errors"]) < 20:
                report["errors"].append(f"{src.name}: {e}")
        if progress is not None:
            progress(i + 1, len(paths))
    return report


def _convert_in_place(src: Path, dest_dir: Path, name: str,
                      fmt: str) -> Path:
    from . import export as core_export
    from .exportplus import render_svg

    placed = dest_dir / name
    work = src
    tmp_png = None
    if src.suffix.lower() == ".svg":
        tmp_png = dest_dir / ("." + placed.stem + ".raster.png")
        render_svg(src, tmp_png, 512)
        work = tmp_png
    try:
        out = core_export.export(work, dest_dir, placed.stem, fmt, None)
        if out.name != placed.name:
            # export() derived its own extension — normalise
            target = dest_dir / f"{placed.stem}.{fmt}"
            if out != target:
                os.replace(out, target)
            out = target
        return out
    finally:
        if tmp_png is not None:
            Path(tmp_png).unlink(missing_ok=True)


def import_zip(zip_path: str, data_dir: str, *, mode: str = "copy",
               convert: str = "none", slug: str = "zip-import",
               template: str = "", prefix: str = "", suffix: str = "",
               find: str = "", repl: str = "", style: str = "none",
               enum_start: int = 1, enum_pad: int = 2, random_len: int = 6,
               csv_names: list[str] | None = None,
               max_members: int = 100000,
               progress=None, should_stop=None) -> dict:
    """Stream a ZIP: members are processed one at a time through a
    64KB buffer — constant memory regardless of archive size. Zip-slip
    is impossible (member names are flattened to their basename)."""
    dest = _target_dir(data_dir, mode, slug)
    report = {"placed": 0, "skipped": 0, "failed": 0, "errors": [],
              "dest": str(dest)}
    with zipfile.ZipFile(zip_path) as zf:
        infos = [zi for zi in zf.infolist()
                 if not zi.is_dir()][:max_members]
        staged = dest / ("._stage-%d" % os.getpid())
        staged.mkdir(exist_ok=True)
        try:
            for i, zi in enumerate(infos):
                if should_stop is not None and should_stop():
                    report["errors"].append("cancelled")
                    break
                name = zi.filename.replace("\\", "/").rsplit("/", 1)[-1]
                if not name or kind_for(name) is None:
                    report["skipped"] += 1
                    continue
                tmp = None
                try:
                    # stream member → temp (constant memory), then treat
                    # exactly like a plain file
                    tmp = staged / f"m{i}{Path(name).suffix.lower()}"
                    with zf.open(zi) as fi, open(tmp, "wb") as fo:
                        shutil.copyfileobj(fi, fo, _COPY_BUFSZ)
                    new_name = patterns.build_name(
                        name, template=template, prefix=prefix,
                        suffix=suffix, find=find, repl=repl, style=style,
                        enum_index=i, enum_start=enum_start,
                        enum_pad=enum_pad, random_len=random_len,
                        csv_name=(csv_names[i] if csv_names
                                  and i < len(csv_names) else ""))
                    new_name = patterns.uniquify(dest, new_name)
                    final = dest / new_name
                    if convert not in ("", "none", "keep") \
                            and kind_for(new_name) == "icon":
                        _convert_in_place(tmp, dest, new_name, convert)
                    else:
                        _place(tmp, final, "copy" if mode == "copy"
                               else "copy")  # staging is already local;
                        # for link mode we link the ORIGINAL zip member's
                        # extraction — a symlink to a temp makes no sense,
                        # so zip imports always copy (documented)
                    report["placed"] += 1
                except Exception as e:
                    report["failed"] += 1
                    if len(report["errors"]) < 20:
                        report["errors"].append(f"{name}: {e}")
                finally:
                    if tmp is not None:
                        Path(tmp).unlink(missing_ok=True)
                if progress is not None:
                    progress(i + 1, len(infos))
        finally:
            shutil.rmtree(staged, ignore_errors=True)
    return report


def import_folder(folder: str, mode: str = "link") -> dict:
    """Folders are SOURCES, not copies — record for the caller to
    register; returns the descriptor (kind sniffed from contents)."""
    p = Path(folder)
    if not p.is_dir():
        raise IngestError(f"not a folder: {folder}")
    if not os.access(p, os.R_OK | os.X_OK):
        raise PermissionError(f"cannot read folder {folder}")
    kinds = {"icon": False, "font": False}
    checked = 0
    for child in p.rglob("*"):
        if child.is_file():
            k = kind_for(child.name)
            if k:
                kinds[k] = True
            checked += 1
            if checked > 20000:      # sniff budget — don't walk terabytes
                break
    kind = "fontroot" if kinds["font"] and not kinds["icon"] else "folder"
    return {"path": str(p), "kind": kind,
            "note": f"{kinds['icon'] and 'icons ' or ''}"
                    f"{kinds['font'] and 'fonts' or ''}".strip()}


def scan_into(con, sources, progress=None) -> dict:
    """Index whatever we just materialised via the normal incremental
    scanner (chunked commits, id-preserving upserts, FTS sync). The icon
    scanner takes no cancel hook — only scan_fonts does."""
    return indexer.scan(con, sources, progress=progress)


def scan_fonts_into(con, sources, progress=None, should_stop=None) -> dict:
    return indexer.scan_fonts(con, sources, progress=progress,
                              should_stop=should_stop)
