"""Projects bridge: the design-token coordinator pane (M4).

Thin adapter over core.projects like the other bridges: project CRUD lives
in SQLite (projects / project_asset tables), the configurator settings are
a JSON dict per project, and exports go through core.projects.export_project.
"""

from __future__ import annotations

import json
import os

from PySide6.QtCore import Property, QObject, Signal, Slot

from ..core import projects as core_projects

_ROLES = ("bg", "surface", "ink", "muted", "accent", "border")


def _merged_settings(raw: str | None) -> dict:
    """Stored settings overlaid on the defaults, so newly added keys appear
    on old projects without a migration."""
    try:
        stored = json.loads(raw or "{}")
    except (ValueError, TypeError):
        stored = {}
    s = json.loads(json.dumps(core_projects.DEFAULT_SETTINGS))
    if isinstance(stored, dict):
        for k, v in stored.items():
            if k == "colors" and isinstance(v, dict):
                s["colors"].update(v)
            elif k == "type" and isinstance(v, dict):
                s["type"].update(v)
            elif k == "preview" and isinstance(v, dict):
                s["preview"].update(v)
            else:
                s[k] = v
    return s


class Projects(QObject):
    message = Signal(str)
    projectsChanged = Signal()
    currentChanged = Signal()
    assetsChanged = Signal()
    exportDone = Signal(str)
    exportFailed = Signal(str)

    def __init__(self, con, parent=None):
        super().__init__(parent)
        self._con = con
        self._search = ""
        self._current_id = -1
        self._current: dict = {}
        self._refresh()

    # ------------------------------------------------------------ properties

    def _refresh(self):
        self._projects = core_projects.list_projects(self._con, self._search)
        self.projectsChanged.emit()

    @Property(list, notify=projectsChanged)
    def projects(self):
        return self._projects

    @Property(int, notify=currentChanged)
    def currentId(self):
        return self._current_id

    @Property("QVariant", notify=currentChanged)
    def current(self):
        return self._current

    @Property("QVariant", notify=currentChanged)
    def settings(self):
        return self._current.get("settings", {})

    @Property("QVariant", notify=assetsChanged)
    def assets(self):
        return self._current.get("assets", [])

    @Property(int, constant=True)
    def projectCount(self):
        return len(self._projects)

    @Property("QVariant", constant=True)
    def roles(self):
        return list(_ROLES)

    # ---------------------------------------------------------------- slots

    @Slot(str)
    def set_search(self, q: str):
        self._search = q.strip()
        self._refresh()

    @Slot(str, str, str)
    def create(self, name: str, description: str = "", tags: str = ""):
        pid = core_projects.create_project(self._con, name, description, tags)
        self.open(pid)
        self.message.emit("Project created: " + (name.strip() or "Untitled project"))

    @Slot(int)
    def open(self, pid: int):
        self._current_id = pid
        self._current = core_projects.get_project(self._con, pid) or {}
        self.currentChanged.emit()
        self.assetsChanged.emit()

    @Slot()
    def new_project(self):
        self.create("Untitled project")

    @Slot(int)
    def remove(self, pid: int):
        core_projects.delete_project(self._con, pid)
        if self._current_id == pid:
            self._current_id = -1
            self._current = {}
            self.currentChanged.emit()
            self.assetsChanged.emit()
        self._refresh()
        self.message.emit("Project deleted")

    @Slot(str, str)
    def update_meta(self, field: str, value: str):
        if self._current_id < 0:
            return
        if field not in ("name", "description", "tags"):
            return
        core_projects.update_project(self._con, self._current_id, **{field: value})
        self._current[field] = value
        self.currentChanged.emit()
        self._refresh()

    @Slot(str)
    def update_settings(self, settings_json: str):
        if self._current_id < 0:
            return
        try:
            s = json.loads(settings_json)
        except ValueError as exc:
            self.message.emit("Bad settings JSON: %s" % exc)
            return
        core_projects.update_project(self._con, self._current_id, settings=s)
        self._current = core_projects.get_project(self._con, self._current_id) or {}
        self.currentChanged.emit()

    @Slot(str, str, str)
    def set_setting(self, path: str, value: str, vtype: str):
        """Convenience setter for one nested key: path in
        'prefix' | 'colors.<role>' | 'type.<key>' | 'preview.<key>'."""
        if self._current_id < 0:
            return
        s = self._current.get("settings") or {}
        try:
            if path == "prefix":
                s["prefix"] = value
            elif path.startswith("colors."):
                key = path.split(".", 1)[1]
                if key == "radius":
                    s.setdefault("colors", {})["radius"] = int(float(value or 0))
                else:
                    s.setdefault("colors", {})[key] = value
            elif path.startswith("type."):
                key = path.split(".", 1)[1]
                if key == "baseSize":
                    s.setdefault("type", {})["baseSize"] = int(float(value or 0))
                elif key == "scale":
                    s.setdefault("type", {})["scale"] = float(value or 1.25)
                else:
                    s.setdefault("type", {})[key] = value
            elif path.startswith("preview."):
                key = path.split(".", 1)[1]
                if key == "snippetId":
                    s.setdefault("preview", {})["snippetId"] = int(value) if value else None
                else:
                    s.setdefault("preview", {})[key] = value
            elif path == "iconSize":
                s["iconSize"] = int(float(value or 0))
            else:
                return
        except (TypeError, ValueError):
            self.message.emit("Bad value for " + path)
            return
        core_projects.update_project(self._con, self._current_id, settings=s)
        self._current = core_projects.get_project(self._con, self._current_id) or {}
        self.currentChanged.emit()

    @Slot(str, int, str)
    def apply_palette(self, palette_id, roles_start: int = 0, role_order: str = ""):
        """Positional role assignment: palette colors fill the six roles in
        order (0.x behaviour) — pass a comma list to reorder, e.g.
        'bg,surface,accent,muted,ink,border'."""
        if self._current_id < 0:
            return
        try:
            pid = int(palette_id)
        except (TypeError, ValueError):
            return
        from ..core import colors as core_colors
        cols = core_colors.palette_colors(self._con, pid)
        hexes = [c["hex"] for c in cols]
        if not hexes:
            self.message.emit("Palette has no colors")
            return
        s = self._current.get("settings") or {}
        order = [r.strip() for r in role_order.split(",") if r.strip()] \
            or list(_ROLES)
        colors = s.setdefault("colors", {})
        for i, role in enumerate(order):
            if i < len(hexes):
                colors[role] = hexes[i]
        colors.setdefault("radius", s["colors"].get("radius", 10))
        s["paletteId"] = pid
        core_projects.update_project(self._con, self._current_id, settings=s)
        self._current = core_projects.get_project(self._con, self._current_id) or {}
        self.currentChanged.emit()
        self.message.emit("Palette applied to roles")

    # ------------------------------------------------------------- assets

    @Slot(str, int, str)
    def add_asset(self, kind: str, asset_id: int, label: str = ""):
        if self._current_id < 0:
            return
        if not core_projects.add_asset(self._con, self._current_id, kind,
                                       int(asset_id), label):
            self.message.emit("Asset not found in the library: %s #%s"
                              % (kind, asset_id))
            return
        self._current = core_projects.get_project(self._con, self._current_id) or {}
        self.assetsChanged.emit()
        self._refresh()

    @Slot(int)
    def remove_asset(self, row_id: int):
        if self._current_id < 0:
            return
        core_projects.remove_asset(self._con, self._current_id, row_id)
        self._current = core_projects.get_project(self._con, self._current_id) or {}
        self.assetsChanged.emit()
        self._refresh()

    # picker sources for the add-asset dialogs
    @Slot(result="QVariant")
    def icon_options(self):
        rows = self._con.execute(
            "SELECT id, name, path FROM asset WHERE kind = 'icon'"
            " ORDER BY name LIMIT 500").fetchall()
        return [{"id": r["id"], "name": r["name"]} for r in rows]

    @Slot(result="QVariant")
    def font_options(self):
        rows = self._con.execute(
            "SELECT id, family, name FROM asset WHERE kind = 'font'"
            " ORDER BY family, name LIMIT 500").fetchall()
        return [{"id": r["id"], "name": (r["family"] + " · " + r["name"])
                 if r["family"] else r["name"]} for r in rows]

    @Slot(result="QVariant")
    def snippet_options(self):
        rows = self._con.execute(
            "SELECT id, title FROM snippet ORDER BY title LIMIT 500").fetchall()
        return [{"id": r["id"], "name": r["title"]} for r in rows]

    @Slot(result="QVariant")
    def palette_options(self):
        rows = self._con.execute(
            "SELECT id, name FROM palette ORDER BY name LIMIT 500").fetchall()
        return [{"id": r["id"], "name": r["name"]} for r in rows]

    @Slot(result="QVariant")
    def family_options(self):
        """Scanned font family names for the type pickers (from the same
        index the Fonts pane uses)."""
        from ..core import fonts as core_fonts
        return [f["family"] for f in core_fonts.families(self._con)]

    # ------------------------------------------------------------ preview/export

    @Slot(result="QVariant")
    def preview_html(self):
        """The boilerplate with tokens inlined — rendered in the sandboxed
        preview. Each attached icon/font is rewritten to its absolute
        fengrid-asset:// url (the scheme allowlists exactly the scan index,
        so nothing unscanned can load)."""
        if self._current_id < 0 or not self._current:
            return ""
        g = core_projects._gather(self._con, self._current)
        html = core_projects.build_site_html(self._con, self._current, g,
                                             inline_css=True)
        for a, (arcname, abspath) in g["icons"] + g["fonts"]:
            html = html.replace(arcname, "fengrid-asset://" + abspath)
        return html

    @Slot(str, str)
    def export(self, dest: str, fmt: str):
        if self._current_id < 0 or not self._current:
            self.exportFailed.emit("No project open")
            return
        try:
            dest = os.path.expanduser(str(dest))
            info = core_projects.export_project(self._con, self._current,
                                                dest, fmt)
            self.exportDone.emit(info["path"])
        except Exception as exc:  # noqa: BLE001 — surfaced to the UI
            self.exportFailed.emit(str(exc)[:300])
