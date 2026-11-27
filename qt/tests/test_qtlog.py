"""qtlog: terminal-noise filter for Qt SVG duplicate-id warnings."""
import types

import pytest
from PySide6 import QtCore, QtGui

from fengrid import qtlog


@pytest.fixture(autouse=True)
def fresh_install():
    qtlog._installed = False
    yield
    qtlog._installed = False
    QtCore.qInstallMessageHandler(None)


def _dup_svg(tmp_path) -> str:
    p = tmp_path / "dup.svg"
    p.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32">'
        '<defs>'
        '<linearGradient id="paint0_linear"><stop offset="0"'
        ' stop-color="#f00"/></linearGradient>'
        '<linearGradient id="paint0_linear"><stop offset="0"'
        ' stop-color="#0f0"/></linearGradient>'
        '</defs>'
        '<rect width="32" height="32" fill="url(#paint0_linear)"/>'
        '</svg>')
    return str(p)


def test_real_svg_flood_is_filtered_but_other_warnings_pass(
        tmp_path, capsys):
    """The reported spam disappears (both Qt render paths) while an
    unrelated warning still reaches stderr — no over-filtering."""
    qtlog.install()

    from PySide6.QtSvg import QSvgRenderer
    img = QtGui.QImage(_dup_svg(tmp_path))
    assert not img.isNull(), "svg must still render fine"
    assert QSvgRenderer(_dup_svg(tmp_path)).isValid()

    QtCore.qWarning("an-unrelated-qt-warning")
    err = capsys.readouterr().err
    assert "Duplicate unique style id" not in err, err
    assert "an-unrelated-qt-warning" in err, err


def test_emits_default_format_for_other_categories(capsys):
    qtlog.install()
    qtlog._handler(QtCore.QtMsgType.QtWarningMsg,
                   types.SimpleNamespace(category="qt.svg"),
                   "could not parse something")
    qtlog._handler(QtCore.QtMsgType.QtWarningMsg,
                   types.SimpleNamespace(category="default"),
                   "plain warning")
    err = capsys.readouterr().err
    assert 'qt.svg: could not parse something' in err
    assert "default: plain warning" not in err      # default = no prefix
    assert "plain warning" in err


def test_suppression_is_warning_only_and_scoped(capsys):
    qtlog.install()
    ctx = types.SimpleNamespace(category="qt.svg")
    # same text at a higher severity is NOT dropped
    qtlog._handler(QtCore.QtMsgType.QtCriticalMsg, ctx,
                   'Duplicate unique style id: "x"')
    # same text in another category is NOT dropped
    qtlog._handler(QtCore.QtMsgType.QtWarningMsg,
                   types.SimpleNamespace(category="qt.qml"),
                   'Duplicate unique style id: "x"')
    # a different qt.svg warning is NOT dropped (real failures stay)
    qtlog._handler(QtCore.QtMsgType.QtWarningMsg, ctx,
                   "some other svg problem")
    err = capsys.readouterr().err
    # BOTH non-suppressed copies survive (critical at qt.svg, warning
    # at qt.qml); only the plain qt.svg WARNING would have been dropped
    assert err.count("Duplicate unique style id") == 2, err
    assert 'qt.svg: Duplicate unique style id: "x"' in err
    assert 'qt.qml: Duplicate unique style id: "x"' in err
    assert "some other svg problem" in err


def test_debug_env_passthrough(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("FENGRID_DEBUG_QT_SVG", "1")
    qtlog.install()
    from PySide6.QtSvg import QSvgRenderer
    QSvgRenderer(_dup_svg(tmp_path))
    assert "Duplicate unique style id" in capsys.readouterr().err


def test_install_is_idempotent():
    qtlog._installed = False
    assert qtlog.install() is True
    assert qtlog.install() is False


def test_unresolved_property_third_party_dropped_but_ours_reports(capsys):
    """#138: 'Could not resolve property' floods from third-party icon
    themes (/usr/share/icons/...) are dropped; the same defect in OUR
    resources (path carries a fengrid segment) still reports."""
    ctx = types.SimpleNamespace(category="qt.svg")
    qtlog._installed = True  # exercise _handler directly, no install
    qtlog._handler(QtCore.QtMsgType.QtWarningMsg, ctx,
                   "/usr/share/icons/Humanity/devices/48/camera-photo.svg"
                   ":194:6: Could not resolve property: #linearGradient9800")
    qtlog._handler(QtCore.QtMsgType.QtWarningMsg, ctx,
                   "/home/me/projects/fengrid/qt/resources/icons/x.svg"
                   ":3:1: Could not resolve property: #missingref")
    # non-warning severity is never dropped
    qtlog._handler(QtCore.QtMsgType.QtCriticalMsg, ctx,
                   "/usr/share/icons/bad.svg:1:1:"
                   " Could not resolve property: #x")
    err = capsys.readouterr().err
    assert "camera-photo.svg" not in err, err
    assert "fengrid/qt/resources/icons/x.svg" in err, err
    assert "bad.svg" in err, err
