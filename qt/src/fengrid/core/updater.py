"""Update checking for the Qt workbench (M5).

Primary probe is the GitHub releases API over urllib — no external binary,
works on every platform the app ships for. `git ls-remote --tags` is the
fallback (the 0.x update.sh probe) for hosts where HTTPS to api.github.com
is blocked but git works. Both are pure functions over parsed output, so
they unit-test without network.
"""

from __future__ import annotations

import json
import re
import subprocess
import urllib.request

REPO_URL = "https://github.com/fengrid/fengrid"
RELEASES_URL = REPO_URL + "/releases/latest"
API_URL = "https://api.github.com/repos/fengrid/fengrid/releases/latest"


def parse_version(tag: str) -> tuple[int, int, int] | None:
    """'v0.3.2' / '0.3.2' / 'v0.3.2-dev.1' → (0, 3, 2); None when not X.Y.Z."""
    if not tag:
        return None
    m = re.match(r"^[vV]?(\d+)\.(\d+)\.(\d+)", tag.strip())
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def is_newer(latest_tag: str, current_version: str) -> bool:
    """True when latest_tag is a strictly higher X.Y.Z than current_version
    ('0.3.0.dev0' compares as 0.3.0 — dev suffix never counts as newer)."""
    lat = parse_version(latest_tag)
    cur = parse_version(current_version)
    if lat is None or cur is None:
        return False
    return lat > cur


def _http_get_json(url: str, timeout: float = 6.0) -> dict | None:
    try:
        req = urllib.request.Request(
            url, headers={"Accept": "application/vnd.github+json",
                          "User-Agent": "fengrid-updater"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001 — network failures are expected here
        return None


def parse_ls_remote(output: str) -> str | None:
    """Newest plain tag from `git ls-remote --tags` output.

    Ignores the peeled '^{}' lines of annotated tags and any tag that does
    not start with vX.Y.Z (0.x also shipped legacy names).
    """
    best: tuple | None = None
    best_tag = None
    for line in output.splitlines():
        ref = line.split("\t", 1)[1] if "\t" in line else ""
        ref = ref.removeprefix("refs/tags/")
        if ref.endswith("^{}"):
            continue
        ver = parse_version(ref)
        if ver is not None and (best is None or ver > best):
            best = ver
            best_tag = ref
    return best_tag


def probe(timeout: float = 6.0) -> str | None:
    """Latest release tag, or None when unreachable/offline."""
    data = _http_get_json(API_URL, timeout)
    if data and isinstance(data.get("tag_name"), str):
        return data["tag_name"]
    # fallback: git ls-remote (the 0.x probe), newest-tag heuristic
    try:
        out = subprocess.run(
            ["git", "ls-remote", "--tags", REPO_URL],
            capture_output=True, text=True, timeout=timeout, check=True,
        ).stdout
        return parse_ls_remote(out)
    except Exception:  # noqa: BLE001 — offline / no git
        return None
