"""Incremental asset indexing — the Python port of the 0.x data plane.

Replaces: refresh-icons.sh + icon-meta.sh + the find/awk list generation.

Fingerprints are size+mtime (cheap stand-in for a content hash — same choice
as icon-meta.sh:5-11; upgrading to a real hash is a recorded quick-win).
A file whose fingerprint is unchanged is never re-identified. WAL mode makes
the single-transaction write crash-safe without the tmpfile dance the shell
scripts needed (icon-meta.sh:26-27).

Metadata gaps, intentional and matching 0.x behaviour:
- SVG: never rasterised at index time; dims from the XML root when parseable.
- .xpm: no Pillow path — indexed with null metadata (export falls back to
  ImageMagick when available; see core/export.py).
- Unreadable rasters: indexed with null metadata rather than dropped, so the
  user sees what exists (the grid shows a broken-image placeholder).
"""

from __future__ import annotations

import os
import sqlite3
import time
from collections import deque
from pathlib import Path
from typing import Any

from . import db as core_db
from . import kinds as core_kinds
from . import scanner

try:
    # hardened parser when available (entity-expansion hardening)
    from defusedxml import ElementTree as SafeET
    _HAVE_DEFUSEDXML = True
except ImportError:
    import xml.etree.ElementTree as SafeET  # type: ignore[no-redef]
    _HAVE_DEFUSEDXML = False

# SEC-4: without defusedxml the stdlib parser is vulnerable to entity
# expansion ("billion laughs") — a 4 MB SVG can expand to gigabytes of
# RAM. Fail secure: when the hardened parser is missing, SVGs carrying
# a DOCTYPE/entity declaration are not parsed at all (dimensions come
# back null; the row still indexes).
_SAFE_SVG_MAX_BYTES = 4 * 1024 * 1024


def _svg_parse_safe(path: str):
    """Parse an SVG only when the parser guarantees entity safety."""
    if os.path.getsize(path) > _SAFE_SVG_MAX_BYTES:
        return None
    if not _HAVE_DEFUSEDXML:
        try:
            with open(path, "rb") as fh:
                head = fh.read(4096).decode("utf-8", errors="ignore")
        except OSError:
            return None
        low = head.lower()
        if "<!doctype" in low or "<!entity" in low:
            return None
    try:
        return SafeET.parse(path).getroot()
    except Exception:                          # noqa: BLE001
        return None

try:
    from PIL import Image
except ImportError:  # pragma: no cover - Pillow is a build requirement
    Image = None

from . import fonts as fonts_mod
from . import scanner

_MAX_SVG_PARSE_BYTES = 4 * 1024 * 1024


class ScanAborted(Exception):
    """Raised via a should_stop() callback to end a scan early (app quit)."""


def fingerprint(path: str) -> str:
    st = os.stat(path)
    return f"{st.st_size}:{st.st_mtime_ns}"


def identify(path: str) -> dict[str, Any]:
    """Best-effort pixel metadata for one file (never raises)."""
    info: dict[str, Any] = dict(width=None, height=None,
                                bytes=os.path.getsize(path),
                                colorspace=None, color_count=None, mono=None)
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    from . import kinds as core_kinds

    if ext == "svg":
        # dims from the SVG root (width/height attrs, then viewBox)
        try:
            if info["bytes"] <= _MAX_SVG_PARSE_BYTES:
                root = _svg_parse_safe(path)
                if root is not None:
                    viewbox = root.get("viewBox", "")
                    w = h = None
                    for attr in ("width", "height"):
                        raw = (root.get(attr) or "").strip()
                        try:
                            val = float(raw.rstrip("px"))
                            if attr == "width":
                                w = val
                            else:
                                h = val
                        except (ValueError, TypeError):
                            pass
                    if (w is None or h is None) and len(viewbox.split()) == 4:
                        vb = viewbox.split()
                        w, h = float(vb[2]), float(vb[3])
                    if w is not None:
                        info["width"] = int(w)
                    if h is not None:
                        info["height"] = int(h)
        except Exception:
            pass
        return info

    # non-raster kinds (video/audio/doc/data/spatial/timeseries/markdown)
    # carry no pixel metadata — skip Pillow entirely
    if Image is None or ext == "xpm" or not core_kinds.is_raster(ext):
        return info

    try:
        with Image.open(path) as im:
            info["width"], info["height"] = im.size
            info["colorspace"] = im.mode
            if im.mode in ("1", "L", "LA"):
                info["mono"] = 1
            # SEC-3: a tiny file can claim a 100000x100000 header;
            # convert("RGB") would allocate ~30 GB BEFORE any cap
            # applied. Check the declared dimensions first and skip
            # colour counting entirely for absurd rasters.
            elif (im.width or 0) * (im.height or 0) > 256 * 1024 * 1024:
                info["mono"] = 0          # cannot verify: assume colour
            else:
                small = im.convert("RGB")
                if small.width * small.height > 4096 * 4096:
                    small = small.resize((256, 256))
                colors = small.getcolors(maxcolors=100000)
                if colors is None:
                    info["mono"] = 0  # >100k colors: definitely not mono
                else:
                    info["color_count"] = len(colors)
                    info["mono"] = 1 if len(colors) <= 2 else 0
    except Exception:
        pass  # unreadable file: keep the row with nulls
    return info


# commit cadence for scan()/scan_fonts() — bounds how long a concurrent
# main-thread writer (settings save on the first-run screen) can block
_CHUNK = 400
# Fonts identify each file with fontTools (~5-20ms) inside the chunk's
# write lock; 400 of those held the DB for multiple seconds and starved
# main-thread settings writes (first-run saves). 100 ≈ ≤1.5s holds.
_CHUNK_FONTS = 100

# scan() identification lookahead: files identified AHEAD of the write
# cursor by the bounded window (see scan) — deep enough to keep the
# write loop fed, shallow enough that per-file progress stays near-real
_IDENTIFY_WINDOW = 32
_IDENTIFY_WORKERS = 4


def _parallel_identify() -> bool:
    """FENGRID_SCAN_PARALLEL=0 forces the serial path (tests, debugging)."""
    return os.environ.get("FENGRID_SCAN_PARALLEL", "1") != "0"


def purge_assets(con: sqlite3.Connection,
                 rows: list[tuple[int, str, str]]) -> int:
    """Delete asset rows AND every derived row, by (id, kind, path).

    item_tag / item_field_value / collection_ref / asset_link reference
    items polymorphically with no FK cascade, so they must be deleted
    explicitly or tag counts and links go orphan-zombie. scan_state rows
    are keyed by path — leaving them makes a re-added folder scan as
    'unchanged' with no asset row (the file never comes back). FTS rows
    clean themselves through the asset AFTER DELETE trigger.
    """
    if not rows:
        return 0
    by_kind: dict[str, list[tuple[int, str]]] = {}
    for asset_id, kind, path in rows:
        by_kind.setdefault(kind, []).append((asset_id, path))
    for kind, items in by_kind.items():
        ids = [i for i, _ in items]
        paths = [p for _, p in items]
        marks = ",".join("?" * len(ids))
        con.execute(
            f"DELETE FROM item_tag WHERE item_kind = ? AND item_id IN"
            f" ({marks})", [kind, *ids])
        con.execute(
            f"DELETE FROM item_field_value WHERE item_kind = ? AND item_id"
            f" IN ({marks})", [kind, *ids])
        con.execute(
            f"DELETE FROM collection_ref WHERE item_kind = ? AND item_id IN"
            f" ({marks})", [kind, *ids])
        con.execute(
            f"DELETE FROM asset_link WHERE (from_kind = ? AND from_id IN"
            f" ({marks})) OR (to_kind = ? AND to_id IN ({marks}))",
            [kind, *ids, kind, *ids])
        con.execute(f"DELETE FROM asset WHERE id IN ({marks})", ids)
        con.executemany("DELETE FROM scan_state WHERE path = ?",
                        [(p,) for p in paths])
    return len(rows)


def _enabled_now(con: sqlite3.Connection,
                 sources: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Re-check enabled flags at scan start — a source the user disabled
    between ensure_sources() and the scan running must not be indexed."""
    out = []
    for source_id, root in sources:
        row = con.execute("SELECT enabled FROM source WHERE id = ?",
                          (source_id,)).fetchone()
        if row is not None and row[0]:
            out.append((source_id, root))
    return out


def _sweep_disabled(con: sqlite3.Connection, kinds: tuple[str, ...],
                    counts: dict) -> None:
    """Purge assets/fingerprints of DISABLED sources of the given kinds.

    Unchecking a path in Settings/first-run must make its assets leave
    the grid; re-checking then re-indexes from scratch (fingerprints
    are gone). Runs inside the scan transaction, so there is never a
    half-swept state visible to the UI.
    """
    disabled = con.execute(
        f"SELECT id FROM source WHERE enabled = 0 AND kind IN"
        f" ({','.join('?' * len(kinds))})", list(kinds)).fetchall()
    for (sid,) in disabled:
        rows = con.execute(
            "SELECT id, kind, path FROM asset WHERE source_id = ?",
            (sid,)).fetchall()
        counts["pruned"] += purge_assets(con, [tuple(r) for r in rows])


def _upsert_asset(con: sqlite3.Connection, source_id: int, path: str,
                  meta: dict, info: dict, now: float, fp: str,
                  kind: str = "icon") -> None:
    """Index one icon/media/data file, preserving its asset id when the
    path is already known.

    UPDATE (not DELETE+INSERT) for existing paths: the id must survive a
    re-identification — a git checkout or touch bumps mtimes, and a new
    id would orphan every item_tag / collection_ref / asset_link row the
    user attached to that asset. The FTS AFTER UPDATE trigger reindexes
    the search row. New rows get a generated GUID at first tracking.
    """
    args = (source_id, meta["name"], meta["theme"], meta["context"],
            meta["ext"], meta["size_px"], info["width"], info["height"],
            info["bytes"], info["colorspace"], info["color_count"],
            info["mono"], os.path.getmtime(path))
    row = con.execute("SELECT id FROM asset WHERE path = ?",
                      (path,)).fetchone()
    if row is not None:
        con.execute(
            "UPDATE asset SET source_id = ?, name = ?, theme = ?,"
            " context = ?, ext = ?, size_px = ?, width = ?, height = ?,"
            " bytes = ?, colorspace = ?, color_count = ?, mono = ?,"
            " mtime = ? WHERE id = ?",
            (*args, row[0]))
    else:
        con.execute(
            "INSERT INTO asset(source_id, kind, path, name, theme,"
            " context, ext, size_px, width, height, bytes,"
            " colorspace, color_count, mono, mtime, guid)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,"
            " ?, ?, ?, ?, ?)",
            (source_id, kind, path, *args[1:], core_db.new_guid()))
    con.execute(
        "INSERT INTO scan_state(path, fingerprint, last_seen)"
        " VALUES (?, ?, ?) ON CONFLICT(path) DO UPDATE SET"
        " fingerprint=excluded.fingerprint,"
        " last_seen=excluded.last_seen",
        (path, fp, now),
    )


def scan(con: sqlite3.Connection, sources: list[tuple[int, str]],
         progress=None) -> dict:
    """Incrementally index the given sources into the library.

    sources: [(source_id, root_path)] for ENABLED sources only.
    Returns a counts report. Writes commit in chunks (every _CHUNK files
    and per source) so concurrent main-thread writes — theme changes,
    folder toggles on the first-run screen — never wait behind one
    whole-scan transaction (WAL allows a single writer at a time; a
    multi-second transaction made sqlite3.OperationalError('database is
    locked') after the 5s busy timeout). Each chunk is internally
    consistent (asset + scan_state commit together), so a crash simply
    resumes at the last committed fingerprint.

    Disabled sources are swept first: their asset rows, taxonomy links
    and fingerprints are purged, so unchecking a path in Settings makes
    its assets leave the grid, and re-checking re-indexes from scratch.
    """
    counts = {"total": 0, "new": 0, "changed": 0, "unchanged": 0,
              "pruned": 0, "errors": 0}
    now = time.time()

    # BEGIN IMMEDIATE: a deferred BEGIN takes a WAL read snapshot on its
    # first SELECT, and an INSERT against a snapshot another writer has
    # since advanced fails INSTANTLY with "database is locked" — the
    # busy timeout never helps that class. Taking the write lock up
    # front makes waits polite instead. (This killed the initial icon
    # scan whenever the font scan committed a chunk first: `scanning`
    # stuck true, half-indexed library — user-reported as a freeze.)
    con.execute("BEGIN IMMEDIATE")
    try:
        _sweep_disabled(con, ("system", "folder"), counts)
        live = _enabled_now(con, sources)
        processed = 0
        for source_id, root in live:
            seen: set[str] = set()
            file_iter = scanner.iter_asset_files(root)
            # bounded-lookahead parallel identification: identification
            # (PIL probe / SVG parse) is pure filesystem work with no DB
            # access, so a small thread pool pipelines it ahead of the
            # serialized writes. The scan thread alone touches the
            # connection (sqlite objects are thread-affine).
            pool = None
            if _parallel_identify():
                from concurrent.futures import ThreadPoolExecutor
                pool = ThreadPoolExecutor(
                    max_workers=_IDENTIFY_WORKERS)
            window: deque = deque()
            try:
                def _stage(seen_set: set, src_root: str,
                           next_path: str, ident_pool) -> tuple:
                    # fingerprint + derive on the scan thread (the DB
                    # read rides this thread's own connection); the
                    # future is None for unchanged files — the writer
                    # must not pay identification for them. Loop
                    # variables are explicit parameters, not free
                    # bindings (ruff B023).
                    seen_set.add(next_path)
                    counts["total"] += 1
                    fp_n = fingerprint(next_path)
                    prev_n = con.execute(
                        "SELECT fingerprint FROM scan_state"
                        " WHERE path = ?", (next_path,),
                    ).fetchone()
                    if prev_n is not None and prev_n[0] == fp_n:
                        return (next_path, fp_n, prev_n, None, None,
                                None)
                    meta_n = scanner.derive_meta(next_path, src_root)
                    kind_n = (core_kinds.kind_for_ext(meta_n["ext"])
                              or "icon")
                    meta_n["kind"] = kind_n
                    fut = (ident_pool.submit(identify, next_path)
                           if ident_pool is not None else None)
                    return (next_path, fp_n, prev_n, meta_n, kind_n,
                            fut)

                for _ in range(_IDENTIFY_WINDOW):
                    try:
                        window.append(_stage(seen, root,
                                             next(file_iter), pool))
                    except StopIteration:
                        break
                while window:
                    path, fp, prev, meta, kind, fut = window.popleft()
                    if meta is None:
                        # staged unchanged — refresh last_seen only
                        con.execute(
                            "UPDATE scan_state SET last_seen = ?"
                            " WHERE path = ?", (now, path),
                        )
                        counts["unchanged"] += 1
                    else:
                        info = (fut.result() if fut is not None
                                else identify(path))
                        try:
                            _upsert_asset(con, source_id, path, meta,
                                          info, now, fp, kind=kind)
                        except sqlite3.IntegrityError:
                            # source removed mid-scan (FK on
                            # source_id) — skip this file; the next
                            # scan reconciles
                            counts["total"] -= 1
                            continue
                        counts["changed" if prev is not None
                                else "new"] += 1
                    processed += 1
                    if progress:
                        progress(counts["total"], path)
                    if processed % _CHUNK == 0:
                        con.commit()
                        con.execute("BEGIN IMMEDIATE")
                    try:
                        nxt = next(file_iter)
                    except StopIteration:
                        continue
                    window.append(_stage(seen, root, nxt, pool))
            finally:
                if pool is not None:
                    pool.shutdown(wait=False)

            # prune assets + fingerprints that vanished from this source
            # (kind-scoped: a source row is single-purpose, so font rows
            # are never touched — the font scan owns them)
            rows = con.execute(
                "SELECT id, path, kind FROM asset"
                " WHERE source_id = ? AND kind != 'font'",
                (source_id,),
            ).fetchall()
            vanished = [(r["id"], r["kind"], r["path"]) for r in rows
                        if r["path"] not in seen]
            counts["pruned"] += purge_assets(con, vanished)
            # PERF-2: fetch only THIS root's scan_state rows (LIKE is
            # index-assisted) instead of the whole table per source;
            # the straggler filter (not in `seen`) stays in Python so
            # freshly-scanned fingerprints are preserved.
            root_prefix = str(Path(root).resolve()) + os.sep
            st_rows = con.execute(
                "SELECT path FROM scan_state WHERE path LIKE ? ESCAPE '\\'",
                (_like_escape(root_prefix) + "%",)).fetchall()
            stragglers = [p for (p,) in st_rows if p not in seen]
            con.executemany("DELETE FROM scan_state WHERE path = ?",
                            [(p,) for p in stragglers])
            con.commit()
            con.execute("BEGIN IMMEDIATE")
        con.commit()
    except Exception:
        con.rollback()
        raise
    return counts


def scan_fonts(con: sqlite3.Connection, sources: list[tuple[int, str]],
               progress=None, should_stop=None,
               files_by_root: dict[str, list[str]] | None = None) -> dict:
    """Incrementally index font sources (kind='font' rows).

    Same fingerprint/incremental scheme as scan(); one row per FILE with the
    first face's metadata (core/fonts.identify_font documents the .ttc
    scope note). should_stop() is checked per file so an app quit ends the
    scan cleanly instead of leaving a QThread running (qa-gate tripwire).

    PERF-1: `files_by_root` lets the caller share ONE directory walk with
    the pre-count (the old code walked every root twice per launch), and
    fontTools identification of changed/new files runs in a small thread
    pool (identification is pure CPU; the DB writes stay serialized on
    the scanning thread).
    """
    counts = {"total": 0, "new": 0, "changed": 0, "unchanged": 0,
              "pruned": 0, "errors": 0}
    now = time.time()

    con.execute("BEGIN IMMEDIATE")
    try:
        _sweep_disabled(con, ("fontroot",), counts)
        live = _enabled_now(con, sources)
        processed = 0
        for source_id, root in live:
            seen: set[str] = set()
            file_list = ((files_by_root or {}).get(root)
                         if files_by_root is not None else None)
            paths = file_list if file_list is not None else \
                fonts_mod.iter_font_files(root)
            # pass 1 — fingerprint check; collect files that need
            # fontTools identification
            pending: list[tuple[str, str | None, str]] = []  # path, fp, prev
            for path in paths:
                if should_stop is not None and should_stop():
                    raise ScanAborted
                seen.add(path)
                counts["total"] += 1
                fp = fingerprint(path)
                prev_row = con.execute(
                    "SELECT fingerprint FROM scan_state WHERE path = ?",
                    (path,),
                ).fetchone()
                prev = prev_row[0] if prev_row is not None else None
                if prev is not None and prev == fp:
                    con.execute(
                        "UPDATE scan_state SET last_seen = ? WHERE path = ?",
                        (now, path),
                    )
                    counts["unchanged"] += 1
                else:
                    pending.append((path, fp, prev))
            # pass 2 — identify in parallel (I/O + CPU bound fontTools
            # parsing), then write serialized
            metas: dict[str, dict | None] = {}
            if len(pending) > 8:
                from concurrent.futures import ThreadPoolExecutor
                with ThreadPoolExecutor(max_workers=4) as pool:
                    for path, meta in zip(
                            [p for p, _f, _pr in pending],
                            pool.map(fonts_mod.identify_font,
                                     [p for p, _f, _pr in pending])):
                        metas[path] = meta
            else:
                for path, _fp, _prev in pending:
                    metas[path] = fonts_mod.identify_font(path)
            for path, fp, prev in pending:
                if should_stop is not None and should_stop():
                    raise ScanAborted
                meta = metas[path]
                rel = os.path.relpath(path, root)
                parts = rel.split(os.sep)
                theme = (parts[0] if len(parts) > 1
                         else os.path.basename(root))
                name = os.path.splitext(os.path.basename(path))[0]
                ext = os.path.splitext(path)[1].lower().lstrip(".")
                try:
                    _upsert_font(con, source_id, path, name, theme, ext,
                                 meta, now, fp)
                except sqlite3.IntegrityError:
                    counts["total"] -= 1  # source removed mid-scan
                    continue
                counts["changed" if prev is not None else "new"] += 1
                processed += 1
                if progress:
                    progress(counts["total"], path)
                if processed % _CHUNK_FONTS == 0:
                    con.commit()
                    con.execute("BEGIN IMMEDIATE")

            # prune font rows that vanished from this source
            rows = con.execute(
                "SELECT id, path FROM asset WHERE source_id = ?"
                " AND kind = 'font'",
                (source_id,),
            ).fetchall()
            vanished = [(r["id"], "font", r["path"]) for r in rows
                        if r["path"] not in seen]
            counts["pruned"] += purge_assets(con, vanished)
            con.commit()
            con.execute("BEGIN IMMEDIATE")
        con.commit()
    except ScanAborted:
        con.rollback()
        counts["aborted"] = True
        return counts
    except Exception:
        con.rollback()
        raise
    return counts


def _upsert_font(con: sqlite3.Connection, source_id: int, path: str,
                 name: str, theme: str, ext: str, meta, now: float,
                 fp: str) -> None:
    """Font twin of _upsert_asset: id-preserving UPDATE for known paths
    (taxonomy rows survive re-identification), INSERT for new ones."""
    args = (source_id, name, theme, ext, os.path.getsize(path),
            meta["family"] if meta else None,
            meta["style"] if meta else None,
            meta["weight"] if meta else None,
            meta["italic"] if meta else None,
            os.path.getmtime(path))
    row = con.execute("SELECT id FROM asset WHERE path = ?",
                      (path,)).fetchone()
    if row is not None:
        con.execute(
            "UPDATE asset SET source_id = ?, name = ?, theme = ?, ext = ?,"
            " bytes = ?, family = ?, style = ?, weight = ?, italic = ?,"
            " mtime = ? WHERE id = ?",
            (*args, row[0]))
    else:
        con.execute(
            "INSERT INTO asset(source_id, kind, path, name, theme,"
            " ext, bytes, family, style, weight, italic, mtime, guid)"
            " VALUES (?, 'font', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (source_id, path, *args[1:], core_db.new_guid()))
    con.execute(
        "INSERT INTO scan_state(path, fingerprint, last_seen)"
        " VALUES (?, ?, ?) ON CONFLICT(path) DO UPDATE SET"
        " fingerprint=excluded.fingerprint,"
        " last_seen=excluded.last_seen",
        (path, fp, now),
    )


def ensure_sources(con: sqlite3.Connection, roots: list[Path],
                   kinds: tuple[str, ...] = ("system",)) -> list[tuple[int, str]]:
    """Insert missing source rows, disable stale ones, return enabled set.

    kinds scopes which source rows this scan owns: icon scans pass
    ("system", "folder"), font scans pass ("fontroot",). Sources previously
    added by the user (kind='folder') are always kept even when their root
    no longer exists — pruning then removes the missing files on the next
    scan, which mirrors the 0.x --merge-list flow.

    An EXISTING row keeps the user's enabled flag: a source disabled from
    Settings/first-run stays disabled even though its path still exists
    (the previous logic force-re-enabled every detected root on each scan).
    New rows are inserted enabled.
    """
    known = {r["path"]: r for r in
             con.execute("SELECT id, path, kind, enabled FROM source")}
    root_strs = {str(Path(r).resolve()): r for r in roots}
    for path_str in root_strs:
        if path_str not in known:
            label = Path(path_str).name or path_str
            cur = con.execute(
                "INSERT INTO source(kind, path, label, enabled)"
                " VALUES (?, ?, ?, 1)",
                (kinds[0], path_str, label),
            )
            known[path_str] = {"id": cur.lastrowid, "path": path_str,
                               "kind": kinds[0], "enabled": 1}
    enabled: list[tuple[int, str]] = []
    for path_str, row in known.items():
        if row["kind"] not in kinds:
            continue
        exists = os.path.isdir(path_str)
        # the user's flag is authoritative for every existing row (system
        # roots included) — a source disabled from Settings/first-run must
        # stay disabled even though its path still exists; new rows are
        # inserted enabled, so detection behaves as before. Missing roots
        # are simply not returned (the exists check below) but keep their
        # flag, so a re-plugged path resumes scanning.
        if row["enabled"] and exists:
            enabled.append((row["id"], path_str))
    con.commit()
    return enabled


def add_folder_source(con: sqlite3.Connection, folder: str,
                      kind: str = "folder") -> int:
    """Register a user folder as a scan source ('folder' = icon assets,
    'fontroot' = font files). Re-adding a disabled path re-enables it."""
    assert kind in ("folder", "fontroot"), kind
    folder = str(Path(folder).resolve())
    row = con.execute("SELECT id FROM source WHERE path = ?",
                      (folder,)).fetchone()
    if row:
        con.execute("UPDATE source SET enabled = 1 WHERE id = ?",
                    (row[0],))
        con.commit()
        return row[0]
    cur = con.execute(
        "INSERT INTO source(kind, path, label, enabled) VALUES (?, ?, ?, 1)",
        (kind, folder, Path(folder).name or folder),
    )
    con.commit()
    return cur.lastrowid


def set_source_enabled(con: sqlite3.Connection, source_id: int,
                       enabled: bool) -> bool:
    """Toggle a source row. Disabling takes effect at the next scan:
    _sweep_disabled purges that source's assets + fingerprints inside
    the scan transaction, so the grid drops its files and re-enabling
    re-indexes from scratch. Callers trigger a scan right after."""
    cur = con.execute("UPDATE source SET enabled = ? WHERE id = ?",
                      (1 if enabled else 0, source_id))
    con.commit()
    return cur.rowcount > 0


def set_path_enabled(con: sqlite3.Connection, path: str, kind: str,
                     enabled: bool) -> None:
    """Upsert the enabled flag for a DETECTED path.

    The first-run screen toggles system roots before any scan has
    registered them, so the row may not exist yet: enabled=True with no
    row is a no-op (registration defaults to on), enabled=False inserts
    a disabled row so the first scan's ensure_sources() skips it. A
    known path keeps its existing kind; `kind` is only used on insert
    ('system' icon roots, 'fontroot' font dirs, 'folder' user folders).
    """
    assert kind in ("system", "folder", "fontroot"), kind
    path = str(Path(path).resolve())
    row = con.execute("SELECT id FROM source WHERE path = ?",
                      (path,)).fetchone()
    if row:
        con.execute("UPDATE source SET enabled = ? WHERE id = ?",
                    (1 if enabled else 0, row[0]))
    elif not enabled:
        con.execute(
            "INSERT INTO source(kind, path, label, enabled)"
            " VALUES (?, ?, ?, 0)",
            (kind, path, Path(path).name or path))
    con.commit()


def _like_escape(path: str) -> str:
    return path.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def remove_source(con: sqlite3.Connection, source_id: int) -> bool:
    """Delete a source and EVERYTHING derived from its assets.

    purge_assets() handles taxonomy rows (polymorphic, no FK cascade),
    FTS (via the asset AFTER DELETE trigger) and scan_state rows —
    without the last, a re-added folder would scan as 'unchanged' with
    no asset rows and its files would never reappear.
    """
    src = con.execute("SELECT path FROM source WHERE id = ?",
                      (source_id,)).fetchone()
    if src is None:
        return False
    root = src["path"]
    rows = con.execute(
        "SELECT id, kind, path FROM asset WHERE source_id = ?",
        (source_id,)).fetchall()
    purge_assets(con, [tuple(r) for r in rows])
    # scan_state stragglers under the root (escaped LIKE — paths may
    # contain % or _)
    con.execute(
        "DELETE FROM scan_state WHERE path = ? OR path LIKE ? ESCAPE '\\'",
        (root, _like_escape(root) + "/%"))
    con.execute("DELETE FROM source WHERE id = ?", (source_id,))
    con.commit()
    return True


def sources_summary(con: sqlite3.Connection) -> list[dict]:
    # #61: the LEFT JOIN … GROUP BY form made SQLite visit the whole
    # asset table PER SOURCE (no source_id index until the migration);
    # on the main thread mid-scan that froze first-run setup for minutes.
    # One indexed aggregate + a merge is O(assets) once, index-only.
    counts = {r[0]: r[1] for r in con.execute(
        "SELECT source_id, COUNT(*) FROM asset GROUP BY source_id")}
    rows = con.execute(
        "SELECT id, kind, path, label, enabled"
        " FROM source ORDER BY kind, label"
    ).fetchall()
    return [{**dict(r), "n": counts.get(r["id"], 0)} for r in rows]
