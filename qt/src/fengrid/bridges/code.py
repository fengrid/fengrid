"""Code bridge: snippet store over the SQLite core (code pane, M3).

Follows the bridges/colors.py pattern — QVariantList properties with
notify signals, no C++ models. The editor contents live in QML; the
bridge owns the DB rows and the import engine (core.snippets). The 0.x
pane drove these over /api/snippets REST endpoints; same data, no server.
"""

from __future__ import annotations

import json

from PySide6.QtCore import Property, QObject, Signal, Slot

from ..core import db as core_db
from ..core import settings
from ..core import snippets as core_snippets


class Code(QObject):
    message = Signal(str)
    snippetsChanged = Signal()
    tagsChanged = Signal()
    currentChanged = Signal()
    savedChanged = Signal()
    filtersChanged = Signal()
    importDone = Signal(int)
    importFailed = Signal(str)
    keymapChanged = Signal()

    KEYMAPS = ("vscode", "emacs", "vim", "readline")

    def __init__(self, con, parent=None):
        super().__init__(parent)
        self._con = con
        self._q = ""
        self._lang = ""
        self._sort = "updated"
        # optional collection filter for the side rail (snippet kind)
        self._collection: int | None = None
        # active smart collection (sidebar) — criteria filtered in Python
        self._smart_id = 0
        self._current_id: int | None = None
        self._current: dict = {}
        self._snippets: list = []
        self._tags: list = []
        self._last_saved = ""
        km = settings.get(con, "editor_keymap", "vscode")
        self._keymap = km if km in self.KEYMAPS else "vscode"
        self._refresh()

    # ---------------------------------------------------------------- state
    @Property("QVariantList", notify=snippetsChanged)
    def snippets(self) -> list:
        return self._snippets

    @Property("QVariantList", notify=tagsChanged)
    def tags(self) -> list:
        return self._tags

    @Property(int, notify=currentChanged)
    def currentId(self) -> int:
        return -1 if self._current_id is None else self._current_id

    @Property("QVariantMap", notify=currentChanged)
    def current(self) -> dict:
        return self._current

    # ------------------------------------------------------------- keymaps
    @Property(str, notify=keymapChanged)
    def keymap(self) -> str:
        return self._keymap

    @Slot(str)
    def set_keymap(self, scheme: str) -> None:
        scheme = str(scheme or "").strip().lower()
        if scheme not in self.KEYMAPS or scheme == self._keymap:
            return
        self._keymap = scheme
        settings.set(self._con, "editor_keymap", scheme)
        self.keymapChanged.emit()
        self.message.emit("Editor keymap: " + scheme)

    @Slot(result="QVariantList")
    def keymap_names(self) -> list:
        return list(self.KEYMAPS)

    @Property(int, notify=snippetsChanged)
    def snippetCount(self) -> int:
        return len(self._snippets)

    @Property(str, notify=filtersChanged)
    def searchQ(self) -> str:
        return self._q

    @Property(str, notify=filtersChanged)
    def langFilter(self) -> str:
        return self._lang

    @Property(str, notify=filtersChanged)
    def sortBy(self) -> str:
        return self._sort

    @Property(str, notify=filtersChanged)
    def collectionFilter(self) -> str:
        return "" if self._collection is None else str(self._collection)

    @Property(str, notify=filtersChanged)
    def smartFilter(self) -> str:
        return "" if not self._smart_id else str(self._smart_id)

    @Slot(str)
    def set_smart(self, sc_id: str) -> None:
        """Toggle the sidebar smart-collection filter (snippet kind)."""
        sid = int(sc_id) if str(sc_id).strip().isdigit() else 0
        if sid and sid == self._smart_id:
            sid = 0
        self._smart_id = sid
        self.filtersChanged.emit()
        self._refresh()

    @Property(str, notify=savedChanged)
    def lastSaved(self) -> str:
        return self._last_saved

    # ---------------------------------------------------------------- slots
    @Slot(str)
    def set_search(self, q: str) -> None:
        self._q = (q or "").strip()
        self._refresh()

    @Slot(str)
    def set_lang(self, lang: str) -> None:
        self._lang = lang or ""
        self._refresh()

    @Slot(str)
    def set_sort(self, sort: str) -> None:
        if sort not in ("updated", "created", "title"):
            return
        self._sort = sort
        self._refresh()

    @Slot(str)
    def set_collection(self, coll: str) -> None:
        """Toggle the side-rail collection filter (snippet kind)."""
        s = (coll or "").strip()
        cid = int(s) if s.isdigit() else None
        if cid is None or cid == self._collection:
            self._collection = None
        else:
            self._collection = cid
        self.filtersChanged.emit()
        self._refresh()

    @Slot()
    def new_snippet(self) -> None:
        self.new_snippet_in("web")

    @Slot(str)
    def new_snippet_in(self, lang: str) -> None:
        """New snippet in an editor-suite language (dropdown / / command)."""
        self._current_id = None
        self._current = {"id": -1, "title": "", "description": "",
                         "language": lang or "web", "html": "", "css": "",
                         "js": "", "tags": "", "created": "", "updated": ""}
        self.currentChanged.emit()

    @Property("QVariantList", constant=True)
    def languages(self) -> list:
        """Snippet editor language suite (dropdown + / command)."""
        return core_snippets.editor_languages()

    @Slot(str, result=str)
    def body_field(self, lang: str) -> str:
        """Single body field for a non-web editor language; "" for the
        web fiddle (which keeps all three tabs)."""
        field = core_snippets.language_field(lang)
        return field or ""

    @Slot(str, bool, result=str)
    def markdown_html(self, md: str, dark: bool = False) -> str:
        """GitHub-styled full HTML document for the markdown preview."""
        return core_snippets.markdown_doc(md, bool(dark))

    @Slot(str, int, result="QVariantList")
    def palette_search(self, query: str, limit: int = 8) -> list:
        """Command-bar snippet lookup (Dash/Alfred-style) over title,
        description, tags and body — independent of the pane's filters."""
        q = (query or "").strip()
        if not q:
            return []
        like = f"%{q}%"
        rows = self._con.execute(
            "SELECT id, title, language FROM snippet"
            " WHERE title LIKE ? OR description LIKE ? OR tags LIKE ?"
            " OR html LIKE ? OR css LIKE ? OR js LIKE ?"
            " ORDER BY (title LIKE ?) DESC, LENGTH(title), title LIMIT ?",
            (like, like, like, like, like, like, q + "%",
             max(1, min(int(limit), 30)))).fetchall()
        return [{"id": r["id"], "title": r["title"],
                 "language": r["language"]} for r in rows]

    @Slot(int)
    def open_snippet(self, sid: int) -> None:
        row = core_snippets.get_snippet(self._con, sid)
        if row is None:
            return
        self._current_id = int(sid)
        self._current = dict(row)
        self.currentChanged.emit()

    @Slot(str, str, str, str, str, str, str)
    def save(self, title: str, description: str, language: str,
             html: str, css: str, js: str, tags: str) -> None:
        title = (title or "").strip() or "Untitled snippet"
        description = (description or "").strip()
        language = language or "web"
        tags = (tags or "").strip()
        if self._current_id is None:
            sid = core_snippets.create_snippet(
                self._con, title, description, language, html, css, js, tags)
            self._current_id = int(sid)
        else:
            core_snippets.update_snippet(
                self._con, self._current_id, title, description, language,
                html, css, js, tags)
        # keep item_tag in sync with the editor's CSV tags (single
        # source of truth going forward)
        core_db._sync_item_tags(self._con, self._current_id, "snippet", tags)
        self._current = dict(core_snippets.get_snippet(self._con,
                                                       self._current_id) or {})
        self._last_saved = self._current.get("title", "")
        self._refresh()
        self.currentChanged.emit()
        self.savedChanged.emit()
        self.message.emit(f"Saved: {self._current.get('title', '')}")

    @Slot(int)
    def remove(self, sid: int) -> None:
        core_snippets.delete_snippet(self._con, sid)
        if self._current_id == sid:
            self._current_id = None
            self._current = {}
            self.currentChanged.emit()
        self._refresh()
        self.message.emit("Snippet deleted")

    @Slot(str, str)
    def import_snippets(self, kind: str, path: str) -> None:
        try:
            items = core_snippets.import_file(kind, path)
        except (ValueError, OSError) as e:
            # json.JSONDecodeError subclasses ValueError — one clause covers
            # bad JSON, unknown kinds, and missing files
            self.importFailed.emit(str(e))
            return
        if not items:
            self.importFailed.emit("no snippets found in that file")
            return
        for it in items:
            core_snippets.create_snippet(
                self._con, it["title"], it["description"], it["language"],
                it["html"], it["css"], it["js"], it["tags"])
        self._refresh()
        self.importDone.emit(len(items))
        self.message.emit(f"Imported {len(items)} snippet"
                          f"{'s' if len(items) != 1 else ''}")

    # -------------------------------------------------------------- internals
    def _refresh(self) -> None:
        rows = core_snippets.list_snippets(
            self._con, q=self._q, lang=self._lang, sort=self._sort,
            collection_id=self._collection)
        self._snippets = [dict(r) for r in rows]
        if self._smart_id:
            from .colors import _matches_smart
            self._snippets = [s for s in self._snippets
                              if _matches_smart(self._con, self._smart_id, s)]
        self._tags = [{"name": n, "count": c}
                      for n, c in core_snippets.tag_cloud(self._con)]
        self.snippetsChanged.emit()
        self.tagsChanged.emit()
