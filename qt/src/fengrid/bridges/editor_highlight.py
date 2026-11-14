"""Real syntax highlighting for the Snippets editor.

Replaces the fragile transparent-TextArea + styled-Text-overlay pattern:
the overlay had to replicate the TextArea's layout pixel-perfectly, and
any divergence showed up as a cursor that didn't line up and selection
rendered as a misplaced/doubled chip. A QSyntaxHighlighter attached to
the TextArea's own QTextDocument formats the SAME layout the cursor and
selection live in, so alignment is correct by construction. It also
rehighlights incrementally per block instead of rebuilding the whole
document string on every keystroke.

QML usage:
    Component.onCompleted: snipHl.attach(edTa.textDocument, currentPane)
    onCurrentPaneChanged:  snipHl.set_language(currentPane)
    on theme change:       snipHl.set_colors({...})   // tkColors map

Token classes (mirrors the 0.x .tk-* roles the old overlay used):
  t tags · k keywords · a attributes/props · s strings · c comments
  n numbers · f selectors/functions
"""
from __future__ import annotations

import re

from PySide6.QtCore import QObject, Slot
from PySide6.QtGui import (QColor, QSyntaxHighlighter, QTextCharFormat,
                           QTextDocument)
from PySide6.QtQuick import QQuickTextDocument

# states for multi-line constructs (block state 0 = plain)
_IN_COMMENT = 1

# compiled rule sets: (pattern, token class); order = priority, a span
# consumed by an earlier rule is never reformatted by a later one
_RULES: dict[str, list[tuple[re.Pattern, str]]] = {
    "html": [
        (re.compile(r"<!--.*?-->", re.S), "c"),
        (re.compile(r"<!DOCTYPE[^>]*>", re.I), "k"),
        (re.compile(r"</?[\w-]+"), "t"),
        (re.compile(r"[\w-]+(?==)"), "a"),
        (re.compile(r'"[^"]*"|\'[^\']*\''), "s"),
    ],
    "css": [
        (re.compile(r"/\*.*?\*/", re.S), "c"),
        (re.compile(r"@[\w-]+"), "k"),
        (re.compile(r"[.#][\w-]+(?=[\s,{:.])"), "f"),
        (re.compile(r":{1,2}[\w-]+(?=[\s,{)])"), "f"),
        (re.compile(r"\b[\w-]+(?=\()"), "f"),
        (re.compile(r"[\w-]+(?=\s*:)"), "a"),
        (re.compile(r"#[0-9a-fA-F]{3,8}\b|\b\d+\.?\d*(?:px|em|rem|%|vh|vw|s|ms|deg|fr)?\b"), "n"),
    ],
    "js": [
        (re.compile(r"//[^\n]*"), "c"),
        (re.compile(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|`(?:[^`\\]|\\.)*`', re.S), "s"),
        (re.compile(r"\b(var|let|const|function|return|if|else|for|while|do|switch|"
                    r"case|break|continue|new|this|typeof|instanceof|null|undefined|"
                    r"true|false|class|extends|import|export|from|async|await|try|"
                    r"catch|finally|throw|delete|in|of)\b"), "k"),
        (re.compile(r"\b[\w$]+(?=\s*\()"), "f"),
        (re.compile(r"\b\d+\.?\d*\b"), "n"),
    ],
}

# multi-line comment opener/closer per language (rules above cover the
# same-line case; this pair carries state ACROSS blocks)
_BLOCK_COMMENT = {
    "html": ("<!--", "-->"),
    "css": ("/*", "*/"),
    "js": ("/*", "*/"),
}


def _fmt(color: str) -> QTextCharFormat:
    f = QTextCharFormat()
    f.setForeground(QColor(color))
    return f


class _Highlighter(QSyntaxHighlighter):
    """Per-language highlighter with cross-line comment state."""

    def __init__(self, doc: QTextDocument, parent: QObject):
        super().__init__(doc)
        self._lang = "html"
        self._colors: dict[str, str] = {}
        self._formats: dict[str, QTextCharFormat] = {}
        self.setParent(parent)

    # ------------------------------------------------------------ config
    def set_language(self, lang: str) -> None:
        self._lang = lang if lang in _RULES else "js"
        self.rehighlight()

    def set_colors(self, colors: dict) -> None:
        self._colors = dict(colors or {})
        self._formats = {k: _fmt(v) for k, v in self._colors.items()}
        self.rehighlight()

    def _format_for(self, cls: str) -> QTextCharFormat | None:
        return self._formats.get(cls)

    # --------------------------------------------------------- highlighting
    def highlightBlock(self, text: str) -> None:  # noqa: N802 (Qt name)
        rules = _RULES.get(self._lang, _RULES["js"])
        opener, closer = _BLOCK_COMMENT.get(
            self._lang, ("/*", "*/"))
        comment_fmt = self._format_for("c")
        consumed: list[tuple[int, int]] = []

        start = 0
        state = self.previousBlockState()

        # carry a multi-line comment from the previous block
        if state == _IN_COMMENT and comment_fmt is not None:
            end = text.find(closer)
            if end == -1:
                self.setFormat(0, len(text), comment_fmt)
                self.setCurrentBlockState(_IN_COMMENT)
                return
            length = end + len(closer)
            self.setFormat(0, length, comment_fmt)
            consumed.append((0, length))
            start = length
            state = 0
        self.setCurrentBlockState(0)

        # a comment OPENING in this block (after prior content): if it
        # never closes, everything to the end of the block is commented
        open_at = text.find(opener, start)
        if open_at != -1:
            close_at = text.find(closer, open_at + len(opener))
            if comment_fmt is not None:
                if close_at == -1:
                    self.setFormat(open_at, len(text) - open_at,
                                   comment_fmt)
                    consumed.append((open_at, len(text)))
                    self.setCurrentBlockState(_IN_COMMENT)
                else:
                    span_end = close_at + len(closer)
                    self.setFormat(open_at, span_end - open_at,
                                   comment_fmt)
                    consumed.append((open_at, span_end))
                    # content AFTER a closed comment is still lexable
                    self._apply_rules(rules, text[span_end:],
                                      span_start=span_end, consumed=consumed)
                    return
            elif close_at == -1:
                self.setCurrentBlockState(_IN_COMMENT)
                return

        self._apply_rules(rules, text, span_start=0, consumed=consumed)

    def _apply_rules(self, rules, text: str, *, span_start: int,
                     consumed: list[tuple[int, int]]) -> None:
        for pattern, cls in rules:
            fmt = self._format_for(cls)
            if fmt is None:
                continue
            for m in pattern.finditer(text):
                a, b = m.span()
                if b <= a:
                    continue
                abs_a, abs_b = span_start + a, span_start + b
                if any(abs_a < e and abs_b > s for s, e in consumed):
                    continue            # already claimed by a higher rule
                self.setFormat(abs_a, abs_b - abs_a, fmt)
                consumed.append((abs_a, abs_b))


class EditorHighlighter(QObject):
    """QML-facing handle: attach a TextArea's textDocument and keep the
    language/colors in sync. The heavy lifting is _Highlighter.

    Colors come from the theme bridge directly (tkColors mapping): QML
    JS objects arrive in slots as QJSValues whose property() access is
    unreliable in PySide6, so the map is built Python-side instead and
    refreshed on tokensChanged."""

    #: token role -> theme token (s stays theme-independent, 0.x value)
    _ROLE_MAP = {
        "t": ("accent", "#39B8C4"),   # tags
        "k": ("accent", "#39B8C4"),   # JS keywords
        "a": ("hlInk", "#F5C25C"),    # attribute names / CSS props
        "s": ("strings", "#98C379"),  # strings (theme-independent)
        "c": ("inkFaint", "#5F6C78"), # comments
        "n": ("hlInk", "#F5C25C"),    # numbers
        "f": ("text", "#E7EDF2"),     # CSS selectors / JS functions
    }

    def __init__(self, theme=None, parent=None):
        super().__init__(parent)
        self._hl: _Highlighter | None = None
        self._doc: QQuickTextDocument | None = None
        self._lang = "html"
        self._colors: dict[str, str] = {}
        self._theme = theme
        if theme is not None:
            theme.tokensChanged.connect(self.refresh_colors)
        self.refresh_colors()

    @Slot("QVariant", str)
    def attach(self, doc, lang: str) -> None:
        """Bind to a TextArea's textDocument (QQuickTextDocument)."""
        if not isinstance(doc, QQuickTextDocument):
            return
        self._doc = doc
        self._lang = lang if lang in _RULES else "js"
        qdoc = doc.textDocument()
        if qdoc is None:
            return
        if self._hl is not None:
            self._hl.setDocument(None)
            self._hl.deleteLater()
        self._hl = _Highlighter(qdoc, self)
        self._hl._colors = self._colors
        self._hl._formats = {k: _fmt(v) for k, v in self._colors.items()}
        self._hl._lang = self._lang
        self._hl.rehighlight()

    @Slot(str)
    def set_language(self, lang: str) -> None:
        self._lang = lang if lang in _RULES else "js"
        if self._hl is not None:
            self._hl.set_language(self._lang)

    @Slot()
    def refresh_colors(self) -> None:
        """(Re)build the color map from the theme bridge's tokens."""
        if self._theme is None:
            return
        try:
            tokens = self._theme.tokens  # QVariantMap -> dict
        except Exception:
            return
        colors = {}
        for role, (key, fallback) in self._ROLE_MAP.items():
            colors[role] = str(tokens.get(key, fallback))
        if colors != self._colors:
            self._colors = colors
            if self._hl is not None:
                self._hl.set_colors(self._colors)

    @Slot("QVariant")
    def set_colors(self, colors) -> None:
        """Programmatic override of the role->color map (dict only).

        Not used from QML: JS objects arrive as QJSValues whose
        property() access is unreliable in PySide6; the UI relies on
        the theme-driven refresh_colors() path instead."""
        if not isinstance(colors, dict):
            return
        self._colors = {str(k): str(v) for k, v in colors.items()}
        if self._hl is not None:
            self._hl.set_colors(self._colors)
