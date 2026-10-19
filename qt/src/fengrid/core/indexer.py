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
from pathlib import Path
from typing import Any

try:
    # hardened parser when available (entity-expansion hardening); the files
    # parsed here are user-indexed local SVGs, so the stdlib fallback is
    # acceptable but not preferred
    from defusedxml import ElementTree as SafeET
except ImportError:
    import xml.etree.ElementTree as SafeET  # type: ignore[no-redef]

try:
    from PIL import Image
except ImportError:  # pragma: no cover - Pillow is a build requirement
    Image = None

from . import scanner

_MAX_SVG_PARSE_BYTES = 4 * 1024 * 1024


def fingerprint(path: str) -> str:
    st = os.stat(path)
    return f"{st.st_size}:{st.st_mtime_ns}"


def identify(path: str) -> dict[str, Any]:
    """Best-effort pixel metadata for one file (never raises)."""
    info: dict[str, Any] = dict(width=None, height=None,
                                bytes=os.path.getsize(path),
                                colorspace=None, color_count=None, mono=None)
    ext = os.path.splitext(path)[1].lower()

    if ext == ".svg":
        # dims from the SVG root (width/height attrs, then viewBox)
        try:
            if info["bytes"] <= _MAX_SVG_PARSE_BYTES:
                root = SafeET.parse(path).getroot()
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

    if Image is None or ext == ".xpm":
        return info

    try:
        with Image.open(path) as im:
            info["width"], info["height"] = im.size
            info["colorspace"] = im.mode
            if im.mode in ("1", "L", "LA"):
                info["mono"] = 1
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


def scan(con: sqlite3.Connection, sources: list[tuple[int, str]],
         progress=None) -> dict:
    """Incrementally index the given sources into the library.

    sources: [(source_id, root_path)] for ENABLED sources only.
    Returns a counts report; all writes happen in one transaction (WAL).
    """
    counts = {"total": 0, "new": 0, "changed": 0, "unchanged": 0,
              "pruned": 0, "errors": 0}
    now = time.time()

    con.execute("BEGIN")
    try:
        for source_id, root in sources:
            seen: set[str] = set()
            for path in scanner.iter_icon_files(root):
                seen.add(path)
                counts["total"] += 1
                fp = fingerprint(path)
                prev = con.execute(
                    "SELECT fingerprint FROM scan_state WHERE path = ?",
                    (path,),
                ).fetchone()
                if prev is not None and prev[0] == fp:
                    con.execute(
                        "UPDATE scan_state SET last_seen = ? WHERE path = ?",
                        (now, path),
                    )
                    counts["unchanged"] += 1
                else:
                    meta = scanner.derive_meta(path, root)
                    info = identify(path)
                    con.execute("DELETE FROM asset WHERE path = ?", (path,))
                    con.execute(
                        "INSERT INTO asset(source_id, kind, path, name, theme,"
                        " context, ext, size_px, width, height, bytes,"
                        " colorspace, color_count, mono, mtime)"
                        " VALUES (?, 'icon', ?, ?, ?, ?, ?, ?, ?, ?, ?,"
                        " ?, ?, ?, ?)",
                        (source_id, path, meta["name"], meta["theme"],
                         meta["context"], meta["ext"], meta["size_px"],
                         info["width"], info["height"], info["bytes"],
                         info["colorspace"], info["color_count"],
                         info["mono"], os.path.getmtime(path)),
                    )
                    con.execute(
                        "INSERT INTO scan_state(path, fingerprint, last_seen)"
                        " VALUES (?, ?, ?) ON CONFLICT(path) DO UPDATE SET"
                        " fingerprint=excluded.fingerprint,"
                        " last_seen=excluded.last_seen",
                        (path, fp, now),
                    )
                    counts["changed" if prev is not None else "new"] += 1
                if progress:
                    progress(counts["total"], path)

            # prune assets + fingerprints that vanished from this source
            rows = con.execute(
                "SELECT path FROM asset WHERE source_id = ?", (source_id,)
            ).fetchall()
            for (path,) in rows:
                if path not in seen:
                    con.execute("DELETE FROM asset WHERE path = ?", (path,))
                    con.execute("DELETE FROM scan_state WHERE path = ?", (path,))
                    counts["pruned"] += 1
            st_rows = con.execute("SELECT path FROM scan_state").fetchall()
            root_prefix = str(Path(root).resolve()) + os.sep
            for (path,) in st_rows:
                if path.startswith(root_prefix) and path not in seen:
                    con.execute("DELETE FROM scan_state WHERE path = ?", (path,))
        con.commit()
    except Exception:
        con.rollback()
        raise
    return counts


def ensure_sources(con: sqlite3.Connection,
                   roots: list[Path]) -> list[tuple[int, str]]:
    """Insert missing source rows, disable stale ones, return enabled set.

    Sources previously added by the user (kind='folder') are always kept
    even when their root no longer exists — pruning then removes the
    missing files on the next scan, which mirrors the 0.x --merge-list flow.
    """
    known = {r["path"]: r for r in
             con.execute("SELECT id, path, kind, enabled FROM source")}
    root_strs = {str(Path(r).resolve()): r for r in roots}
    for path_str in root_strs:
        if path_str not in known:
            label = Path(path_str).name or path_str
            cur = con.execute(
                "INSERT INTO source(kind, path, label, enabled)"
                " VALUES ('system', ?, ?, 1)",
                (path_str, label),
            )
            known[path_str] = {"id": cur.lastrowid, "path": path_str,
                               "kind": "system", "enabled": 1}
    enabled: list[tuple[int, str]] = []
    for path_str, row in known.items():
        exists = os.path.isdir(path_str)
        should_enable = 1 if (exists and path_str in root_strs) else row["enabled"]
        if row["kind"] == "folder":
            should_enable = row["enabled"]  # user decides; folder stays as-is
        if row["enabled"] != should_enable:
            con.execute("UPDATE source SET enabled=? WHERE id=?",
                        (should_enable, row["id"]))
        if should_enable and exists:
            enabled.append((row["id"], path_str))
    con.commit()
    return enabled


def add_folder_source(con: sqlite3.Connection, folder: str) -> int:
    folder = str(Path(folder).resolve())
    row = con.execute("SELECT id FROM source WHERE path = ?", (folder,)).fetchone()
    if row:
        con.execute("UPDATE source SET enabled = 1 WHERE id = ?", (row[0],))
        con.commit()
        return row[0]
    cur = con.execute(
        "INSERT INTO source(kind, path, label, enabled) VALUES ('folder', ?, ?, 1)",
        (folder, Path(folder).name or folder),
    )
    con.commit()
    return cur.lastrowid


def sources_summary(con: sqlite3.Connection) -> list[dict]:
    rows = con.execute(
        "SELECT s.id, s.kind, s.path, s.label, s.enabled,"
        " COUNT(a.id) AS n"
        " FROM source s LEFT JOIN asset a ON a.source_id = s.id"
        " GROUP BY s.id ORDER BY s.kind, s.label"
    ).fetchall()
    return [dict(r) for r in rows]
