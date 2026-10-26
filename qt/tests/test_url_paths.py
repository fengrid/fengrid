"""Regression tests for file:// URL → local-path conversion (#41).

On Windows, FolderDialog/FileDialog hand over URLs like
``file:///D:/Library/Design Library/Icons/mynaui-icons``. The old
hand-rolled substring conversion sliced after ``file://`` and left
``/D:/Library/…`` — a path ``os.path.isdir`` can never match — so
selecting ANY folder in Settings or first-run setup failed with
``Not a folder: …``. Spaces were handled, but drive letters were not.

Fixed at three layers, all covered here:
1. ``core.paths.local_path`` — the Python converter (QUrl.toLocalFile),
   used by the receiver slots (library.add_folder, dataio.import/export,
   databases open/create).
2. ``Icons.toLocalPath`` — the QML singleton every dialog funnels
   through, exercised here through a REAL QmlEngine load (the JS logic
   runs even on this Linux host; QUrl's drive-letter handling is
   platform-independent).
3. Receiver hardening: a file:// URL passed straight to
   ``library.add_folder`` registers the source instead of erroring.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest                                    # noqa: E402
from PySide6.QtGui import QGuiApplication         # noqa: E402
from PySide6.QtCore import QUrl                   # noqa: E402

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from fengrid.core import db as core_db           # noqa: E402
from fengrid.core.paths import file_url, local_path  # noqa: E402

_APP = None


def _qapp():
    global _APP
    if _APP is None:
        _APP = QGuiApplication.instance() or QGuiApplication(sys.argv)
    return _APP


# ────────────────────────────────────────────── core.paths.local_path
def test_posix_url():
    assert local_path("file:///home/nat/My%20Icons") == "/home/nat/My Icons"


def test_windows_drive_url():
    """THE #41 case: file:///D:/… must NOT keep a leading slash."""
    assert local_path(
        "file:///D:/Library/Design%20Library/Icons/mynaui-icons"
    ) == "D:/Library/Design Library/Icons/mynaui-icons"


def test_windows_drive_url_root():
    assert local_path("file:///C:/") == "C:/"


def test_unc_url():
    assert local_path(
        "file://server/share/icons/devicon") == "//server/share/icons/devicon"


def test_hash_in_path_survives():
    """%23 (encoded '#') must decode, not truncate the URL fragment."""
    assert local_path("file:///tmp/ic%23ons/x.svg") == "/tmp/ic#ons/x.svg"


def test_plain_paths_pass_through():
    assert local_path("/home/nat/Icons") == "/home/nat/Icons"
    assert local_path("D:/Library/Icons") == "D:/Library/Icons"
    assert local_path(r"D:\Library\Design Library\Icons") == \
        r"D:\Library\Design Library\Icons"


def test_file_url_roundtrip():
    p = "/tmp/fengrid Design Library"
    assert local_path(file_url(p)) == p


# ───────────────────────────────────── library.add_folder with a URL
@pytest.fixture()
def library_env(tmp_path):
    _qapp()
    from fengrid.bridges.library import Library

    con = core_db.connect(tmp_path / "t.db")
    # the scanned folder — a REAL dir whose name contains a space,
    # mirroring "D:\Library\Design Library\Icons\mynaui-icons"
    folder = tmp_path / "Design Library" / "Icons" / "mynaui-icons"
    folder.mkdir(parents=True)
    (folder / "home.svg").write_text(
        "<svg xmlns='http://www.w3.org/2000/svg'/>")
    lib = Library(con, str(tmp_path / "t.db"), no_scan=True)
    msgs = []
    lib.message.connect(msgs.append)
    return {"lib": lib, "con": con, "folder": folder, "msgs": msgs}


def test_add_folder_accepts_file_url(library_env):
    """Dialogs hand over URLs; the receiver must convert, not error."""
    env = library_env
    url = QUrl.fromLocalFile(str(env["folder"])).toString()
    env["lib"].add_folder(url, "folder")
    assert not any(m.startswith("Not a folder") for m in env["msgs"]), \
        env["msgs"]
    assert any(m.startswith("Added folder") for m in env["msgs"]), env["msgs"]
    row = env["con"].execute(
        "SELECT path FROM source WHERE kind = 'folder'").fetchone()
    assert row is not None
    assert Path(row[0]) == env["folder"]


def test_add_folder_accepts_windows_style_url(library_env):
    """A Windows drive-letter URL (the exact #41 shape) converts too."""
    env = library_env
    # build the URL the way Windows FolderDialog does: drive in the path
    url = "file:///" + str(env["folder"]).lstrip("/").replace("\\", "/")
    env["lib"].add_folder(url, "folder")
    assert not any(m.startswith("Not a folder") for m in env["msgs"])
    row = env["con"].execute(
        "SELECT path FROM source WHERE kind = 'folder'").fetchone()
    assert row is not None
    assert Path(row[0]) == env["folder"]


def test_add_folder_plain_path_with_space(library_env):
    """The issue's explicit ask: plain paths with spaces keep working."""
    env = library_env
    env["lib"].add_folder(str(env["folder"]), "folder")
    assert any(m.startswith("Added folder") for m in env["msgs"])
    row = env["con"].execute(
        "SELECT path FROM source WHERE kind = 'folder'").fetchone()
    assert row is not None
    assert Path(row[0]) == env["folder"]


def test_add_folder_still_rejects_missing_dirs(library_env):
    env = library_env
    env["lib"].add_folder(str(env["folder"] / "nope"), "folder")
    assert any(m.startswith("Not a folder") for m in env["msgs"])


# ─────────────────────────────── QML: Icons.toLocalPath (the singleton)
_QML_PROBE = """import QtQuick
import \"{QMCDIR}\"
QtObject {
    function conv(u) { return Icons.toLocalPath(u) }
    function furl(p) { return Icons.fileUrl(p) }
}
"""


@pytest.fixture()
def qml_conv(tmp_path):
    _qapp()
    from PySide6.QtCore import QUrl as Q
    from PySide6.QtQml import QQmlComponent, QQmlEngine

    comps = Path(__file__).resolve().parents[1] / "qml" / "components"
    probe = tmp_path / "probe.qml"
    # directory imports must be RELATIVE to the probe file
    probe.write_text(_QML_PROBE.replace(
        "{QMCDIR}", os.path.relpath(comps, tmp_path)))
    engine = QQmlEngine()
    comp = QQmlComponent(engine, Q.fromLocalFile(str(probe)))
    root = comp.create()
    assert root is not None, [str(e) for e in comp.errors()]
    yield root
    del root, engine


def test_qml_toLocalPath_windows_drive(qml_conv):
    """The exact URL shape Windows FolderDialog produces for the
    reporter's path — must come back as a drive path, no leading slash."""
    assert qml_conv.conv(
        "file:///D:/Library/Design Library/Icons/mynaui-icons"
    ) == "D:/Library/Design Library/Icons/mynaui-icons"


def test_qml_toLocalPath_percent_encoded(qml_conv):
    assert qml_conv.conv(
        "file:///D:/Library/Design%20Library/Icons/mynaui-icons"
    ) == "D:/Library/Design Library/Icons/mynaui-icons"
    assert qml_conv.conv(
        "file:///home/nat/ic%23ons/My%20Pack") == "/home/nat/ic#ons/My Pack"


def test_qml_toLocalPath_posix_and_plain(qml_conv):
    assert qml_conv.conv("file:///home/nat/Icons") == "/home/nat/Icons"
    assert qml_conv.conv("/home/nat/Icons") == "/home/nat/Icons"
    assert qml_conv.conv("D:\\Library\\Icons") == "D:\\Library\\Icons"


def test_qml_toLocalPath_unc(qml_conv):
    assert qml_conv.conv(
        "file://server/share/icons") == "//server/share/icons"


def test_qml_fileUrl_windows_drive(qml_conv):
    """Windows paths need the THIRD slash: file://D:/… parses 'D:' as a
    URL host and the Image source never loads. Spaces must survive."""
    assert qml_conv.furl(
        "D:/Library/Design Library/Icons") == \
        "file:///D:/Library/Design%20Library/Icons"
    assert qml_conv.furl(
        "D:\\Library\\Design Library\\Icons") == \
        "file:///D:/Library/Design%20Library/Icons"


def test_qml_fileUrl_posix_and_hash(qml_conv):
    assert qml_conv.furl("/home/nat/My Icons") == \
        "file:///home/nat/My%20Icons"
    assert qml_conv.furl("/tmp/ic#ons") == "file:///tmp/ic%23ons"


def test_qml_fileUrl_unc(qml_conv):
    assert qml_conv.furl("//server/share/icons") == \
        "file://server/share/icons"
