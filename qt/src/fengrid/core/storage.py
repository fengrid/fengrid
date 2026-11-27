"""Storage backends: where a Fengrid database's asset content lives.

Every backend resolves to a LOCAL PATH before the scanner sees it —
mount-based attach (sshfs / gio for SMB / s3fs / mount for NFS) is the
seam, so scan, fingerprint, preview and export keep working unchanged
and no credential ever passes through Fengrid's own storage: ssh uses
the agent/config, SMB the session keyring, s3fs its profile file.

All commands run through an injectable `runner` (subprocess.run
shape), which is how the tests exercise attach/detach logic without
root, network or FUSE.

Statuses are honest: a backend with missing tooling reports exactly
what to install, and any backend can also be fed an ALREADY-mounted
local path (manual mount fallback — the supported route for NFS
without root).
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


class StorageError(Exception):
    """Attach/detach failure with a user-presentable message."""


@dataclass(frozen=True)
class Backend:
    key: str
    label: str
    hint: str                       # placeholder/example for the URI field
    tools: tuple[str, ...] = ()     # ALL of these must be on PATH
    tool_note: str = ""             # install hint when a tool is missing


BACKENDS: dict[str, Backend] = {
    "local": Backend(
        key="local",
        label="Local folder",
        hint="/home/you/Pictures/icons",
    ),
    "smb": Backend(
        key="smb",
        label="SMB / CIFS share",
        hint="smb://server/share/folder",
        tools=("gio",),
        tool_note="credentials come from the session keyring — or mount"
                  " the share with your system and attach its local path",
    ),
    "nfs": Backend(
        key="nfs",
        label="NFS export",
        hint="server:/export/graphics",
        tools=("mount",),
        tool_note="NFS mounts need root — add an fstab entry with the"
                  " `user` option, mount it, then attach the local path",
    ),
    "sshfs": Backend(
        key="sshfs",
        label="SSHFS (SFTP)",
        hint="user@host:/srv/assets",
        tools=("sshfs",),
        tool_note="keys/auth come from your ssh agent or ~/.ssh/config",
    ),
    "s3": Backend(
        key="s3",
        label="S3-compatible bucket",
        hint="my-bucket/assets   (endpoint: https://s3.example.com)",
        tools=("s3fs",),
        tool_note="credentials come from ~/.passwd-s3fs or the AWS"
                  " environment",
    ),
}

# mounts that FUSE manages get a lazy unmount; gvfs has its own verb
_FUSE_BACKENDS = {"sshfs", "s3", "nfs"}


def _is_mount(path: Path) -> bool:
    return os.path.ismount(str(path))


def default_runner(cmd: list[str], timeout: int = 45) -> subprocess.CompletedProcess:
    """Real subprocess runner (tests inject their own)."""
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, check=False)


def availability(backend_key: str) -> tuple[bool, str]:
    """(ready, status line) for the Settings UI."""
    b = BACKENDS[backend_key]
    if not b.tools:
        return True, "ready"
    missing = [t for t in b.tools if shutil.which(t) is None]
    if missing:
        return False, f"install {', '.join(missing)} — {b.tool_note}"
    return True, f"via {' + '.join(b.tools)} — {b.tool_note}"


def mountpoint_for(data_dir: str | Path, backend_key: str,
                   uri: str) -> Path:
    """Deterministic mount dir under the data dir (stable across
    relaunches so remount + registered sources keep their path)."""
    slug = "".join(c if c.isalnum() or c in "-_" else "-"
                   for c in uri.lower()).strip("-")[:60] or "root"
    return Path(data_dir) / "mounts" / backend_key / slug


def build_cmd(backend_key: str, uri: str, mountpoint: Path) -> list[str]:
    """The exact mount command for a backend (pure — unit tested)."""
    if backend_key == "sshfs":
        return ["sshfs", uri, str(mountpoint)]
    if backend_key == "nfs":
        return ["mount", "-t", "nfs", uri, str(mountpoint)]
    if backend_key == "s3":
        # bucket[/prefix] as uri; endpoint rides -o url when given as
        # "bucket" with an "endpoint=" option appended by power users
        return ["s3fs", uri.split()[0], str(mountpoint), "-o", "allow_other"]
    if backend_key == "smb":
        # gvfs does the credential dance (session keyring) and picks
        # its own mountpoint — we discover it afterwards
        return ["gio", "mount", uri]
    raise StorageError(f"unknown backend: {backend_key}")


def _gvfs_root() -> Path | None:
    uid = os.getuid()
    root = Path(f"/run/user/{uid}/gvfs")
    return root if root.is_dir() else None


def _gvfs_new_entries(before: set[str]) -> list[Path]:
    root = _gvfs_root()
    if root is None:
        return []
    now = {str(p) for p in root.iterdir()}
    return [Path(p) for p in sorted(now - before)]


def attach(backend_key: str, uri: str, data_dir: str | Path,
           runner: Callable = default_runner) -> Path:
    """Attach a backend and return the local path to scan.

    A URI that already IS an existing local dir short-circuits (the
    manual-mount fallback for any backend, and the normal local flow).
    """
    if backend_key not in BACKENDS:
        raise StorageError(f"unknown backend: {backend_key}")
    if backend_key == "local" or Path(uri).expanduser().is_dir():
        p = Path(uri).expanduser()
        if not p.is_dir():
            raise StorageError(f"Not a folder: {uri}")
        return p.resolve()

    ready, status = availability(backend_key)
    if not ready:
        raise StorageError(status)

    mountpoint = mountpoint_for(data_dir, backend_key, uri)
    mountpoint.mkdir(parents=True, exist_ok=True)

    if backend_key == "smb":
        gvfs = _gvfs_root()
        before = {str(p) for p in gvfs.iterdir()} if gvfs else set()
        proc = runner(build_cmd("smb", uri, mountpoint), timeout=45)
        if proc.returncode != 0:
            raise StorageError(_tail(proc) or f"gio mount failed ({uri})")
        found = _gvfs_new_entries(before)
        if not found:
            raise StorageError(
                f"mounted, but no new gvfs entry appeared for {uri}")
        return found[0]

    if _is_mount(mountpoint):
        return mountpoint          # already mounted — reuse
    proc = runner(build_cmd(backend_key, uri, mountpoint), timeout=45)
    if proc.returncode != 0:
        raise StorageError(_tail(proc) or f"mount failed ({uri})")
    if not mountpoint.is_dir():
        raise StorageError(f"mount vanished: {mountpoint}")
    return mountpoint


def detach(backend_key: str, uri: str, mountpoint: str | Path,
           runner: Callable = default_runner) -> None:
    """Unmount (best effort — a missing mount is not an error)."""
    mountpoint = Path(mountpoint)
    if not mountpoint.exists():
        return
    if not _is_mount(mountpoint) and backend_key not in ("smb", "local"):
        return  # already unmounted / plain local dir
    if backend_key in ("local", "smb"):
        if backend_key == "local":
            return                  # local dirs are never unmounted
        proc = runner(["gio", "mount", "-u", uri], timeout=30)
    elif shutil.which("fusermount3") or shutil.which("fusermount"):
        fuse = shutil.which("fusermount3") or shutil.which("fusermount")
        proc = runner([fuse, "-u", str(mountpoint)], timeout=30)
    else:
        proc = runner(["umount", str(mountpoint)], timeout=30)
    if proc.returncode != 0:
        raise StorageError(_tail(proc) or f"unmount failed: {mountpoint}")
    if mountpoint.is_dir() and not any(mountpoint.iterdir()):
        mountpoint.rmdir()   # our own empty dir under data_dir/mounts


def healthy(mountpoint: str | Path, backend_key: str = "") -> bool:
    """Liveness check for a registered mount.

    gvfs entries exist only while mounted (attach returns the live
    gvfs path), so existence is enough for smb; FUSE/NFS mounts need a
    real mountpoint check — a leftover empty dir after reboot must NOT
    read as healthy (remount has to run)."""
    p = Path(mountpoint)
    try:
        if backend_key == "local":
            return p.is_dir()
        if backend_key == "smb":
            return p.exists()
        return _is_mount(p) or (p.is_dir() and backend_key == ""
                                and any(p.iterdir()))
    except OSError:
        return False


def _tail(proc: subprocess.CompletedProcess, lines: int = 3) -> str:
    err = (getattr(proc, "stderr", "") or "").strip().splitlines()
    out = (getattr(proc, "stdout", "") or "").strip().splitlines()
    return " — ".join((err or out)[-lines:])