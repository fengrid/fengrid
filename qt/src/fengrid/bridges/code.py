"""Code bridge: snippet store over the SQLite core (code pane, M3).

Follows the bridges/colors.py pattern — QVariantList properties with
notify signals, no C++ models. The editor contents live in QML; the
bridge owns the DB rows and the import engine (core.snippets). The 0.x
pane drove these over /api/snippets REST endpoints; same data, no server.
"""

from __future__ import annotations
from pathlib import Path

import json

from PySide6.QtCore import Property, QObject, Signal, Slot

from ..core import assetrefs as core_assetrefs
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
    exportDone = Signal(str)
    exportFailed = Signal(str)
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
        self._starred_only = False
        # saved-library tag filter (rail Libraries row on this pane)
        self._lib_tags: list[str] = []
        self._lib_match_all = True
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
        self._starred_only = False
        self.filtersChanged.emit()
        self._refresh()

    # ── starred rail row: filter the pane to starred snippets ──
    starredOnlyChanged = Signal()

    @Property(bool, notify=starredOnlyChanged)
    def starredOnly(self) -> bool:
        return self._starred_only

    @Slot(bool)
    def set_starred_only(self, on: bool) -> None:
        on = bool(on)
        if on == self._starred_only:
            return
        self._starred_only = on
        if on:
            self._collection = None
        self.filtersChanged.emit()
        self._refresh()

    # ── saved-library tag filter (rail Libraries row, snippet pane) ──
    libTagsChanged = Signal()

    @Property(str, notify=libTagsChanged)
    def libraryTagFilter(self) -> str:
        return ",".join(self._lib_tags)

    @Slot(str, bool)
    def set_library_tags(self, tags_csv: str, match_all: bool = True) -> None:
        """Toggle the library-view tag filter on this pane (second call
        with the same list clears it)."""
        wanted = [t.strip() for t in str(tags_csv or "").split(",")
                  if t.strip()]
        if wanted and wanted == self._lib_tags:
            wanted = []
        self._lib_tags = wanted
        self._lib_match_all = bool(match_all)
        self.libTagsChanged.emit()
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
        """GitHub-styled full HTML document for the markdown preview.

        [[ asset ]] references are expanded first so `img src="[[ slug ]]"`
        renders the tracked file through the hardened fengrid-asset://
        scheme; unresolved refs stay visible as the literal token."""
        expanded, _unresolved = core_assetrefs.expand(self._con, md or "")
        return core_snippets.markdown_doc(expanded, bool(dark))

    @Slot(str, result=str)
    def expand_refs(self, text: str) -> str:
        """Expand [[ slug ]] / [[ GUID ]] / [[ type/…/name ]] references
        in a text block (snippet bodies, project templates)."""
        expanded, _unresolved = core_assetrefs.expand(self._con, text or "")
        return expanded

    @Slot(str, str, str, result=str)
    def fiddle_doc(self, html: str, css: str, js: str) -> str:
        """The Run ▸ preview document with asset references expanded in
        all three fiddle panes. Expanded asset paths (legal filesystem
        characters) are context-escaped so they can never break out of
        the <style>/<script> elements (SEC-1): `</script` and
        `</style` in the expanded payload would close the element and
        inject arbitrary markup into the preview document."""
        exp_html, _u1 = core_assetrefs.expand(self._con, html or "")
        exp_css, _u2 = core_assetrefs.expand(self._con, css or "")
        exp_js, _u3 = core_assetrefs.expand(self._con, js or "")
        # "\/" is identical to "/" inside JS/CSS string literals, so
        # legitimate content is unaffected; breakout sequences are
        # neutralized
        exp_js = exp_js.replace("</script", "<\\/script")
        exp_css = exp_css.replace("</style", "<\\/style")
        return ("<!DOCTYPE html><html><head><style>" + exp_css
                + "</style></head><body>" + exp_html
                + "<script>" + exp_js + "</" + "script></body></html>")

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
        if not kind:
            # #98: the Settings import row doesn't know the source kind —
            # infer it from the file extension (.sqlite/.db = massCode,
            # .code-snippets/.json = VS Code)
            kind = core_snippets.infer_snippet_kind(path)
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

    @Slot(result="QVariantList")
    def scan_vscode_snippets(self) -> list:
        """#98: find snippet files at VS Code's default locations.

        Returns a list of dicts {app, name, path} for each .code-snippets
        or .json file in the User/snippets folder of any installed VS Code
        variant (Code / Insiders / VSCodium / Cursor). Empty when none
        exist — the user can still pick files manually.
        """
        return core_snippets.scan_vscode_snippets()

    # -------------------------------------------------------------- exports
    @Slot(str, str)
    def export_current(self, dest_dir: str, kind: str = "html") -> None:
        """Export the CURRENT snippet: 'html' = standalone page with the
        editors' HTML/CSS/JS inlined; any core kind (bundle / vscode /
        masscode / files) packages it the same way the library does."""
        from ..core import exportplus as core_exportplus
        dest = str(Path(dest_dir).expanduser()) if dest_dir else ""
        if not dest:
            self.exportFailed.emit("choose a folder first")
            return
        cur = self._current
        if not cur:
            self.exportFailed.emit("no snippet open")
            return
        try:
            if kind == "html":
                name = (_slug_of(cur.get("title")) or "snippet") + ".html"
                out = Path(dest) / name
                out.write_text(_standalone_html(cur), encoding="utf-8")
            else:
                res = core_exportplus.export_snippets(
                    [_snippet_row(self._con, int(cur["id"]))],
                    dest, kind=kind)
                out = res["outputs"][0] if res["outputs"] else dest
        except Exception as e:                    # noqa: BLE001
            self.exportFailed.emit(str(e))
            return
        settings.set(self._con, "last_export_dir", dest)
        self.exportDone.emit(str(out))

    @Slot(str, str)
    def export_all(self, dest_dir: str, kind: str = "bundle") -> None:
        """Export EVERY listed snippet in the given package kind."""
        from ..core import exportplus as core_exportplus
        dest = str(Path(dest_dir).expanduser()) if dest_dir else ""
        if not dest:
            self.exportFailed.emit("choose a folder first")
            return
        try:
            rows = [_snippet_row(self._con, int(s["id"]))
                    for s in self._snippets]
            if not rows:
                self.exportFailed.emit("no snippets to export")
                return
            res = core_exportplus.export_snippets(rows, dest, kind=kind)
            out = res["outputs"][0] if res["outputs"] else dest
        except Exception as e:                    # noqa: BLE001
            self.exportFailed.emit(str(e))
            return
        settings.set(self._con, "last_export_dir", dest)
        self.exportDone.emit(str(out))

    # -------------------------------------------------------------- internals
    def _refresh(self) -> None:
        rows = core_snippets.list_snippets(
            self._con, q=self._q, lang=self._lang, sort=self._sort,
            collection_id=self._collection, starred_only=self._starred_only)
        self._snippets = [dict(r) for r in rows]
        if self._smart_id:
            from .colors import _matches_smart
            self._snippets = [s for s in self._snippets
                              if _matches_smart(self._con, self._smart_id, s)]
        if self._lib_tags:
            from .colors import _tags_match
            self._snippets = [s for s in self._snippets
                              if _tags_match(s.get("tags"), self._lib_tags,
                                             self._lib_match_all)]
        self._tags = [{"name": n, "count": c}
                      for n, c in core_snippets.tag_cloud(self._con)]
        self.snippetsChanged.emit()
        self.tagsChanged.emit()


def _slug_of(title: str) -> str:
    import re as _re
    return _re.sub(r"[^A-Za-z0-9._-]+", "-", (title or "").strip()).strip("-")


def _snippet_row(con, snippet_id: int) -> dict:
    row = con.execute(
        "SELECT id, title, language, description, tags, html,"
        " css, js FROM snippet WHERE id = ?", (snippet_id,)
    ).fetchone()
    return dict(row) if row else {}


def _standalone_html(cur: dict) -> str:
    css = cur.get("css") or ""
    js = cur.get("js") or ""
    body = cur.get("html") or ""
    return ("<!doctype html><html><head><meta charset='utf-8'>"
            f"<title>{cur.get('title') or 'snippet'}</title>"
            f"<style>{css}</style></head><body>"
            f"{body}<script>{js}</" + "script></body></html>")
