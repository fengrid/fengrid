"""Default font-specimen preview text.

Loads resources/preview_text.json (haiku, poem lines, speech lines —
public domain) and serves a random passage from the bucket matching
the current preview size. Exactly three breakpoints keep swaps rare:

  previewPx >= 48  → "large"  (short, punchy passages)
  20..47           → "medium"
  < 20             → "small"  (longer, filling passages)
"""

from __future__ import annotations

import json
import random
from importlib import resources
from pathlib import Path

_CACHE: dict | None = None


def _data() -> dict:
    global _CACHE
    if _CACHE is None:
        p = Path(__file__).resolve().parent.parent / "resources" / \
            "preview_text.json"
        if not p.is_file():                     # frozen / packaged layouts
            try:
                p = Path(str(resources.files("fengrid").joinpath(
                    "resources/preview_text.json")))
            except Exception:                    # noqa: BLE001
                p = None
        if p is None or not p.is_file():
            _CACHE = {"groups": {}, "breakpoints": []}
        else:
            _CACHE = json.loads(p.read_text(encoding="utf-8"))
    return _CACHE


def bucket_for(px: int) -> str:
    """Bucket name for a preview pixel size (2-3 breakpoints)."""
    for bp in _data().get("breakpoints", []):
        if px <= bp["max_px"]:
            return bp["bucket"]
    return "medium"


def boundaries() -> list[tuple[int, str]]:
    """(max_px, bucket) ascending — the size classes the picker swaps
    between. The fonts bridge exposes the two lower edges as properties
    so the grid's QML picks a specimen without a Python round-trip
    (#137: per-card slot calls on every grid resize flooded the bridge)."""
    bps = [(int(bp.get("max_px", 0)), str(bp.get("bucket", "")))
           for bp in _data().get("breakpoints", [])]
    return sorted(bps)


def candidates(bucket: str) -> list[dict]:
    """Curated 'fit' passages for the bucket, falling back to all."""
    out = []
    for group in _data().get("groups", {}).values():
        for entry in group:
            if entry.get("fit") == bucket:
                out.append(entry)
    if out:
        return out
    for group in _data().get("groups", {}).values():
        out.extend(group)
    return out


def pick(bucket: str, rng: random.Random | None = None) -> str:
    cands = candidates(bucket)
    if not cands:
        return "The quick brown fox jumps over the lazy dog"
    entry = (rng or random).choice(cands)
    return entry["text"]


def reshuffle() -> dict[str, str]:
    """One random passage PER bucket — call when the Fonts pane opens
    so the specimen text changes each session, not on every size tick."""
    rng = random.Random()
    return {b: pick(b, rng) for b in ("large", "medium", "small")}


def stats() -> dict:
    out: dict[str, int] = {}
    for name, group in _data().get("groups", {}).items():
        out[name] = len(group)
    return out
