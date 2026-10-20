"""Search modes for the library: smart (FTS), fuzzy, regex, and content.

- smart   — the existing FTS5 prefix search (indexer-maintained, fast).
- fuzzy   — subsequence + similarity ranking over indexed names/paths
            (difflib ratios, capped candidate set; pure CPU, no extra
            memory beyond the name list).
- regex   — Python re over names/paths. Patterns are compiled once and the
            scan is bounded; pathological patterns can still burn CPU, so
            the candidate cap applies and errors surface as SearchError.
- content — searches INSIDE files: snippet bodies (html/css/js) and
            text-like asset files (svg/xml/html/css/js/json/md, size-capped).

Performance notes (large collections):
  * fuzzy/regex scan an in-memory candidate list built in ONE query and
    capped at MAX_CANDIDATES (names are tiny strings; 100k names ≈ a few
    MB and ~0.5s per search — the cap keeps worst cases bounded).
  * content search is I/O bound: file reads are capped per-file
    (MAX_FILE_BYTES) and per-search (MAX_SCANS). For serious content
    search at scale, an FTS5 index over extracted text (updated by the
    indexer's metadata pass) is the right upgrade path — the indexer
    already visits every file once, so it should populate
    asset_fts-like content text then, not at query time.
"""

from __future__ import annotations

import difflib
import re
import sqlite3
from pathlib import Path

MODES = ("smart", "fuzzy", "regex", "content")

MAX_CANDIDATES = 100_000
MAX_RESULTS = 500
MAX_FILE_BYTES = 256 * 1024
MAX_SCANS = 2_000
TEXT_EXTS = {".svg", ".xml", ".html", ".htm", ".css", ".js", ".json",
             ".md", ".txt", ".toml", ".yaml", ".yml", ".ini"}


class SearchError(ValueError):
    """Bad query (e.g. invalid regex) — surfaced to the UI."""


def _candidates(con: sqlite3.Connection) -> list[tuple[int, str, str]]:
    """(asset_id, name, path) for scoring — one query, bounded."""
    rows = con.execute(
        "SELECT id, name, path FROM asset LIMIT ?", (MAX_CANDIDATES,),
    ).fetchall()
    return [(r["id"], r["name"], r["path"]) for r in rows]


def search_assets(con: sqlite3.Connection, term: str, mode: str = "smart",
                  limit: int = MAX_RESULTS) -> list[dict]:
    """Asset rows for the grid, best matches first (fuzzy) or natural
    order. The `smart` mode is handled by the library bridge's FTS query;
    this module covers fuzzy / regex / content."""
    term = (term or "").strip()
    if not term:
        return []
    if mode == "fuzzy":
        return _fuzzy(con, term, limit)
    if mode == "regex":
        return _regex(con, term, limit)
    if mode == "content":
        return _content(con, term, limit)
    raise SearchError("unknown search mode: %s" % mode)


def _fuzzy(con, term: str, limit: int) -> list[dict]:
    t = term.lower()
    rows = []
    for aid, name, path in _candidates(con):
        # subsequence hit on the name is the fast path; ratio refines rank
        ratio = difflib.SequenceMatcher(None, t, name.lower()).ratio()
        sub = _subsequence(t, name.lower())
        if not sub and ratio < 0.45:
            continue
        path_bonus = 0.1 if t in path.lower() else 0.0
        score = ratio + (0.35 if sub else 0.0) + path_bonus
        rows.append({"id": aid, "name": name, "path": path,
                     "score": round(score, 3)})
    rows.sort(key=lambda r: r["score"], reverse=True)
    return _full_rows(con, rows[:limit])


def _subsequence(needle: str, hay: str) -> bool:
    it = iter(hay)
    return all(ch in it for ch in needle)


def _regex(con, pattern: str, limit: int) -> list[dict]:
    try:
        rx = re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        raise SearchError("invalid regex: %s" % exc) from exc
    rows = []
    for aid, name, path in _candidates(con):
        if rx.search(name) or rx.search(path):
            rows.append({"id": aid, "name": name, "path": path, "score": 1.0})
        if len(rows) >= limit:
            break
    return _full_rows(con, rows)


def _content(con, term: str, limit: int) -> list[dict]:
    """Search inside snippet bodies and text-like asset files (both capped)."""
    hits: list[dict] = []
    needle = term.lower()

    # 1) snippets — the DB stores their bodies, so this is pure SQL
    for r in con.execute(
            "SELECT id, title, html, css, js FROM snippet"
            " WHERE lower(html) LIKE ? OR lower(css) LIKE ?"
            " OR lower(js) LIKE ? LIMIT ?",
            ("%" + needle + "%",) * 3 + (limit,)):
        hits.append({"kind": "snippet", "id": r["id"], "name": r["title"],
                     "path": "snippet", "score": 1.0})
        if len(hits) >= limit:
            return hits

    # 2) text-like asset files — bounded I/O
    scans = 0
    for r in con.execute(
            "SELECT id, name, path, ext FROM asset"
            " WHERE kind = 'icon' ORDER BY id"):
        ext = (r["ext"] or "").lstrip(".").lower()
        if ext not in {e.lstrip(".") for e in TEXT_EXTS}:
            continue
        scans += 1
        if scans > MAX_SCANS:
            break
        p = Path(r["path"])
        try:
            if p.stat().st_size > MAX_FILE_BYTES:
                continue
            text = p.read_text(encoding="utf-8", errors="ignore").lower()
        except OSError:
            continue
        if needle in text:
            hits.append({"kind": "asset", "id": r["id"], "name": r["name"],
                         "path": r["path"], "score": 1.0})
            if len(hits) >= limit:
                break
    return hits


def _full_rows(con, hits: list[dict]) -> list[dict]:
    """Hydrate score-ordered ids into full grid rows (library model shape)."""
    out = []
    for h in hits:
        if h.get("kind") == "snippet":
            continue
        row = con.execute("SELECT * FROM asset WHERE id = ?",
                          (h["id"],)).fetchone()
        if row is None:
            continue
        d = dict(row)
        d["sizePx"] = d.pop("size_px", None)
        d["score"] = h["score"]
        out.append(d)
    return out


def search_snippets(con: sqlite3.Connection, term: str,
                    include_content: bool = False) -> list[int]:
    """Snippet ids matching title/description/tags — plus body content when
    include_content is on (LIKE-based, bounded by the snippet table size)."""
    needle = "%" + term.lower().strip() + "%"
    if not term.strip():
        return []
    if include_content:
        sql = ("SELECT id FROM snippet WHERE lower(title) LIKE ?"
               " OR lower(description) LIKE ? OR lower(tags) LIKE ?"
               " OR lower(html) LIKE ? OR lower(css) LIKE ?"
               " OR lower(js) LIKE ? ORDER BY updated DESC")
        params = [needle] * 6
    else:
        sql = ("SELECT id FROM snippet WHERE lower(title) LIKE ?"
               " OR lower(description) LIKE ? OR lower(tags) LIKE ?"
               " ORDER BY updated DESC")
        params = [needle] * 3
    return [r["id"] for r in con.execute(sql, params)]
