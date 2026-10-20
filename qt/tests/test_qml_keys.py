"""Interaction tests for the Code pane IDE command layer (emacs + vim).

Drives REAL key events through QtTest into the actual Code.qml editor
(offscreen platform) and asserts text, cursor, selection and mode outcomes,
including a :w save round-trip through the Code bridge into SQLite.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt, QUrl
from PySide6.QtGui import QGuiApplication, QKeyEvent
from PySide6.QtQml import QQmlComponent, QQmlContext, QQmlEngine
from PySide6.QtQuick import QQuickWindow

QML_DIR = Path(__file__).resolve().parents[1] / "qml"
SRC = Path(__file__).resolve().parents[1] / "src"
FONTS = Path(__file__).resolve().parents[2] / "fonts"
sys.path.insert(0, str(SRC))

_APP = None


def _qapp():
    global _APP
    if _APP is None:
        _APP = QGuiApplication.instance() or QGuiApplication(sys.argv)
    return _APP


def _find_textarea(root):
    stack = [root]
    while stack:
        o = stack.pop()
        if "TextArea" in o.metaObject().className():
            return o
        stack.extend(o.childItems())
    return None


@pytest.fixture()
def editor(tmp_path):
    _qapp()
    from fengrid.bridges.code import Code
    from fengrid.bridges.theme import Theme
    from fengrid.core import db as core_db

    con = core_db.connect(tmp_path / "t.db")
    theme = Theme(con, str(FONTS))
    bridge = Code(con)

    engine = QQmlEngine()
    # context properties go on the ENGINE ROOT context (as __main__ does) —
    # a child QQmlContext left `theme` null inside the directory-imported
    # components
    engine.rootContext().setContextProperty("theme", theme)
    engine.rootContext().setContextProperty("code", bridge)
    engine.rootContext().setContextProperty("previewProfile", None)
    comp = QQmlComponent(
        engine, QUrl.fromLocalFile(str(QML_DIR / "components" / "Code.qml")))
    root = comp.create(engine.rootContext())
    assert root is not None, comp.errors()
    root.setWidth(1000)
    root.setHeight(700)

    win = QQuickWindow()
    root.setParentItem(win.contentItem())
    win.show()
    _qapp().processEvents()

    ta = _find_textarea(root)
    assert ta is not None, "editor TextArea not found"
    ta.forceActiveFocus()
    _qapp().processEvents()

    yield {"root": root, "ta": ta, "win": win, "bridge": bridge, "con": con}

    # teardown in the proven order: kill the window and engine while the
    # bridges are still referenced, so live bindings never log TypeErrors
    win.close()
    root.setParentItem(None)
    engine.collectGarbage()
    del engine
    import gc
    gc.collect()


def _press(win, key, mods, text):
    # QTest.keyClicks/keyClick require QWidgets; for QML items the same
    # events go straight to the QWindow, which routes them to the focused
    # item (this is what QTest does internally for QWindow targets)
    for typ in (QEvent.KeyPress, QEvent.KeyRelease):
        QCoreApplication.sendEvent(
            win, QKeyEvent(typ, int(key), mods, text))
    _qapp().processEvents()


def _type(ed, text):
    # printable ASCII ord() == Qt.Key (A=0x41…), text carries the case;
    # "\n" must go as Qt.Key_Return (0x01000004) — ASCII 10 is NOT the
    # Return key and TextArea ignores it
    for ch in text:
        if ch == "\n":
            _press(ed["win"], int(Qt.Key_Return),
                   Qt.KeyboardModifier.NoModifier, "\n")
        else:
            _press(ed["win"], ord(ch), Qt.KeyboardModifier.NoModifier, ch)
    _qapp().processEvents()


def _key(ed, key, mods=Qt.KeyboardModifier.NoModifier, text=None):
    # the vim layer matches on event.text — derive it from the key when not
    # given explicitly (unshifted letters lowercase, like a real keyboard)
    if text is None:
        k = int(key)
        text = chr(k) if 0x21 <= k <= 0x7E else ""
        if not (mods & Qt.ShiftModifier):
            text = text.lower()
    _press(ed["win"], int(key), mods, text)


def _vim(ed):
    # toggle via the QML method. Driving Ctrl+Alt+V as a synthetic event
    # would fire BOTH consumers (the pane Shortcut does not consume
    # sendEvent-delivered keys the way it consumes real input events), so
    # the toggle would run twice — real user input only ever hits one.
    from PySide6.QtCore import QMetaObject
    ok = QMetaObject.invokeMethod(ed["root"], "toggleVim")
    assert ok, "toggleVim not invokable"
    _qapp().processEvents()


def _html(root):
    v = root.property("editors")
    d = v.toVariant() if hasattr(v, "toVariant") else v
    return d["html"]


def test_plain_typing_and_emacs(editor):
    ed = editor
    ta, root, bridge = ed["ta"], ed["root"], ed["bridge"]
    bridge.set_keymap("emacs")       # this test exercises the emacs layer
    _type(ed, "hello brave world")
    assert _html(root) == "hello brave world"
    assert ta.property("cursorPosition") == 17

    _key(ed, Qt.Key_A, Qt.ControlModifier)
    assert ta.property("cursorPosition") == 0        # line home
    _key(ed, Qt.Key_E, Qt.ControlModifier)
    assert ta.property("cursorPosition") == 17       # line end
    _key(ed, Qt.Key_B, Qt.AltModifier)
    assert ta.property("cursorPosition") == 12       # word back → "world"
    _key(ed, Qt.Key_F, Qt.AltModifier)
    assert ta.property("cursorPosition") == 17       # word forward → end
    _key(ed, Qt.Key_B, Qt.AltModifier)               # back to 12
    _key(ed, Qt.Key_K, Qt.ControlModifier)           # kill to line end
    assert _html(root) == "hello brave "
    _key(ed, Qt.Key_Y, Qt.ControlModifier)           # yank it back
    assert _html(root) == "hello brave world"
    _key(ed, Qt.Key_B, Qt.AltModifier)               # back to "world"
    _key(ed, Qt.Key_D, Qt.ControlModifier)           # delete char
    assert _html(root) == "hello brave orld"


def test_vim_motions_and_operators(editor):
    ed = editor
    ta, root = ed["ta"], ed["root"]
    _type(ed, "alpha beta gamma")
    _vim(ed)
    assert root.property("vimEnabled") is True
    assert root.property("vimMode") == "normal"

    # b b from the end → start of "beta"
    _key(ed, Qt.Key_B)
    _key(ed, Qt.Key_B)
    assert ta.property("cursorPosition") == 6

    # d w → delete one word forward
    _key(ed, Qt.Key_D)
    _key(ed, Qt.Key_W)
    assert _html(root) == "alpha gamma"

    # x deletes the char under the cursor (still at 6 → the "g"), u undoes
    _key(ed, Qt.Key_X)
    assert _html(root) == "alpha amma"
    _key(ed, Qt.Key_U)
    assert _html(root) == "alpha gamma"

    # gg → 0, G → end
    _key(ed, Qt.Key_G)
    assert root.property("pendingG") is True
    _key(ed, Qt.Key_G)
    assert ta.property("cursorPosition") == 0
    _press(ed["win"], ord("G"), Qt.ShiftModifier, "G")       # G
    assert ta.property("cursorPosition") == len("alpha gamma")

    # G left the cursor at doc end — come back before inserting
    _key(ed, Qt.Key_G)
    _key(ed, Qt.Key_G)
    assert ta.property("cursorPosition") == 0

    # i … typing … Esc (cursor steps back into normal mode)
    _key(ed, Qt.Key_I)
    assert root.property("vimMode") == "insert"
    _type(ed, "Z")
    assert _html(root) == "Zalpha gamma"
    _key(ed, Qt.Key_Escape)
    assert root.property("vimMode") == "normal"
    assert ta.property("cursorPosition") == 0        # stepped back off the Z


def test_vim_dd_and_paste(editor):
    ed = editor
    ta, root = ed["ta"], ed["root"]
    _type(ed, "one\ntwo\nthree")
    _vim(ed)

    # gg, d d → first line deleted
    _key(ed, Qt.Key_G)
    _key(ed, Qt.Key_G)
    _key(ed, Qt.Key_D)
    _key(ed, Qt.Key_D)
    assert _html(root) == "two\nthree"

    # p pastes the killed LINE below the CURRENT line ("two")
    _key(ed, Qt.Key_P)
    assert _html(root) == "two\none\nthree"


def test_visual_selection_and_yank(editor):
    ed = editor
    ta, root = ed["ta"], ed["root"]
    _type(ed, "keep drop")
    _vim(ed)
    _key(ed, Qt.Key_0)                               # line start
    _key(ed, Qt.Key_V)                               # visual
    assert root.property("vimMode") == "visual"
    _key(ed, Qt.Key_W)                               # select "keep "
    assert ta.property("selectionStart") != ta.property("selectionEnd")
    _key(ed, Qt.Key_Y)                               # yank → back to normal
    assert root.property("vimMode") == "normal"
    assert ta.property("cursorPosition") == 0


def test_vim_ex_save(editor):
    ed = editor
    ta, root, bridge = ed["ta"], ed["root"], ed["bridge"]
    _type(ed, "save me")
    _vim(ed)
    _key(ed, Qt.Key_Colon)                           # ':'
    assert root.property("pendingOp") == ":"
    _key(ed, Qt.Key_W)                               # ':w' → saveSnippet
    assert root.property("pendingOp") == ""
    assert bridge.snippetCount >= 1                  # row landed in SQLite
    # an unknown ex command just cancels
    _key(ed, Qt.Key_Colon)
    _key(ed, Qt.Key_Q)
    assert root.property("pendingOp") == ""


def test_pending_state_transitions(editor):
    ed = editor
    root = ed["root"]
    _type(ed, "word")
    _vim(ed)
    _key(ed, Qt.Key_D)
    assert root.property("pendingOp") == "d"
    _key(ed, Qt.Key_Escape)
    assert root.property("pendingOp") == ""
    _key(ed, Qt.Key_I)
    assert root.property("vimMode") == "insert"


# ------------------------------------------------------- keybinding schemes

def test_default_keymap_is_vscode(editor):
    ed = editor
    ta, root, bridge = ed["ta"], ed["root"], ed["bridge"]
    assert root.property("keymap") == "vscode"
    assert root.property("vimEnabled") is False
    _type(ed, "hello")
    # vscode: Ctrl+A is SELECT ALL, not emacs line-home
    _key(ed, Qt.Key_A, Qt.ControlModifier)
    assert ta.property("selectionStart") != ta.property("selectionEnd")


def test_emacs_keymap_line_home(editor):
    ed = editor
    ta, root, bridge = ed["ta"], ed["root"], ed["bridge"]
    bridge.set_keymap("emacs")
    assert root.property("keymap") == "emacs"
    _type(ed, "hello")
    _key(ed, Qt.Key_A, Qt.ControlModifier)
    assert ta.property("cursorPosition") == 0      # line home
    assert ta.property("selectionStart") == ta.property("selectionEnd")
    # switching back to vscode disables the emacs bindings
    bridge.set_keymap("vscode")
    _key(ed, Qt.Key_E, Qt.ControlModifier)
    assert ta.property("cursorPosition") == 0      # select-all, not line end


def test_readline_kill_to_start_and_word(editor):
    ed = editor
    ta, root, bridge = ed["ta"], ed["root"], ed["bridge"]
    bridge.set_keymap("readline")
    _type(ed, "keep drop this")
    _key(ed, Qt.Key_U, Qt.ControlModifier)         # kill to line start
    assert _html(root) == ""
    _key(ed, Qt.Key_Y, Qt.ControlModifier)         # yank it back
    assert _html(root) == "keep drop this"
    _key(ed, Qt.Key_W, Qt.ControlModifier)         # kill word backward
    assert _html(root) == "keep drop "


def test_vim_keymap_starts_in_vim(editor):
    ed = editor
    ta, root, bridge = ed["ta"], ed["root"], ed["bridge"]
    _type(ed, "alpha beta")
    bridge.set_keymap("vim")
    assert root.property("vimEnabled") is True
    assert root.property("vimMode") == "normal"
    _key(ed, Qt.Key_B)
    _key(ed, Qt.Key_B)               # onto the first word (cursor was at end)
    _key(ed, Qt.Key_D)
    _key(ed, Qt.Key_W)
    assert _html(root) == "beta"
    # leaving the scheme drops out of vim mode
    bridge.set_keymap("vscode")
    assert root.property("vimEnabled") is False
    # bad schemes are ignored
    bridge.set_keymap("joe")
    assert root.property("keymap") == "vscode"
    assert bridge.keymap == "vscode"


def test_keymap_persists(editor):
    ed = editor
    bridge, con = ed["bridge"], ed["con"]
    bridge.set_keymap("readline")
    from fengrid.core import settings
    assert settings.get(con, "editor_keymap") == "readline"


def test_shift_tab_dedents(editor):
    ed = editor
    ta, root = ed["ta"], ed["root"]
    _type(ed, "    indented\nplain")
    ta.setProperty("cursorPosition", 0)
    _key(ed, Qt.Key_Backtab)
    assert _html(root) == "  indented\nplain"
    _key(ed, Qt.Key_Backtab)
    assert _html(root) == "indented\nplain"
