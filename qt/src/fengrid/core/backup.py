"""Backup / restore + SQLite database administration.

backup(): uses sqlite3's Online Backup API → a CONSISTENT snapshot even
while a scan is writing (a naive file copy of a WAL database can capture
a torn state; the backup API cannot). The zip carries the library DB,
the app registry (global prefs + known databases) and a manifest.

restore(): validates the manifest first, moves the current DB aside to
`<name>.pre-restore` (one-step rollback), then atomically replaces.

dbadmin: stats / integrity / VACUUM / WAL checkpoint / PRAGMA optimize /
FTS rebuild / orphan sweep — everything a "manage the database" screen
needs, as pure functions over a connection (worker-thread callers).
"""
from __future__ import annotations

import getpass
import hashlib
import io
import json
import os
import platform
import re
import shutil
import sqlite3
import sys
import tarfile
import time
import zipfile
from pathlib import Path

MANIFEST_NAME = "backup-manifest.json"
PACKAGE_SUFFIX = ".tar.gz"


class BackupError(Exception):
    pass


def backup(db_path: str | Path, dest_dir: str | Path, *,
           registry_path: str = "",
           label: str = "",
           extra_paths: list | None = None,
           data_dir: str | Path = "",
           logs_dir: str | Path = "") -> dict:
    """Create a self-contained restore PACKAGE:
    `<dest>/fengrid-backup-<ts>[-label].tar.gz` containing

      backup.json      structured manifest — version/build details,
                       system settings (DB setting table), user
                       preferences (registry globals), configuration
                       options (sources/mounts/watches/import-export
                       opts/databases), local environment details,
                       file checksums and the log index
      library.db       full consistent copy (SQLite online-backup API —
                       safe mid-scan)
      registry.db      full consistent copy of the app registry
      logs/*.log       captured logs/debug tails when present
      restore.sh       POSIX restore script (Linux/macOS)
      restore.ps1      Windows restore script

    Both scripts embed the RELEASE TAG recorded in the manifest and the
    target-machine data dir is recomputed on the destination (usernames
    and install paths in the manifest are informational only)."""
    db_path = Path(db_path)
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    safe_label = "".join(c for c in (label or "") if c.isalnum()
                         or c in "-_ ")[:40].strip().replace(" ", "-")
    name = (f"fengrid-backup-{ts}"
            f"{('-' + safe_label) if safe_label else ''}.tar.gz")
    out = dest_dir / name

    # consistent snapshots to temp files (backup API — never torn)
    snap_db = dest_dir / f".{name}.library"
    snap_reg = dest_dir / f".{name}.registry"
    try:
        _snapshot(db_path, snap_db)
        extras: list[Path] = []
        if registry_path and Path(registry_path).is_file():
            _snapshot(registry_path, snap_reg)
            extras.append(snap_reg)
        else:
            snap_reg = None

        manifest = _manifest_v2(db_path, snap_db,
                                registry_path=registry_path,
                                label=safe_label,
                                extra_paths=extra_paths or [],
                                data_dir=data_dir, logs_dir=logs_dir)
        scripts = generate_restore_scripts(manifest)

        logs = _collect_logs(logs_dir, data_dir)
        tmp = out.with_suffix(".tar.gz.tmp")
        with tarfile.open(tmp, "w:gz") as tf:
            _tar_add_bytes(tf, MANIFEST_NAME,
                           json.dumps(manifest, indent=1))
            _tar_add_file(tf, snap_db, "library.db", mode=0o644)
            for e in extras:
                # snapshot temps are .pkg.registry — the ARCHIVE member
                # must carry the real database name scripts look for
                _tar_add_file(tf, e, "registry.db", mode=0o644)
            for lp in logs:
                _tar_add_file(tf, lp["path"], lp["name"], mode=0o644)
            _tar_add_bytes(tf, "restore/restore.sh", scripts["restore.sh"],
                           mode=0o755)
            _tar_add_bytes(tf, "restore/restore.ps1",
                           scripts["restore.ps1"], mode=0o644)
        os.replace(tmp, out)
    finally:
        snap_db.unlink(missing_ok=True)
        if snap_reg is not None:
            Path(snap_reg).unlink(missing_ok=True)
        for junk in dest_dir.glob(f".{name}.*"):
            junk.unlink(missing_ok=True)
        for lp in locals().get("logs", []) or []:
            Path(lp.get("tmp", "")).unlink(missing_ok=True)
    return {"path": str(out), "name": name,
            "bytes": out.stat().st_size}


def _snapshot(src: Path, dest: Path) -> None:
    """Consistent online-backup snapshot of one database file."""
    source = sqlite3.connect(str(src))
    try:
        target = sqlite3.connect(str(dest))
        try:
            with target:
                source.backup(target)
        finally:
            target.close()
    finally:
        source.close()


def _tag_for(version: str) -> tuple[str, bool]:
    """'0.3.0.dev0' → ('v0.3.0', False) — dev builds map to their base
    release tag; the second element flags pre-release (the restore
    script warns before downloading)."""
    m = re.match(r"v?(\d+)\.(\d+)\.(\d+)", version or "")
    if not m:
        return ("", False)
    tag = f"v{m.group(1)}.{m.group(2)}.{m.group(3)}"
    return (tag, bool(re.search(r"dev|alpha|beta|rc", version or "")))


def _settings_dump(con: sqlite3.Connection) -> dict:
    out = {}
    try:
        for r in con.execute("SELECT key, value FROM setting ORDER BY key"):
            out[r[0]] = r[1]
    except sqlite3.Error:
        pass
    return out


def _rows(con: sqlite3.Connection, sql: str) -> list[dict]:
    try:
        return [dict(r) for r in con.execute(sql)]
    except sqlite3.Error:
        return []


def _row_counts(con: sqlite3.Connection) -> dict:
    """Counts for the fixed, well-known tables only — dynamic SQL over
    sqlite_master is a quoting trap and none of it is worth it here."""
    counts = {}
    for t in ("asset", "source", "collection", "collection_ref", "tag",
              "item_tag", "snippet", "palette", "projects",
              "watch_source", "storage_mount"):
        try:
            counts[t] = int(con.execute(
                f'SELECT COUNT(*) FROM "{t}"').fetchone()[0])
        except sqlite3.Error:
            counts[t] = 0
    return counts


def _manifest_v2(db_path: Path, snap_db: Path, *, registry_path: str,
                  label: str, extra_paths: list, data_dir,
                  logs_dir) -> dict:
    from .. import __version__

    version = __version__
    tag, prerelease = _tag_for(version)
    con = sqlite3.connect(str(snap_db))
    con.row_factory = sqlite3.Row
    try:
        system_settings = _settings_dump(con)
        configuration = {
            "sources": _rows(con, "SELECT kind, path, label, enabled"
                                       " FROM source ORDER BY id"),
            "storage_mounts": _rows(con, "SELECT backend, uri, local_path,"
                                                " kind FROM storage_mount"
                                       " ORDER BY id"),
            "watch_sources": _rows(con, "SELECT path, label, transport,"
                                               " interval, enabled"
                                       " FROM watch_source ORDER BY id"),
            "collections": _rows(con, "SELECT id, name FROM collection"
                                       " ORDER BY id"),
                        "row_counts": _row_counts(con),
        }
        for key in ("import_opts", "export_opts"):
            raw = None
            for r in con.execute("SELECT value FROM setting WHERE key=?",
                                 (key,)):
                raw = r[0]
            if raw:
                try:
                    configuration[key] = json.loads(raw)
                except ValueError:
                    configuration[key] = raw
    finally:
        con.close()

    user_prefs: dict = {}
    dbs_list: list = []
    if registry_path and Path(registry_path).is_file():
        rcon = sqlite3.connect(f"file:{registry_path}?mode=ro", uri=True)
        rcon.row_factory = sqlite3.Row
        try:
            user_prefs = _settings_dump(rcon)
            dbs_list = _rows(rcon, "SELECT path, label, starred,"
                                   " last_opened FROM registry_db"
                                   " ORDER BY last_opened DESC")
        except sqlite3.Error:
            pass
        finally:
            rcon.close()
    configuration["databases"] = dbs_list

    # build/runtime details
    build = {
        "app": "fengrid",
        "app_version": version,
        "release_tag": tag,
        "prerelease": prerelease,
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "frozen": bool(getattr(sys, "frozen", False)),
    }
    try:
        import PySide6
        build["pyside"] = getattr(PySide6, "__version__", "")
    except Exception:
        build["pyside"] = ""
    try:
        from PySide6.QtCore import QT_VERSION_STR
        build["qt"] = QT_VERSION_STR
    except Exception:
        build["qt"] = ""

    environment = {
        "os": platform.platform(),
        "system": platform.system(),
        "machine": platform.machine(),
        "hostname": platform.node(),
        "user": getpass.getuser() if _has_getpass() else "",
        "home": str(Path.home()),
        "data_dir": str(data_dir or ""),
        "database": str(db_path),
        "registry": str(registry_path or ""),
        "cwd": os.getcwd(),
        "locale": ".".join(part for part in (platform.libc_ver()[0],
                                             platform.libc_ver()[1])
                           if part) or "",
        "tools": {t: bool(shutil.which(t)) for t in
                  ("rsync", "scp", "sftp", "curl", "git", "magick")},
    }

    manifest = {
        "app": "fengrid",
        "kind": "backup",
        "format": 2,                       # tar.gz restore package
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "label": label,
        "build": build,
        "system_settings": system_settings,
        "user_preferences": user_prefs,
        "configuration": configuration,
        "environment": environment,
        "files": [],                       # filled after hashing below
        "logs": [],
    }
    # checksums for every database payload we are about to write
    manifest["files"].append(_file_entry(snap_db, "library.db"))
    if registry_path and Path(registry_path).is_file():
        manifest["files"].append(_file_entry(
            Path(registry_path), "registry.db"))
    for p in extra_paths:
        pp = Path(p)
        if pp.is_file():
            manifest["files"].append(_file_entry(pp, f"extra/{pp.name}"))
    for lp in _collect_logs(logs_dir, data_dir):
        manifest["logs"].append({"name": lp["name"],
                                 "source": lp["source"],
                                 "bytes": lp["bytes"],
                                 "truncated": lp["truncated"]})
    return manifest


def _has_getpass() -> bool:
    try:
        import getpass
        getpass.getuser()
        return True
    except Exception:
        return False


def _file_entry(path: Path, name: str) -> dict:
    return {"name": name, "bytes": Path(path).stat().st_size,
            "sha256": _sha256(path)}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


LOG_TAIL_CAP = 128 * 1024


def _collect_logs(logs_dir, data_dir) -> list[dict]:
    """Candidate logs 'if present' (spec): app data dir + 0.x state dir.
    Each captured as a TAIL (last 128KB) under logs/ in the package."""
    candidates: list[Path] = []
    for base in (Path(logs_dir) if logs_dir else None,
                 Path(data_dir) if data_dir else None,
                 Path(os.environ.get("FENGRID_STATE_DIR",
                                     str(Path.home() /
                                         ".local/state/fengrid")))):
        if base is None or not base.is_dir():
            continue
        for pat in ("*.log", "logs/*.log"):
            candidates.extend(sorted(base.glob(pat)))
    out, seen = [], set()
    for c in candidates:
        try:
            if not c.is_file() or c.resolve() in seen:
                continue
            seen.add(c.resolve())
            size = c.stat().st_size
            with open(c, "rb") as fh:
                if size > LOG_TAIL_CAP:
                    fh.seek(size - LOG_TAIL_CAP)
                    data = b"... (tail) ...\n" + fh.read()
                    trunc = True
                else:
                    data = fh.read()
                    trunc = False
            if not data:
                continue
            tmp = c.parent / (f".fengrid-log-tmp-{os.getpid()}"
                              f"-{len(out)}")
            tmp.write_bytes(data)
            pkg_name = f"logs/{c.name}"
            if pkg_name in {o["name"] for o in out}:
                # two sources can share a basename — tar members must
                # stay unique or extraction silently drops one
                pkg_name = f"logs/{len(out)}-{c.parent.name}-{c.name}"
            out.append({"path": str(tmp), "tmp": str(tmp),
                        "name": pkg_name,
                        "source": str(c), "bytes": len(data),
                        "truncated": trunc})
        except OSError:
            continue
    return out


def _tar_add_bytes(tf: tarfile.TarFile, name: str, text: str,
                   mode: int = 0o644) -> None:
    data = text.encode("utf-8")
    ti = tarfile.TarInfo(name)
    ti.size = len(data)
    ti.mode = mode
    ti.mtime = int(time.time())
    tf.addfile(ti, io.BytesIO(data))


def _tar_add_file(tf: tarfile.TarFile, src: Path, name: str,
                  mode: int = 0o644) -> None:
    ti = tarfile.TarInfo(name)
    ti.size = Path(src).stat().st_size
    ti.mode = mode
    ti.mtime = int(time.time())
    with open(src, "rb") as fh:
        tf.addfile(ti, fh)


def _open_package(zip_path: str | Path):
    """Unified member reader for tar.gz packages AND legacy zip
    backups (pre-format-2). Returns (names, read_fn, close)."""
    p = Path(zip_path)
    if p.name.endswith(".zip"):
        zf = zipfile.ZipFile(p)
        return (zf.namelist(), lambda n: zf.read(n), zf.close)
    tf = tarfile.open(p, "r:*")
    names = tf.getnames()

    def read(n: str) -> bytes:
        f = tf.extractfile(n)
        if f is None:
            raise KeyError(n)
        return f.read()
    return (names, read, tf.close)


def list_backups(dest_dir: str | Path) -> list[dict]:
    out = []
    d = Path(dest_dir)
    if not d.is_dir():
        return []
    for p in sorted(list(d.glob("fengrid-backup-*.tar.gz"))
                    + list(d.glob("fengrid-backup-*.zip")),
                    reverse=True):
        try:
            names, read, close = _open_package(p)
            try:
                m = json.loads(read(MANIFEST_NAME).decode("utf-8"))
            finally:
                close()
        except Exception:
            m = {}
        out.append({"path": str(p), "name": p.name,
                    "bytes": p.stat().st_size,
                    "created": m.get("created", ""),
                    "label": m.get("label", "")})
    return out


def validate_backup(zip_path: str | Path) -> dict:
    try:
        names, read, close = _open_package(zip_path)
    except (tarfile.TarError, zipfile.BadZipFile, OSError) as e:
        raise BackupError(f"cannot open backup package: {e}")
    try:
        if MANIFEST_NAME not in names:
            raise BackupError("not a fengrid backup (no manifest)")
        if "library.db" not in names:
            raise BackupError("backup has no library.db")
        manifest = json.loads(read(MANIFEST_NAME).decode("utf-8"))
    finally:
        close()
    if manifest.get("kind") != "backup":
        raise BackupError("not a fengrid backup")
    return manifest


def restore(zip_path: str, target_db: str) -> dict:
    """Replace `target_db` with the package's library.db. The CURRENT db
    is preserved as `<target>.pre-restore` first (manual rollback) and
    the payload is quick_checked BEFORE the swap."""
    manifest = validate_backup(zip_path)
    target = Path(target_db)
    backup_of_current = None
    if target.exists():
        backup_of_current = target.with_suffix(target.suffix + ".pre-restore")
        shutil.copy2(target, backup_of_current)
    names, read, close = _open_package(zip_path)
    tmp = target.with_suffix(target.suffix + ".restoring")
    try:
        if "library.db" not in names:
            raise BackupError("backup has no library.db")
        with open(tmp, "wb") as fo:
            fo.write(read("library.db"))
    finally:
        close()
    try:
        probe = sqlite3.connect(str(tmp))
        try:
            ok = probe.execute("PRAGMA quick_check").fetchone()[0]
        finally:
            probe.close()
        if ok != "ok":
            raise BackupError(f"backup fails integrity check: {ok}")
        # optional checksum verification when the manifest recorded one
        for f in manifest.get("files", []):
            if f.get("name") == "library.db" and f.get("sha256"):
                if _sha256(tmp) != f["sha256"]:
                    raise BackupError("library.db checksum mismatch")
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)
    return {"restored": str(target), "manifest": manifest,
            "previous": str(backup_of_current) if backup_of_current
            else None}


def remove_backup(path: str | Path, backups_dir: str | Path) -> None:
    """Delete one backup — but only inside the backups dir (a path from
    the UI could be stale/hostile)."""
    p = Path(path).resolve()
    root = Path(backups_dir).resolve()
    if p.parent != root or not p.is_file():
        raise BackupError("refusing to delete outside the backups folder")
    if p.suffix not in (".gz", ".zip") and not p.name.endswith(".tar.gz"):
        raise BackupError("refusing to delete a non-backup file")
    p.unlink()


def generate_restore_scripts(manifest: dict) -> dict:
    """Platform restore scripts for the package (spec: same release tag
    as recorded, refuse on active installs/processes, copy settings +
    databases, handle permissions/usernames/OS, fail gracefully with
    numbered reasons).

    Exit codes (both platforms):
      2 = Fengrid is installed or running here
      3 = download of the recorded release tag failed
      4 = package/archive problem
      5 = copy or permissions failure
      6 = checksum verification failed
      7 = missing prerequisite (tool/env)
    """
    build = manifest.get("build", {})
    env = manifest.get("environment", {})
    tag = build.get("release_tag") or ""
    pre = 1 if build.get("prerelease") else 0
    sha = ""
    for f in manifest.get("files", []):
        if f.get("name") == "library.db":
            sha = f.get("sha256", "")
    created = manifest.get("created", "")
    version = build.get("app_version", "")
    url = (f"https://github.com/fengrid/fengrid/releases/download/"
           f"{tag}/fengrid-prod-linux-x64.tar.gz") if tag else ""
    ps_url = (f"https://github.com/fengrid/fengrid/releases/download/"
              f"{tag}/fengrid-prod-windows-x64.zip") if tag else ""

    sh = f"""#!/usr/bin/env bash
# fengrid restore (POSIX: Linux / macOS) — generated {created}
# backup of fengrid {version} (release tag {tag or 'UNKNOWN'})
# Source machine recorded: {env.get('os', 'unknown')}, user '{env.get('user', '?')}'
# The data directory below is recomputed for THIS machine/user.
set -euo pipefail

TAG="{tag}"
PRERELEASE={pre}
EXPECTED_SHA256="{sha}"
DOWNLOAD_URL="{url}"
HERE="$(cd "$(dirname "$0")" && pwd)"

# exit codes: 2 installed/running  3 download  4 archive
#             5 copy/permissions   6 verify   7 prerequisite
fail() {{ echo "fengrid-restore: ERROR [$2] $1" >&2; exit "$2"; }}
note() {{ echo "fengrid-restore: $1"; }}

case "$(uname -s)" in
    Darwin) DATA_DIR="${{HOME}}/Library/Application Support/fengrid" ;;
    Linux)  DATA_DIR="${{XDG_DATA_HOME:-$HOME/.local/share}}/fengrid" ;;
    *)      DATA_DIR="${{XDG_DATA_HOME:-$HOME/.local/share}}/fengrid" ;;
esac
APP_DIR="${{FENGRID_INSTALL_DIR:-$HOME/fengrid}}"

# 1) refuse to run where Fengrid is present or active
if command -v pgrep >/dev/null 2>&1; then
    if pgrep -f "fengrid" >/dev/null 2>&1 || pgrep -f "serve.py" >/dev/null 2>&1; then
        fail "a fengrid process/server appears to be RUNNING — this script must be run on a system where Fengrid is not active" 2
    fi
fi
for probe in "$APP_DIR" "$HOME/.local/bin/fengrid" "/usr/local/bin/fengrid" "$HOME/.cache/fengrid"; do
    if [ -e "$probe" ]; then
        fail "an existing Fengrid installation was found at $probe — this script must be run on a system where Fengrid is not installed or running (remove or rename it first if this machine IS the target)" 2
    fi
done

# 2) download the same release tag recorded in this backup
[ -n "$TAG" ] || fail "backup records no release tag — cannot download a matching build" 7
[ "$PRERELEASE" = "1" ] && note "warning: backup came from a pre-release build; tag $TAG may not exist yet"
command -v curl >/dev/null 2>&1 || fail "curl is required to download fengrid $TAG" 7
note "downloading fengrid $TAG ..."
TMP_TGZ="$(mktemp "${{TMPDIR:-/tmp}}/fengrid-app.XXXXXX").tar.gz"
trap 'rm -f "$TMP_TGZ"' EXIT
if ! curl -fL --retry 3 -o "$TMP_TGZ" "$DOWNLOAD_URL"; then
    fail "download failed for $DOWNLOAD_URL — check the network, or install release $TAG manually and copy the database into $DATA_DIR" 3
fi
tar -tzf "$TMP_TGZ" >/dev/null 2>&1 || fail "downloaded file is not a valid fengrid archive" 4

# 3) install the application
mkdir -p "$APP_DIR" || fail "cannot create $APP_DIR (permissions?)" 5
tar -xzf "$TMP_TGZ" -C "$APP_DIR" || fail "could not extract into $APP_DIR" 4

# 4) place databases + configuration (username-independent target paths)
[ -f "$HERE/../library.db" ] || fail "library.db missing from the backup package" 4
mkdir -p "$DATA_DIR" 2>/dev/null || fail "cannot create data directory $DATA_DIR — run as a user with write access (no auto-sudo by design)" 5
[ -w "$DATA_DIR" ] || fail "no write permission on $DATA_DIR" 5
if [ -f "$DATA_DIR/library.db" ]; then
    STAMP="$(date +%Y%m%d-%H%M%S)"
    mv "$DATA_DIR/library.db" "$DATA_DIR/library.db.pre-restore-$STAMP" \
        || fail "cannot move the existing database aside" 5
    [ -f "$DATA_DIR/registry.db" ] && \
        mv "$DATA_DIR/registry.db" "$DATA_DIR/registry.db.pre-restore-$STAMP" 2>/dev/null || true
    note "existing database kept as library.db.pre-restore-$STAMP"
fi
cp "$HERE/../library.db" "$DATA_DIR/library.db" || fail "could not copy the database to $DATA_DIR" 5
if [ -f "$HERE/../registry.db" ]; then
    cp "$HERE/../registry.db" "$DATA_DIR/registry.db" || fail "could not copy registry.db" 5
fi
if [ -d "$HERE/../extra" ]; then
    mkdir -p "$DATA_DIR" && cp -R "$HERE/../extra/." "$DATA_DIR/" \
        || note "warning: could not copy auxiliary files (continuing)"
fi
chmod 0644 "$DATA_DIR/library.db" 2>/dev/null || true

# 5) verify the restored database against the recorded checksum
if [ -n "$EXPECTED_SHA256" ]; then
    if command -v sha256sum >/dev/null 2>&1; then
        GOT="$(sha256sum "$DATA_DIR/library.db" | awk '{{print $1}}')"
    elif command -v shasum >/dev/null 2>&1; then
        GOT="$(shasum -a 256 "$DATA_DIR/library.db" | awk '{{print $1}}')"
    else
        GOT=""
        note "warning: no sha256 tool available — skipping checksum verification"
    fi
    if [ -n "$GOT" ] && [ "$GOT" != "$EXPECTED_SHA256" ]; then
        fail "database checksum mismatch (package corrupted during transfer)" 6
    fi
fi

note "restore complete."
note "  data : $DATA_DIR"
note "  app  : $APP_DIR (release $TAG)"
note "start fengrid from $APP_DIR and check Settings → Database → Integrity check."
exit 0
"""

    ps1 = f"""# fengrid restore (Windows PowerShell) — generated {created}
# backup of fengrid {version} (release tag {tag or 'UNKNOWN'})
# The data directory below is recomputed for THIS machine/user.
$ErrorActionPreference = 'Stop'
$Tag = '{tag}'
$Prerelease = {('1' if pre else 0)}
$ExpectedSha = '{sha}'
$DownloadUrl = '{ps_url}'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path

function Fail([string]$Msg, [int]$Code) {{
    Write-Error "fengrid-restore: ERROR [$Code] $Msg"
    exit $Code
}}
function Note([string]$Msg) {{ Write-Host "fengrid-restore: $Msg" }}

$DataDir = Join-Path $env:LOCALAPPDATA 'fengrid'
$AppDir  = if ($env:FENGRID_INSTALL_DIR) {{ $env:FENGRID_INSTALL_DIR }}
           else {{ Join-Path $HOME 'fengrid' }}

# 1) refuse to run where Fengrid is present or active
$procs = Get-Process -Name 'fengrid','python','pythonw' -ErrorAction SilentlyContinue |
    Where-Object {{ $_.Path -and $_.Path -like "*fengrid*" }}
if ($procs) {{ Fail "a fengrid process appears to be RUNNING — this script must be run on a system where Fengrid is not active" 2 }}
$server = Get-NetTCPConnection -LocalPort 8642 -State Listen -ErrorAction SilentlyContinue
if ($server) {{ Fail "a fengrid server is LISTENING on port 8642 — stop it first (script must run where Fengrid is not active)" 2 }}
foreach ($probe in @($AppDir, (Join-Path $env:LOCALAPPDATA 'fengrid'))) {{
    if (Test-Path (Join-Path $probe 'library.db')) {{
        Fail "an existing Fengrid installation/data was found at $probe — this script must be run on a system where Fengrid is not installed or running" 2
    }}
}}

# 2) download the same release tag recorded in this backup
if (-not $Tag) {{ Fail "backup records no release tag — cannot download a matching build" 7 }}
if ($Prerelease -eq 1) {{ Note "warning: backup came from a pre-release build; tag $Tag may not exist yet" }}
Note "downloading fengrid $Tag ..."
$Tmp = Join-Path $env:TEMP ("fengrid-app-" + [guid]::NewGuid().ToString() + '.zip')
try {{
    try {{
        Invoke-WebRequest -Uri $DownloadUrl -OutFile $Tmp -UseBasicParsing
    }} catch {{
        Fail "download failed for $DownloadUrl — check the network, or install release $Tag manually and copy the database into $DataDir" 3
    }}
    if (-not (Test-Path $Tmp)) {{ Fail "download produced no file" 3 }}

    # 3) install the application
    New-Item -ItemType Directory -Force -Path $AppDir | Out-Null
    try {{
        Expand-Archive -Path $Tmp -DestinationPath $AppDir -Force
    }} catch {{
        Fail "could not extract the application into $AppDir ($_)" 4
    }}

    # 4) place databases + configuration
    $PayloadDb = Join-Path (Split-Path -Parent $Here) 'library.db'
    if (-not (Test-Path $PayloadDb)) {{ Fail "library.db missing from the backup package" 4 }}
    New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
    $existing = Join-Path $DataDir 'library.db'
    if (Test-Path $existing) {{
        $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
        Move-Item $existing (Join-Path $DataDir "library.db.pre-restore-$stamp") -Force
        Note "existing database kept as library.db.pre-restore-$stamp"
    }}
    try {{
        Copy-Item $PayloadDb $existing -Force
        $regPayload = Join-Path (Split-Path -Parent $Here) 'registry.db'
        if (Test-Path $regPayload) {{
            Copy-Item $regPayload (Join-Path $DataDir 'registry.db') -Force
        }}
        $extra = Join-Path (Split-Path -Parent $Here) 'extra'
        if (Test-Path $extra) {{
            Copy-Item "$extra\\*" $DataDir -Recurse -Force
        }}
    }} catch {{
        Fail "could not copy database/settings to $DataDir ($_)" 5
    }}

    # 5) verify the restored database against the recorded checksum
    if ($ExpectedSha) {{
        try {{
            $got = (Get-FileHash -Algorithm SHA256 $existing).Hash.ToLower()
            if ($got -ne $ExpectedSha.ToLower()) {{
                Fail "database checksum mismatch (package corrupted during transfer)" 6
            }}
        }} catch {{
            Fail "could not verify the restored database ($_)" 6
        }}
    }}
}} finally {{
    if (Test-Path $Tmp) {{ Remove-Item $Tmp -Force -ErrorAction SilentlyContinue }}
}}

Note "restore complete."
Note "  data : $DataDir"
Note "  app  : $AppDir (release $Tag)"
Note "Start fengrid from $AppDir and check Settings -> Database -> Integrity check."
exit 0
"""
    return {"restore.sh": sh, "restore.ps1": ps1}


# ── database administration ──────────────────────────────────────────
def stats(con: sqlite3.Connection, db_path: str | Path) -> dict:
    size = Path(db_path).stat().st_size if Path(db_path).exists() else 0
    wal = Path(str(db_path) + "-wal")
    tables = []
    for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
            " AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'asset_fts%'"
            " ORDER BY name"):
        n = con.execute(f"SELECT COUNT(*) FROM \"{r[0]}\"").fetchone()[0]
        tables.append({"name": r[0], "rows": int(n)})
    return {"bytes": size, "wal_bytes": wal.stat().st_size
            if wal.exists() else 0,
            "tables": tables,
            "page_size": int(con.execute(
                "PRAGMA page_size").fetchone()[0])}


def quick_check(con: sqlite3.Connection) -> dict:
    rows = [r[0] for r in con.execute("PRAGMA quick_check")]
    return {"ok": rows == ["ok"], "lines": rows[:20]}


def vacuum(con: sqlite3.Connection) -> dict:
    before = None
    try:
        before = con.execute("PRAGMA page_count").fetchone()[0]
    except sqlite3.Error:
        pass
    con.execute("VACUUM")
    after = con.execute("PRAGMA page_count").fetchone()[0]
    return {"pages_before": before, "pages_after": after}


def checkpoint(con: sqlite3.Connection) -> dict:
    mode = con.execute("PRAGMA journal_mode").fetchone()[0]
    if str(mode).lower() != "wal":
        return {"mode": mode, "note": "checkpoint only applies to WAL"}
    row = con.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    return {"mode": mode, "busy": int(row[0]), "log_pages": int(row[1]),
            "checkpointed": int(row[2])}


def optimize(con: sqlite3.Connection) -> dict:
    con.execute("PRAGMA optimize")
    return {"ok": True}


def rebuild_fts(con: sqlite3.Connection) -> dict:
    """DROP + recreate the FTS index. It is EXTERNAL-CONTENT (reads the
    asset table live), so recreation is instant — no reindex pass, and
    the triggers (asset_fts_au/ad/ai) come back with the schema."""
    from .db import FTS_SCHEMA
    # triggers live ON `asset` but write into asset_fts — they must go
    # first, or SQLite keeps them and the next asset INSERT errors
    for trig in ("asset_fts_ai", "asset_fts_ad", "asset_fts_au"):
        con.execute(f"DROP TRIGGER IF EXISTS {trig}")
    con.execute("DROP TABLE IF EXISTS asset_fts")
    con.executescript(FTS_SCHEMA)
    con.commit()
    n = con.execute("SELECT COUNT(*) FROM asset").fetchone()[0]
    return {"assets": int(n), "ok": True}


def sweep_orphans(con: sqlite3.Connection) -> dict:
    """Delete taxonomy rows pointing at objects that no longer exist —
    classic post-crash debris. item_kind decides WHICH table an id must
    exist in (icon/font rows both live in `asset`). scan_state is
    DELIBERATELY untouched: fingerprints for vanished files are pruned
    by the scanner, and removing them here would re-identify everything.
    """
    checks = {
        "item_tag":
            "DELETE FROM item_tag WHERE"
            " (item_kind IN ('icon','font')"
            "  AND item_id NOT IN (SELECT id FROM asset))"
            " OR (item_kind='palette'"
            "  AND item_id NOT IN (SELECT id FROM palette))"
            " OR (item_kind='snippet'"
            "  AND item_id NOT IN (SELECT id FROM snippet))",
        "item_field_value":
            "DELETE FROM item_field_value WHERE"
            " (item_kind IN ('icon','font')"
            "  AND item_id NOT IN (SELECT id FROM asset))"
            " OR (item_kind='palette'"
            "  AND item_id NOT IN (SELECT id FROM palette))"
            " OR (item_kind='snippet'"
            "  AND item_id NOT IN (SELECT id FROM snippet))",
        "collection_ref":
            "DELETE FROM collection_ref WHERE"
            " (item_kind IN ('icon','font')"
            "  AND item_id NOT IN (SELECT id FROM asset))"
            " OR (item_kind='palette'"
            "  AND item_id NOT IN (SELECT id FROM palette))"
            " OR (item_kind='snippet'"
            "  AND item_id NOT IN (SELECT id FROM snippet))"
            " OR collection_id NOT IN (SELECT id FROM collection)",
        "asset_field_value":
            "DELETE FROM asset_field_value WHERE"
            " asset_id NOT IN (SELECT id FROM asset)",
        "project_asset":
            "DELETE FROM project_asset WHERE"
            " (asset_kind IN ('icon','font')"
            "  AND asset_id NOT IN (SELECT id FROM asset))"
            " OR (asset_kind='palette'"
            "  AND asset_id NOT IN (SELECT id FROM palette))"
            " OR (asset_kind='snippet'"
            "  AND asset_id NOT IN (SELECT id FROM snippet))"
            " OR project_id NOT IN (SELECT id FROM projects)",
    }
    counts = {}
    for name, sql in checks.items():
        cur = con.execute(sql)
        counts[name] = max(0, cur.rowcount or 0)
    con.commit()
    return counts
