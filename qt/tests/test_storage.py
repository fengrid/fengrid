"""Storage backends: command construction, availability, attach/detach
paths and mount persistence — all without root, network or FUSE.

The core functions take an injectable `runner` (tests feed canned
subprocess results); the bridge's 'local' attach short-circuits to an
existing directory, which is how the threaded attach flow is exercised
end to end (worker thread → signal → storage_mount row).
"""
import os
import subprocess
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fengrid.core import db, storage                  # noqa: E402


def _ok(cmd=None, **kw):
    return subprocess.CompletedProcess(cmd or [], 0, "", "")


def _fail(cmd=None, err="boom", **kw):
    return subprocess.CompletedProcess(cmd or [], 1, "", err)


def test_build_cmd_is_pure(tmp_path):
    mnt = tmp_path / "mnt"
    assert storage.build_cmd("sshfs", "u@h:/x", mnt)[:2] == ["sshfs", "u@h:/x"]
    assert storage.build_cmd("nfs", "srv:/exp", mnt)[:3] == \
        ["mount", "-t", "nfs"]
    assert storage.build_cmd("s3", "bucket/pfx", mnt)[0] == "s3fs"
    assert storage.build_cmd("smb", "smb://srv/share", mnt)[:2] == \
        ["gio", "mount"]


def test_availability_honesty():
    ok, status = storage.availability("local")
    assert ok and status == "ready"
    # every backend returns a usable status line either way
    for key in ("smb", "nfs", "sshfs", "s3"):
        ok, status = storage.availability(key)
        assert isinstance(ok, bool) and status
        if not ok:
            assert status.startswith("install ")   # actionable hint


def test_attach_local_short_circuits(tmp_path):
    d = tmp_path / "assets"
    d.mkdir()
    got = storage.attach("local", str(d), tmp_path)
    assert got == d.resolve()
    # an existing local path works for ANY backend (manual-mount route)
    got = storage.attach("sshfs", str(d), tmp_path)
    assert got == d.resolve()
    # unknown backend / missing dir are real errors
    try:
        storage.attach("smb", str(tmp_path / "nope-dir"), tmp_path)
        assert False, "should raise"
    except storage.StorageError:
        pass
    try:
        storage.attach("wat", "x", tmp_path)
        assert False, "should raise"
    except storage.StorageError:
        pass


def test_attach_runs_mount_command(tmp_path, monkeypatch):
    """Successful mount: the runner's command lands on the mountpoint
    dir and the returned path is the mountpoint."""
    calls = []

    def runner(cmd, timeout=45):
        calls.append(cmd)
        Path(cmd[2] if cmd[0] == "sshfs" else cmd[-1]).mkdir(
            parents=True, exist_ok=True)
        return _ok(cmd)

    monkeypatch.setattr(storage, "shutil",
                        type("S", (), {"which": staticmethod(
                            lambda t: "/usr/bin/" + t)})())
    p = storage.attach("sshfs", "u@host:/srv/x", tmp_path, runner=runner)
    assert calls and calls[0][0] == "sshfs"
    assert p == storage.mountpoint_for(tmp_path, "sshfs", "u@host:/srv/x")

    # failure surfaces the tool's stderr tail
    def fail_runner(cmd, timeout=45):
        return _fail(cmd, err="read: Connection refused")

    monkeypatch.setattr(storage, "shutil",
                        type("S", (), {"which": staticmethod(
                            lambda t: "/usr/bin/" + t)})())
    try:
        storage.attach("sshfs", "u@dead:/x", tmp_path, runner=fail_runner)
        assert False, "should raise"
    except storage.StorageError as e:
        assert "Connection refused" in str(e)


def test_detach_best_effort(tmp_path, monkeypatch):
    mnt = tmp_path / "mnt"
    mnt.mkdir()
    # not a mountpoint → no-op, no error, dir untouched
    storage.detach("sshfs", "u@h:/x", mnt, runner=_fail)
    assert mnt.is_dir()
    # missing path → no-op
    storage.detach("sshfs", "u@h:/x", tmp_path / "gone", runner=_fail)
    # local backend never unmounts
    storage.detach("local", str(mnt), mnt, runner=_fail)
    assert mnt.is_dir()


def test_mount_table_persists(tmp_path):
    con = db.connect(tmp_path / "t.db")
    bridge_path = str(tmp_path)
    from fengrid.bridges.storage import Storage

    assets = tmp_path / "nas"
    assets.mkdir()
    s = Storage(con, bridge_path)
    assert s.mounts == [] and s.mountCount == 0
    assert len(s.backends) == 5            # local + smb + nfs + sshfs + s3

    s._register("local", str(assets), str(assets), "folder")
    s._mounts = s._load()
    assert s.mountCount == 1
    row = s.mounts[0]
    assert row["backend"] == "local" and row["healthy"] is True
    assert row["backendLabel"] == "Local folder"

    # healthy() drives remount: a live local dir never remounts …
    stale = [m for m in s.mounts if not m["healthy"]]
    assert stale == []
    s._forget(row["id"], str(assets))
    s._mounts = s._load()          # _forget alone doesn't refresh —
    assert s.mountCount == 0       # _on_done does that in production
    con.close()


def test_bridge_attach_local_thread(tmp_path):
    """Full threaded attach: worker → done → attached signal → row."""
    from PySide6.QtGui import QGuiApplication
    from fengrid.bridges.storage import Storage

    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    con = db.connect(tmp_path / "t.db")
    assets = tmp_path / "cloudish"
    assets.mkdir()

    s = Storage(con, str(tmp_path))
    got = []
    s.attached.connect(lambda p, k: got.append((p, k)))

    s.attach("local", str(assets), "folder")
    deadline = time.time() + 5
    while time.time() < deadline and not (got and s.mountCount == 1):
        app.processEvents()
        time.sleep(0.02)
    assert got == [(str(assets.resolve()), "folder")], got
    assert s.mountCount == 1 and s.busy is False

    mid = s.mounts[0]["id"]
    s.detach(mid)
    deadline = time.time() + 5
    while time.time() < deadline and s.mountCount != 0:
        app.processEvents()
        time.sleep(0.02)
    assert s.mountCount == 0
    # let the worker's finished/deleteLater chain drain before exit
    # (otherwise the interpreter warns "QThread: Destroyed while …")
    for _ in range(10):
        app.processEvents()
        time.sleep(0.02)
    rows = con.execute("SELECT COUNT(*) c FROM storage_mount").fetchone()
    assert rows["c"] == 0
    con.close()