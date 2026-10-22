"""Taxonomy bridge: saved libraries, smart collections, custom fields,
generated IDs and links — a thin QVariantList adapter over core.taxonomy,
following the bridges/colors.py pattern (properties + notify signals, no
C++ models). The bridge holds no filter state itself: activating a
library or smart collection delegates to the pane bridges (library /
colors / code), which each keep their own filter state.
"""

from __future__ import annotations

import json

from PySide6.QtCore import Property, QObject, Signal, Slot

from ..core import db as core_db
from ..core import taxonomy as core_tax


class Taxonomy(QObject):
    message = Signal(str)
    viewsChanged = Signal()
    smartsChanged = Signal()
    fieldsChanged = Signal()
    linksChanged = Signal()

    def __init__(self, con, parent=None):
        super().__init__(parent)
        self._con = con
        self._refresh()

    # ---------------------------------------------------------------- state
    def _refresh(self) -> None:
        self._views = []
        for v in core_tax.list_library_views(self._con):
            v["n"] = len(core_tax.library_view_assets(self._con, v["id"]))
            self._views.append(v)
        self._smarts = []
        for s in core_tax.list_smart_collections(self._con):
            crit = s["criteria"]
            s["n"] = len(core_tax.smart_asset_ids(
                self._con, s["item_kind"], crit))
            self._smarts.append(s)
        self._fields = core_tax.list_fields(self._con)

    @Property("QVariantList", notify=viewsChanged)
    def libraryViews(self) -> list:
        return self._views

    @Property("QVariantList", notify=smartsChanged)
    def smartCollections(self) -> list:
        return self._smarts

    @Property("QVariantList", notify=fieldsChanged)
    def fields(self) -> list:
        return self._fields

    # ------------------------------------------------------ saved libraries
    @Slot(str, str, bool)
    def create_library_view(self, name: str, tags: str,
                            match_all: bool) -> None:
        try:
            core_tax.create_library_view(self._con, name, tags, match_all)
        except ValueError as e:
            self.message.emit(str(e))
            return
        self._refresh()
        self.viewsChanged.emit()
        self.message.emit(f"Library created: {name.strip()}")

    @Slot(int, str, str, bool)
    def update_library_view(self, view_id: int, name: str, tags: str,
                            match_all: bool) -> None:
        try:
            core_tax.update_library_view(self._con, view_id, name, tags,
                                         match_all)
        except ValueError as e:
            self.message.emit(str(e))
            return
        self._refresh()
        self.viewsChanged.emit()

    @Slot(int)
    def delete_library_view(self, view_id: int) -> None:
        core_tax.delete_library_view(self._con, view_id)
        self._refresh()
        self.viewsChanged.emit()
        self.message.emit("Library deleted")

    # ---------------------------------------------------- smart collections
    @Slot(str, str, str)
    def create_smart(self, name: str, item_kind: str,
                     criteria_json: str) -> None:
        try:
            crit = json.loads(criteria_json or "{}")
            core_tax.create_smart_collection(self._con, name, item_kind, crit)
        except (ValueError, json.JSONDecodeError) as e:
            self.message.emit(str(e))
            return
        self._refresh()
        self.smartsChanged.emit()
        self.message.emit(f"Smart collection created: {name.strip()}")

    @Slot(int, str, str)
    def update_smart(self, sc_id: int, name: str, criteria_json: str) -> None:
        try:
            crit = json.loads(criteria_json or "{}")
            core_tax.update_smart_collection(self._con, sc_id, name, crit)
        except (ValueError, json.JSONDecodeError) as e:
            self.message.emit(str(e))
            return
        self._refresh()
        self.smartsChanged.emit()

    @Slot(int)
    def delete_smart(self, sc_id: int) -> None:
        core_tax.delete_smart_collection(self._con, sc_id)
        self._refresh()
        self.smartsChanged.emit()
        self.message.emit("Smart collection deleted")

    @Slot(str, str, result="QVariantList")
    def smart_preview(self, item_kind: str, criteria_json: str) -> list:
        """Live ids for unsaved criteria — the editor dialog's match count."""
        try:
            crit = json.loads(criteria_json or "{}")
        except json.JSONDecodeError:
            return []
        return core_tax.smart_asset_ids(self._con, item_kind, crit)

    # -------------------------------------------------------- custom fields
    @Slot(str, str, str, result=int)
    def create_field(self, name: str, ftype: str, options_json: str) -> int:
        try:
            opts = json.loads(options_json or "{}")
            fid = core_tax.create_field(self._con, name, ftype, opts)
        except (ValueError, json.JSONDecodeError) as e:
            self.message.emit(str(e))
            return -1
        self._refresh()
        self.fieldsChanged.emit()
        self.message.emit(f"Field created: {name.strip()}")
        return fid

    @Slot(int)
    def delete_field(self, field_id: int) -> None:
        core_tax.delete_field(self._con, field_id)
        self._refresh()
        self.fieldsChanged.emit()
        self.message.emit("Field deleted")

    @Slot(int, int, str, str)
    def set_field_value(self, item_id: int, field_id: int,
                        value: str, kind: str = "icon") -> None:
        try:
            core_tax.set_field_value(self._con, item_id, field_id, value,
                                     kind)
        except ValueError as e:
            self.message.emit(str(e))
            return
        self.fieldsChanged.emit()

    @Slot(int, int, str)
    def generate_id(self, item_id: int, field_id: int,
                    kind: str = "icon") -> None:
        try:
            nxt = core_tax.generate_field_id(self._con, item_id, field_id,
                                             kind)
        except ValueError as e:
            self.message.emit(str(e))
            return
        self.fieldsChanged.emit()
        self.message.emit(f"Assigned {nxt}")

    # ---------------------------------------------------------------- links
    @Slot(str, int, str, int, str)
    def add_link(self, from_kind: str, from_id: int, to_kind: str,
                 to_id: int, role: str) -> None:
        try:
            core_tax.add_link(self._con, from_kind, from_id, to_kind, to_id,
                              role)
        except ValueError as e:
            self.message.emit(str(e))
            return
        self.linksChanged.emit()
        self.message.emit("Linked")

    @Slot(int)
    def remove_link(self, link_id: int) -> None:
        core_tax.remove_link(self._con, link_id)
        self.linksChanged.emit()

    @Slot(str, int, result="QVariantList")
    def links_for(self, kind: str, item_id: int) -> list:
        return core_tax.links_for(self._con, kind, item_id, "both")

    # ------------------------------------------------- generic tag operations
    # (any asset kind — the Properties panel's shared editing surface)
    @Slot(str, int, result="QVariantList")
    def tags_for(self, kind: str, item_id: int) -> list:
        return core_db.tags_for(self._con, item_id, kind)

    @Slot(str, int, str)
    def add_tag(self, kind: str, item_id: int, name: str) -> None:
        if core_db.add_tag(self._con, item_id, name, kind):
            self.message.emit(f"Tagged #{name.strip()}")
        self.fieldsChanged.emit()

    @Slot(str, int, str)
    def remove_tag(self, kind: str, item_id: int, name: str) -> None:
        core_db.remove_tag(self._con, item_id, name, kind)
        self.fieldsChanged.emit()

    @Slot(str, int, bool)
    def set_starred(self, kind: str, item_id: int, starred: bool) -> None:
        core_db.set_starred(self._con, item_id, bool(starred), kind)
        self.fieldsChanged.emit()

    @Slot(str, int, result=bool)
    def is_starred(self, kind: str, item_id: int) -> bool:
        return core_db.is_starred(self._con, item_id, kind)

    # ------------------------------------------------------------ item details
    @Slot(str, int, result="QVariantMap")
    def item_properties(self, kind: str, item_id: int) -> dict:
        """Everything the Properties panel renders for one item: tags,
        custom field values (with definitions), links, and kind-specific
        detail data — for any kind."""
        if not core_tax._item_exists(self._con, kind, item_id):
            # MISSING item (deleted under the panel, sweep, db switch):
            # NEVER return a truthy-but-empty {} — every QML binding does
            # panel.props.meta.<key>.<field>, which throws on a partial
            # payload ("Value is undefined...", frozen-build terminal
            # flood). Shape the null case like a real payload.
            return {"kind": kind, "id": item_id, "tags": [], "fields": [],
                    "links": [], "meta": {}, "starred": False}
        tags = core_db.tags_for(self._con, item_id, kind)
        fields = core_tax.asset_field_values(self._con, item_id, kind)
        links = core_tax.links_for(self._con, kind, item_id, "both")
        return {"kind": kind, "id": item_id, "tags": tags,
                "fields": fields, "links": links,
                "meta": self._kind_meta(kind, item_id),
                "starred": core_db.is_starred(self._con, item_id, kind)}

    def _kind_meta(self, kind: str, item_id: int) -> dict:
        """Kind-specific detail payload for the inspector's Details tab."""
        from ..core import colors as core_colors
        from ..core import snippets as core_snippets
        if kind == "font":
            rows = self._con.execute(
                "SELECT family FROM asset WHERE id = ?", (item_id,)).fetchone()
            family = rows["family"] if rows else ""
            files = self._con.execute(
                "SELECT COUNT(*) FROM asset WHERE kind = 'font' AND family = ?",
                (family,)).fetchone()[0]
            return {"family": family, "files": files}
        if kind == "palette":
            row = self._con.execute(
                "SELECT name FROM palette WHERE id = ?", (item_id,)).fetchone()
            return {"name": row["name"] if row else "",
                    "colors": core_colors.palette_colors(self._con, item_id)}
        if kind == "snippet":
            row = self._con.execute(
                "SELECT title, description, language, created, updated"
                " FROM snippet WHERE id = ?", (item_id,)).fetchone()
            if row is None:
                return {"title": "", "description": "", "language": "",
                        "created": "", "updated": ""}
            return {"title": row["title"],
                    "description": row["description"],
                    "language": row["language"],
                    "created": row["created"], "updated": row["updated"]}
        if kind == "icon":
            row = self._con.execute(
                "SELECT name, path FROM asset WHERE id = ?",
                (item_id,)).fetchone()
            if row is None:
                return {"name": "", "path": ""}
            return {"name": row["name"], "path": row["path"]}
        return {}

    # ---------------------------------------------------------- link targets
    @Slot(result="QVariantList")
    def link_targets(self) -> list:
        """Candidate targets for the Link-to submenus: collections,
        libraries, projects — label + id + kind, ready for QML menus."""
        out = []
        for r in self._con.execute(
                "SELECT id, name FROM collection ORDER BY name COLLATE NOCASE"
                " LIMIT 30"):
            out.append({"kind": "collection", "id": r["id"],
                        "label": r["name"]})
        for r in self._con.execute(
                "SELECT id, name FROM library_view"
                " ORDER BY name COLLATE NOCASE LIMIT 30"):
            out.append({"kind": "library", "id": r["id"], "label": r["name"]})
        for r in self._con.execute(
                "SELECT id, name FROM projects ORDER BY updated DESC LIMIT 30"):
            out.append({"kind": "project", "id": r["id"], "label": r["name"]})
        return out

    # ----------------------------------------------------------- internals
    def refresh_all(self) -> None:
        self._refresh()
        self.viewsChanged.emit()
        self.smartsChanged.emit()
        self.fieldsChanged.emit()


def ensure_taxonomy_defaults(con) -> None:
    """Seed the two demo-friendly id/label fields people expect (idempotent)."""
    core_db.ensure_defaults(con)
