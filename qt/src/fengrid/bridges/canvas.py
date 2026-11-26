"""Canvas bridge — QML facade over core.canvas.

Backs the Projects pane's Canvas screen (StudioCanvas.qml): boards of
the current project, the node list (with bound nodes hydrated from the
library: file URLs, registered font families, palette hexes, snippet
code), selection, undo/redo, library pickers for the asset panel, and
the live-collaboration loop:

  - every local edit goes through core.canvas (Lamport-stamped op log)
  - a light poll (``head`` seq, one indexed query) picks up ops written
    by anyone else — the REST API, a second window, a remote peer — and
    refreshes the board; presence (who else is here, their cursors) is
    published/read on the same tick

Slots are camelCase in Python: PySide6 exposes slots under their Python
names only (see tests/test_qml_bridge_callnames.py).
"""
from __future__ import annotations

import json
import os

from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot

from ..core import assetrefs
from ..core import canvas as core_canvas
from ..core import db as core_db

_UNDO_CAP = 200
_POLL_MS = 900
_PRESENCE_EVERY = 4                     # poll ticks between heartbeats
_PEER_COLORS = ("#E879A6", "#A78BFA", "#F0885C", "#5AA7E8", "#63C48B",
                "#F5C25C")


class Canvas(QObject):
    message = Signal(str)
    boardsChanged = Signal()
    boardChanged = Signal()
    nodesChanged = Signal()
    selectionChanged = Signal()
    historyChanged = Signal()
    peersChanged = Signal()
    commentsChanged = Signal()

    def __init__(self, con, parent=None, poll: bool = True):
        super().__init__(parent)
        self._con = con
        core_canvas.migrate(con)
        self._actor = core_canvas.local_actor(con)
        self._projects = None
        self._board_id = -1
        self._nodes: list[dict] = []
        self._sel: list[str] = []
        self._undo: list[list] = []
        self._redo: list[list] = []
        self._seen = 0
        self._peers: list[dict] = []
        self._cursor: tuple | None = None
        self._tick = 0
        self._font_cache: dict[str, str] = {}
        self._timer = QTimer(self)
        self._timer.setInterval(_POLL_MS)
        self._timer.timeout.connect(self._poll)
        if poll:
            self._timer.start()

    # ─────────────────────────────────────────────────────── binding
    def bind_projects(self, projects_bridge) -> None:
        self._projects = projects_bridge
        projects_bridge.currentChanged.connect(self._project_switched)
        self._project_switched()

    def _pid(self) -> int:
        if self._projects is None:
            return -1
        return int(self._projects.currentId)

    def _project_switched(self) -> None:
        boards = self._boards()
        self._open(boards[0]["id"] if boards else -1)
        self.boardsChanged.emit()

    def _boards(self) -> list[dict]:
        pid = self._pid()
        return core_canvas.list_boards(self._con, pid) if pid > 0 else []

    def _open(self, board_id: int) -> None:
        self._board_id = int(board_id)
        self._sel = []
        self._undo.clear()
        self._redo.clear()
        self._seen = core_canvas.head(self._con, self._board_id) \
            if self._board_id > 0 else 0
        self._reload()
        self.boardChanged.emit()
        self.selectionChanged.emit()
        self.historyChanged.emit()
        self.commentsChanged.emit()

    # ──────────────────────────────────────────────────── hydration
    def _font_family(self, path: str, fallback: str) -> str:
        """Register a font file with Qt once; return the family Qt
        reports (that's the name QML Text can actually use)."""
        if not path:
            return fallback
        if path in self._font_cache:
            return self._font_cache[path] or fallback
        fam = ""
        try:
            from PySide6.QtGui import QFontDatabase
            fid = QFontDatabase.addApplicationFont(path)
            if fid >= 0:
                fams = QFontDatabase.applicationFontFamilies(fid)
                fam = fams[0] if fams else ""
        except Exception:                        # noqa: BLE001 — no GUI app
            fam = ""
        self._font_cache[path] = fam
        return fam or fallback

    def _view(self, n: dict, cache: dict) -> dict:
        b = n.get("bind") or {}
        if not b:
            return {}
        key = b.get("guid") or f"{b.get('kind')}:{b.get('id')}"
        if key in cache:
            return cache[key]
        info = core_canvas.hydrate(self._con, b)
        v = {"ok": bool(info.get("ok")), "kind": info.get("kind", ""),
             "name": info.get("name", ""), "id": info.get("id", 0),
             "slug": info.get("slug", ""), "guid": info.get("guid", "")}
        path = info.get("path") or ""
        if path:
            v["url"] = QUrl.fromLocalFile(path).toString()
            v["ext"] = info.get("ext") or ""
        if info.get("kind") == "font":
            v["family"] = self._font_family(path, info.get("family") or "")
        if "hexes" in info:
            v["hexes"] = info["hexes"]
        if info.get("kind") == "snippet":
            v["code"] = (info.get("html") or "")[:2000]
            v["css"] = (info.get("css") or "")[:2000]
            v["language"] = info.get("language") or ""
        if "members" in info:
            v["members"] = len(info["members"])
        cache[key] = v
        return v

    def _reload(self) -> None:
        if self._board_id <= 0:
            self._nodes = []
        else:
            cache: dict = {}
            out = []
            for n in core_canvas.nodes(self._con, self._board_id):
                n["view"] = self._view(n, cache)
                out.append(n)
            self._nodes = out
        alive = {n["id"] for n in self._nodes}
        if any(i not in alive for i in self._sel):
            self._sel = [i for i in self._sel if i in alive]
            self.selectionChanged.emit()
        self.nodesChanged.emit()

    # ─────────────────────────────────────────────────── edit plumbing
    def _guard(self, fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except core_canvas.CanvasError as e:
            self.message.emit(str(e))
        except Exception as e:                   # noqa: BLE001
            self.message.emit(f"{type(e).__name__}: {e}")
        return None

    def _record(self, inverse: list) -> None:
        if not inverse:
            return
        self._undo.append(inverse)
        if len(self._undo) > _UNDO_CAP:
            del self._undo[0]
        self._redo.clear()
        self.historyChanged.emit()

    def _after_edit(self, logged) -> None:
        if logged:
            self._seen = max(self._seen, max(o["seq"] for o in logged))
        self._reload()

    def _need_board(self) -> bool:
        if self._board_id > 0:
            return True
        self.message.emit("Create a board first")
        return False

    # ─────────────────────────────────────────────────────── properties
    @Property(str, constant=True)
    def actor(self) -> str:
        return self._actor

    @Property("QVariantList", notify=boardsChanged)
    def boards(self) -> list:
        return self._boards()

    @Property(int, notify=boardChanged)
    def boardId(self) -> int:
        return self._board_id

    @Property(str, notify=boardChanged)
    def boardName(self) -> str:
        b = core_canvas.get_board(self._con, self._board_id) \
            if self._board_id > 0 else None
        return b["name"] if b else ""

    @Property("QVariantMap", notify=boardChanged)
    def boardSettings(self) -> dict:
        b = core_canvas.get_board(self._con, self._board_id) \
            if self._board_id > 0 else None
        return b["settings"] if b else {}

    @Property("QVariantList", notify=nodesChanged)
    def nodes(self) -> list:
        return self._nodes

    @Property(int, notify=nodesChanged)
    def nodeCount(self) -> int:
        return len(self._nodes)

    @Property("QVariantList", notify=selectionChanged)
    def selection(self) -> list:
        return list(self._sel)

    @Property("QVariantList", notify=selectionChanged)
    def selectedNodes(self) -> list:
        byid = {n["id"]: n for n in self._nodes}
        return [byid[i] for i in self._sel if i in byid]

    @Property(bool, notify=historyChanged)
    def canUndo(self) -> bool:
        return bool(self._undo)

    @Property(bool, notify=historyChanged)
    def canRedo(self) -> bool:
        return bool(self._redo)

    @Property("QVariantList", notify=peersChanged)
    def peers(self) -> list:
        return self._peers

    @Property("QVariantList", notify=commentsChanged)
    def comments(self) -> list:
        if self._board_id <= 0:
            return []
        return core_canvas.comments(self._con, self._board_id)

    # ─────────────────────────────────────────────────────────── boards
    @Slot(str)
    def newBoard(self, name: str) -> None:
        pid = self._pid()
        if pid <= 0:
            self.message.emit("Open a project first")
            return
        bid = self._guard(core_canvas.create_board, self._con, pid, name)
        if bid:
            self.boardsChanged.emit()
            self._open(bid)

    @Slot(int)
    def setBoard(self, board_id: int) -> None:
        if board_id != self._board_id:
            self._open(board_id)

    @Slot(str)
    def renameBoard(self, name: str) -> None:
        if self._need_board():
            self._guard(core_canvas.rename_board, self._con, self._board_id,
                        name)
            self.boardsChanged.emit()
            self.boardChanged.emit()

    @Slot()
    def duplicateBoard(self) -> None:
        if self._need_board():
            nb = self._guard(core_canvas.duplicate_board, self._con,
                             self._board_id)
            if nb:
                self.boardsChanged.emit()
                self._open(nb)

    @Slot()
    def deleteBoard(self) -> None:
        if not self._need_board():
            return
        core_canvas.delete_board(self._con, self._board_id)
        self.boardsChanged.emit()
        boards = self._boards()
        self._open(boards[0]["id"] if boards else -1)

    @Slot(float, float, float)
    def saveViewport(self, x: float, y: float, zoom: float) -> None:
        if self._board_id > 0:
            core_canvas.set_board_settings(
                self._con, self._board_id,
                {"viewport": [round(x, 1), round(y, 1), round(zoom, 3)]})

    # ─────────────────────────────────────────────────────── selection
    @Slot(str, bool)
    def select(self, node_id: str, additive: bool) -> None:
        if not node_id:
            self._sel = [] if not additive else self._sel
        elif additive:
            if node_id in self._sel:
                self._sel = [i for i in self._sel if i != node_id]
            else:
                self._sel = self._sel + [node_id]
        else:
            self._sel = [node_id]
        self.selectionChanged.emit()

    @Slot("QVariantList", bool)
    def selectMany(self, ids: list, additive: bool) -> None:
        ids = [str(i) for i in ids]
        self._sel = list(dict.fromkeys((self._sel if additive else []) + ids))
        self.selectionChanged.emit()

    @Slot()
    def selectAll(self) -> None:
        self._sel = [n["id"] for n in self._nodes
                     if not n["locked"] and not n["parent"]]
        self.selectionChanged.emit()

    @Slot()
    def clearSelection(self) -> None:
        if self._sel:
            self._sel = []
            self.selectionChanged.emit()

    # ─────────────────────────────────────────────────────────── edits
    def _apply(self, result) -> None:
        """Common tail for (logged, inverse) edit results."""
        if result is None:
            return
        logged, inv = result[-2], result[-1]
        self._record(inv)
        self._after_edit(logged)

    @Slot(str, float, float, float, float, result=str)
    def addNode(self, ntype: str, x: float, y: float, w: float,
                h: float) -> str:
        if not self._need_board():
            return ""
        res = self._guard(core_canvas.create_node, self._con,
                          self._board_id, ntype, x, y,
                          w if w > 0 else None, h if h > 0 else None,
                          actor=self._actor)
        if res is None:
            return ""
        self._apply(res)
        self._sel = [res[0]]
        self.selectionChanged.emit()
        return res[0]

    @Slot(str, str, "QVariant")
    def setField(self, node_id: str, key: str, value) -> None:
        """One field: x/y/w/h/rot/name/locked/hidden or p.<prop>."""
        if self._need_board():
            self._apply(self._guard(core_canvas.update_node, self._con,
                                    self._board_id, node_id, {key: value},
                                    self._actor))

    @Slot(str, str, "QVariant")
    def setProp(self, node_id: str, key: str, value) -> None:
        self.setField(node_id, "p." + key, value)

    @Slot(str, "QVariantMap")
    def setFields(self, node_id: str, fields: dict) -> None:
        if self._need_board() and fields:
            self._apply(self._guard(core_canvas.update_node, self._con,
                                    self._board_id, node_id, dict(fields),
                                    self._actor))

    @Slot(str, "QVariant")
    def setPropOnSelection(self, key: str, value) -> None:
        if not self._need_board() or not self._sel:
            return
        ops = [{"node": i, "fields": {"p." + key: value}} for i in self._sel]
        self._apply(self._guard(core_canvas.edit, self._con, self._board_id,
                                ops, self._actor))

    @Slot(str, float, float, float, float)
    def setGeometry(self, node_id: str, x: float, y: float, w: float,
                    h: float) -> None:
        self.setFields(node_id, {"x": x, "y": y,
                                 "w": max(core_canvas.MIN_SIZE, w),
                                 "h": max(0.0, h)})

    @Slot(float, float)
    def moveSelection(self, dx: float, dy: float) -> None:
        if self._need_board() and self._sel and (dx or dy):
            self._apply(self._guard(core_canvas.move_nodes, self._con,
                                    self._board_id, self._sel, dx, dy,
                                    self._actor))

    @Slot()
    def deleteSelection(self) -> None:
        if self._need_board() and self._sel:
            self._apply(self._guard(core_canvas.delete_nodes, self._con,
                                    self._board_id, self._sel, self._actor))
            self._sel = []
            self.selectionChanged.emit()

    @Slot()
    def duplicateSelection(self) -> None:
        if not (self._need_board() and self._sel):
            return
        res = self._guard(core_canvas.duplicate_nodes, self._con,
                          self._board_id, self._sel, 24.0, self._actor)
        if res:
            self._apply(res)
            self._sel = list(res[0])
            self.selectionChanged.emit()

    @Slot(bool)
    def groupSelection(self, as_frame: bool) -> None:
        if not (self._need_board() and self._sel):
            return
        res = self._guard(core_canvas.group_nodes, self._con,
                          self._board_id, self._sel,
                          "Frame" if as_frame else "Group", as_frame,
                          self._actor)
        if res:
            self._apply(res)
            self._sel = [res[0]]
            self.selectionChanged.emit()

    @Slot()
    def ungroupSelection(self) -> None:
        if not (self._need_board() and len(self._sel) == 1):
            return
        gid = self._sel[0]
        kids = [n["id"] for n in self._nodes if n["parent"] == gid]
        res = self._guard(core_canvas.ungroup, self._con, self._board_id,
                          gid, self._actor)
        if res:
            self._apply(res)
            self._sel = kids
            self.selectionChanged.emit()

    @Slot(str)
    def restackSelection(self, where: str) -> None:
        if self._need_board() and self._sel:
            self._apply(self._guard(core_canvas.restack, self._con,
                                    self._board_id, self._sel, where,
                                    self._actor))

    @Slot(str)
    def alignSelection(self, how: str) -> None:
        if self._need_board() and len(self._sel) > 1:
            self._apply(self._guard(core_canvas.align, self._con,
                                    self._board_id, self._sel, how,
                                    self._actor))

    @Slot(str, str, result=str)
    def connectNodes(self, from_id: str, to_id: str) -> str:
        """Connector between two nodes (follows them when they move)."""
        if not (self._need_board() and from_id and to_id
                and from_id != to_id):
            return ""
        res = self._guard(core_canvas.create_node, self._con,
                          self._board_id, "connector", 0, 0, 0, 0,
                          props={"from": from_id, "to": to_id},
                          name="Connector", actor=self._actor)
        if res:
            self._apply(res)
            return res[0]
        return ""

    @Slot()
    def undo(self) -> None:
        if not self._undo or self._board_id <= 0:
            return
        inv = self._undo.pop()
        res = self._guard(core_canvas.edit, self._con, self._board_id, inv,
                          self._actor)
        if res:
            self._redo.append(res[1])
            self._after_edit(res[0])
        self.historyChanged.emit()

    @Slot()
    def redo(self) -> None:
        if not self._redo or self._board_id <= 0:
            return
        fwd = self._redo.pop()
        res = self._guard(core_canvas.edit, self._con, self._board_id, fwd,
                          self._actor)
        if res:
            self._undo.append(res[1])
            self._after_edit(res[0])
        self.historyChanged.emit()

    # ───────────────────────────────────────────── library integration
    def _placed(self, res) -> str:
        if not res:
            return ""
        self._apply(res)
        core_canvas.sync_links(self._con, self._board_id)
        first = res[0]
        self._sel = list(first) if isinstance(first, list) else [first]
        self.selectionChanged.emit()
        return self._sel[0] if self._sel else ""

    @Slot(str, int, float, float, result=str)
    def placeAsset(self, kind: str, item_id: int, x: float, y: float) -> str:
        if not self._need_board():
            return ""
        if kind == "collection":
            return self._placed(self._guard(
                core_canvas.place_collection, self._con, self._board_id,
                item_id, x, y, actor=self._actor))
        if kind == "smart":
            return self._placed(self._guard(
                core_canvas.place_smart_collection, self._con,
                self._board_id, item_id, x, y, actor=self._actor))
        if kind == "library":
            return self._placed(self._guard(
                core_canvas.place_library_view, self._con, self._board_id,
                item_id, x, y, actor=self._actor))
        return self._placed(self._guard(
            core_canvas.place_asset, self._con, self._board_id, kind,
            item_id, x, y, actor=self._actor))

    @Slot(str, float, float, result=str)
    def placeRef(self, ref: str, x: float, y: float) -> str:
        if not self._need_board():
            return ""
        return self._placed(self._guard(core_canvas.place_ref, self._con,
                                        self._board_id, ref, x, y,
                                        actor=self._actor))

    @Slot(int, float, float)
    def explodePalette(self, palette_id: int, x: float, y: float) -> None:
        if self._need_board():
            self._placed(self._guard(core_canvas.explode_palette, self._con,
                                     self._board_id, palette_id, x, y,
                                     actor=self._actor))

    @Slot(str, str, result=bool)
    def bindNode(self, node_id: str, ref: str) -> bool:
        """(Re)bind a node to any [[ ref ]] — slug, GUID or path form."""
        if not self._need_board():
            return False
        b = core_canvas.binding_for_ref(self._con, ref)
        if b is None:
            self.message.emit(f"Unresolved reference: {ref}")
            return False
        self.setField(node_id, "bind", b)
        core_canvas.sync_links(self._con, self._board_id)
        return True

    @Slot(str)
    def codeToSnippet(self, node_id: str) -> None:
        if not self._need_board():
            return
        res = self._guard(core_canvas.code_to_snippet, self._con,
                          self._board_id, node_id, "", self._actor)
        if res:
            self._apply(res)
            core_canvas.sync_links(self._con, self._board_id)
            self.message.emit(f"Saved as snippet #{res[0]} (Code pane)")

    @Slot(str, int, result="QVariantList")
    def usage(self, kind: str, item_id: int) -> list:
        return core_canvas.usage(self._con, kind, item_id)

    @Slot(str, str, result="QVariantList")
    def libraryItems(self, kind: str, query: str) -> list:
        """Asset-panel rows: {kind, id, name, url?, hexes?, family?}."""
        q = f"%{(query or '').strip().lower()}%"
        con = self._con
        if kind == "palette":
            out = []
            for r in con.execute("SELECT id, name FROM palette WHERE"
                                 " lower(name) LIKE ? ORDER BY name"
                                 " LIMIT 200", (q,)):
                hexes = [h[0] for h in con.execute(
                    "SELECT hex FROM palette_color WHERE palette_id = ?"
                    " ORDER BY position", (r["id"],))]
                out.append({"kind": "palette", "id": r["id"],
                            "name": r["name"], "hexes": hexes})
            return out
        if kind == "snippet":
            return [{"kind": "snippet", "id": r["id"], "name": r["title"],
                     "language": r["language"]}
                    for r in con.execute(
                        "SELECT id, title, language FROM snippet WHERE"
                        " lower(title) LIKE ? ORDER BY updated DESC"
                        " LIMIT 200", (q,))]
        if kind == "collection":
            return [{"kind": "collection", "id": c["id"],
                     "name": c["name"], "sub": c.get("kind") or "mixed",
                     "count": c["total"]}
                    for c in core_db.collection_tree(con)
                    if query.lower() in c["name"].lower()][:200]
        if kind == "smart":
            return [{"kind": "smart", "id": r["id"], "name": r["name"],
                     "sub": r["item_kind"]} for r in con.execute(
                "SELECT id, name, item_kind FROM smart_collection WHERE"
                " lower(name) LIKE ? ORDER BY name LIMIT 200", (q,))]
        if kind == "library":
            return [{"kind": "library", "id": r["id"], "name": r["name"],
                     "sub": r["tags"]} for r in con.execute(
                "SELECT id, name, tags FROM library_view WHERE lower(name)"
                " LIKE ? ORDER BY name LIMIT 200", (q,))]
        cols = core_canvas._asset_cols(con)
        fam = ", family" if "family" in cols else ""
        rows = con.execute(
            f"SELECT id, kind, name, path{fam} FROM asset WHERE kind = ?"
            " AND lower(name) LIKE ? ORDER BY name LIMIT 300",
            (kind, q)).fetchall()
        out = []
        for r in rows:
            d = {"kind": r["kind"], "id": r["id"], "name": r["name"]}
            if kind in ("icon", "image"):
                d["url"] = QUrl.fromLocalFile(r["path"]).toString()
            if fam and r["family"]:
                d["family"] = r["family"]
            out.append(d)
        return out

    # ─────────────────────────────────────────────────── export/preview
    @Slot(result=str)
    def previewHtml(self) -> str:
        """The board as HTML for the pane's sandboxed live preview —
        file-backed nodes load through the fengrid-asset:// allowlist."""
        if self._board_id <= 0:
            return ""
        return core_canvas.render_html(
            self._con, self._board_id,
            assets=lambda p: assetrefs.url_for({"path": p}))

    @Slot(str, result=str)
    def exportBundle(self, folder_url: str) -> str:
        if not self._need_board():
            return ""
        path = QUrl(folder_url).toLocalFile() or folder_url
        name = (self.boardName or "board").strip().replace(os.sep, "-")
        dest = os.path.join(path, name or "board")
        res = self._guard(core_canvas.export_bundle, self._con,
                          self._board_id, dest)
        if res:
            msg = f"Exported {res['nodes']} nodes, {res['assets']} assets"
            if res["missing"]:
                msg += f" ({len(res['missing'])} missing files)"
            self.message.emit(msg + f" → {dest}")
            return dest
        return ""

    @Slot(result=str)
    def svgText(self) -> str:
        if self._board_id <= 0:
            return ""
        return core_canvas.render_svg(self._con, self._board_id)

    @Slot(result=str)
    def snapshotJson(self) -> str:
        if self._board_id <= 0:
            return "{}"
        return json.dumps(core_canvas.snapshot(self._con, self._board_id),
                          default=str)

    # ──────────────────────────────────────────────────────── comments
    @Slot(str, float, float, str)
    def addComment(self, body: str, x: float, y: float, node_id: str) -> None:
        if self._need_board() and self._guard(
                core_canvas.add_comment, self._con, self._board_id, body,
                node_id, x, y, self._actor):
            self.commentsChanged.emit()

    @Slot(int)
    def resolveComment(self, comment_id: int) -> None:
        core_canvas.resolve_comment(self._con, comment_id)
        self.commentsChanged.emit()

    # ─────────────────────────────────────────────────── collaboration
    @Slot(float, float)
    def setCursor(self, x: float, y: float) -> None:
        self._cursor = (x, y)

    def _poll(self) -> None:
        if self._board_id <= 0:
            return
        try:
            h = core_canvas.head(self._con, self._board_id)
            if h > self._seen:
                foreign = core_canvas.ops_since(
                    self._con, self._board_id, self._seen, 1,
                    exclude_actor=self._actor)
                self._seen = h
                if foreign:
                    self._reload()
                    self.boardChanged.emit()
            self._tick += 1
            if self._tick % _PRESENCE_EVERY == 0:
                core_canvas.touch_presence(
                    self._con, self._board_id, self._actor, "You",
                    _PEER_COLORS[0], self._cursor, self._sel)
                peers = core_canvas.presence(self._con, self._board_id,
                                             self._actor)
                for k, p in enumerate(peers):
                    if not p.get("color"):
                        p["color"] = _PEER_COLORS[(k + 1) % len(_PEER_COLORS)]
                if peers != self._peers:
                    self._peers = peers
                    self.peersChanged.emit()
        except Exception:                        # noqa: BLE001 — db busy
            pass

    @Slot()
    def refresh(self) -> None:
        self._reload()
