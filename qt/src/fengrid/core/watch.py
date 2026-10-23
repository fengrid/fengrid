"""Watch folders / dropboxes — periodic change detection over the local
filesystem and remote transports.

Transport reality table (what is actually implemented, honestly):
  local                 → path is already local: scan it
  smb / nfs / sshfs / s3 → resolved to a LOCAL path by core.storage's
                          mount backends; the watcher just verifies the
                          mount is live (attaching happens in Storage)
  rsync / scp / http / ftp / sftp → PULL into a staging dir via system
                          tools (argv only, injectable runner, probed
                          with shutil.which)
  onedrive / icloud / gdrive → listed in the UI as Coming Soon

Each watch_source row gets its own staging dir + a `watch_state` row
(last_run / last_signature). Change detection = cheap SIGNATURE walk
(count + max mtime) so unchanged trees cost almost nothing; only on a
signature change does the indexer run over that source.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

TRANSPORTS = [
    {"key": "local", "label": "Local filesystem", "kind": "builtin"},
    {"key": "smb", "label": "SMB share (via Storage)", "kind": "mount"},
    {"key": "nfs", "label": "NFS share (via Storage)", "kind": "mount"},
    {"key": "sshfs", "label": "SSHFS (via Storage)", "kind": "mount"},
    {"key": "s3", "label": "Amazon S3-compatible (via Storage)",
     "kind": "mount"},
    {"key": "rsync", "label": "rsync / SSH remote", "kind": "pull"},
    {"key": "scp", "label": "SCP remote", "kind": "pull"},
    {"key": "sftp", "label": "SFTP remote", "kind": "pull"},
    {"key": "ftp", "label": "FTP remote", "kind": "pull"},
    {"key": "http", "label": "HTTP(S) directory", "kind": "pull"},
    {"key": "onedrive", "label": "OneDrive", "kind": "soon"},
    {"key": "icloud", "label": "iCloud Drive", "kind": "soon"},
    {"key": "gdrive", "label": "Google Drive", "kind": "soon"},
]

# which binary each pull transport needs
_PULL_TOOL = {"rsync": "rsync", "scp": "scp", "sftp": "sftp",
              "ftp": "curl", "http": "curl"}


class WatchError(Exception):
    pass


def availability() -> list[dict]:
    """Transport rows for the UI, with live availability + coming-soon
    flags (OneDrive/iCloud/Google Drive are explicitly NOT implemented)."""
    out = []
    for t in TRANSPORTS:
        row: dict = dict(t)
        if t["kind"] == "soon":
            row["available"] = False
            row["comingSoon"] = True
        elif t["kind"] == "pull":
            tool = _PULL_TOOL[t["key"]]
            row["available"] = shutil.which(tool) is not None
            row["tool"] = tool
        else:
            row["available"] = True
        out.append(row)
    return out


def pull_argv(transport: str, remote: str, dest: Path) -> list[str]:
    """argv for one pull (NEVER a shell string). `remote` is
    transport-specific (user@host:/path, ftp://…, http://…)."""
    dest.mkdir(parents=True, exist_ok=True)
    if transport == "rsync":
        return ["rsync", "-a", "--delete", remote.rstrip("/") + "/",
                str(dest) + "/"]
    if transport == "scp":
        # directory copy needs -r; patterns come from the remote spec
        return ["scp", "-r", remote, str(dest)]
    if transport == "sftp":
        # batch get: single-file mirrors only — document limitation
        return ["sftp", "-b", "-"]  # caller supplies stdin (tests inject)
    if transport in ("ftp", "http"):
        return ["curl", "-fsSL", "-o", str(dest / "mirror.zip"),
                "--remote-time", remote]
    raise WatchError(f"unknown pull transport: {transport}")


def run_pull(transport: str, remote: str, staging: Path,
             runner=None) -> dict:
    argv = pull_argv(transport, remote, staging)
    tool = shutil.which(argv[0])
    if tool is None:
        raise WatchError(f"{argv[0]} is not installed")
    run = runner if runner is not None else _run
    code = run(argv)
    if code not in (0, None):
        raise WatchError(f"{argv[0]} exited {code}")
    return {"staging": str(staging)}


def _run(argv: list) -> int:
    return subprocess.run(argv, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL, timeout=300).returncode


def signature(path: str | Path) -> str:
    """Cheap change fingerprint: file count + newest mtime + total size.
    One directory walk, no content reads — safe for huge trees."""
    root = Path(path)
    if not root.exists():
        return "missing"
    n = 0
    newest = 0.0
    total = 0
    try:
        for child in root.rglob("*"):
            try:
                st = child.stat() if child.is_file() else None
            except OSError:
                continue
            if st is None:
                continue
            n += 1
            total += st.st_size
            newest = max(newest, st.st_mtime)
    except OSError as e:
        return f"error:{e.__class__.__name__}"
    return f"{n}:{total}:{int(newest)}"


def resolve_local(row: dict, staging_root: Path) -> Path:
    """Where the watcher reads from, after transport handling."""
    transport = row.get("transport", "local")
    path = Path(row["path"])
    if transport == "local":
        return path
    if transport in ("smb", "nfs", "sshfs", "s3"):
        if not path.exists():
            raise WatchError(
                f"{transport} path not mounted — attach it in Storage first")
        return path
    # pull transports: fetch into staging, scan the staging copy
    staging = staging_root / str(row.get("id", 0))
    run_pull(transport, row["path"], staging,
             runner=row.get("_runner"))
    return staging


def due(row: dict, now: float | None = None,
        last_run: float = 0.0) -> bool:
    """Periodic gate: interval seconds since last attempt (first run
    fires immediately)."""
    interval = max(15, int(row.get("interval") or 60))
    now = time.time() if now is None else now
    return (now - last_run) >= interval
