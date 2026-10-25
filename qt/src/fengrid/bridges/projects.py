"""Projects bridge: the design-token coordinator pane (M4).

Thin adapter over core.projects like the other bridges: project CRUD lives
in SQLite (projects / project_asset tables), the configurator settings are
a JSON dict per project, and exports go through core.projects.export_project.
"""

from __future__ import annotations

import html as _html_mod
import json
import os
import shutil
import subprocess
import threading

from PySide6.QtCore import Property, QObject, Signal, Slot

from ..core import assetrefs as core_assetrefs
from ..core import projects as core_projects
from ..core import settings as core_settings

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
    revisionsChanged = Signal()
    askDone = Signal(str)            # local llm helper replied
    askFailed = Signal(str)

    def __init__(self, con, parent=None):
        super().__init__(parent)
        self._con = con
        self._search = ""
        self._current_id = -1
        self._current: dict = {}
        self._ask_thread = None
        self._sc_ref = None          # SourceControl bridge (optional)
        self._refresh()

    def _sc_bridge(self):
        return self._sc_ref

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
        # point source control at this project (auto git init on first
        # open — the initial snapshot commit lands with the first Save)
        sc = self._sc_bridge() if callable(getattr(self, "_sc_bridge",
                                                   None)) else None
        if sc is not None and self._current:
            sc.attach(self._current.get("name", ""), "project")

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
        old = dict(self._current.get("settings") or {})
        core_projects.update_project(self._con, self._current_id, settings=s)
        self._current = core_projects.get_project(self._con, self._current_id) or {}
        self.currentChanged.emit()
        # git: every Save is a commit on fengrid-main (bridge optional —
        # the panel is inert when the sc bridge isn't wired in QA rigs)
        sc = self._sc_bridge() if callable(getattr(self, "_sc_bridge", None)) \
            else None
        if sc is not None:
            sc.attach(self._current.get("name", ""), "project")
            sc.commit("Save: settings updated")

    def bind_source_control(self, sc) -> None:
        """__main__ wires the shared SourceControl bridge in (QA rigs may
        omit it — every sc call site tolerates its absence)."""
        self._sc_ref = sc

    # ------------------------------------------------------- batch support
    @Slot(str, result=bool)
    def batch_begin(self, label: str) -> bool:
        """Auto-branch before a bulk change (git spec: batch operations
        create a branch first, then the user reviews commit/discard).
        False = no repo attached, the operation runs unprotected."""
        sc = self._sc_ref
        if sc is None:
            return False
        return sc.batch_begin(label) is not None

    @Slot(str, bool)
    def batch_finish(self, label: str, keep: bool) -> None:
        sc = self._sc_ref
        if sc is not None:
            sc.batch_finish(label, keep)

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
            # SEC-2: the path lands inside HTML attribute values in the
            # preview document — escape it so a crafted path cannot
            # break out of the attribute (the DOM decodes entities
            # before resolving the URL, so the scheme handler still
            # receives the raw path)
            html = html.replace(arcname, "fengrid-asset://"
                                + _html_mod.escape(abspath, quote=True))
        # [[ asset ]] references (slug / GUID / path forms) expand to
        # fengrid-asset:// urls the sandboxed preview can serve
        expanded, _unresolved = core_assetrefs.expand(self._con, html)
        return expanded

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

    # ------------------------------------------------------- revisions
    @Property("QVariantList", notify=revisionsChanged)
    def revisions(self) -> list:
        if self._current_id < 0:
            return []
        return [dict(r) for r in self._con.execute(
            "SELECT id, created, label, name FROM project_revision"
            " WHERE project_id = ? ORDER BY id DESC LIMIT 50",
            (self._current_id,))]

    @Slot(str)
    def snapshot(self, label: str = "") -> None:
        """Save a revision of the current project's meta + settings."""
        if self._current_id < 0 or not self._current:
            self.message.emit("No project open")
            return
        self._con.execute(
            "INSERT INTO project_revision(project_id, label, name,"
            " description, settings) VALUES (?, ?, ?, ?, ?)",
            (self._current_id, (label or "").strip() or "manual",
             self._current.get("name", ""),
             self._current.get("description", ""),
             json.dumps(self._current.get("settings") or {})))
        self._con.commit()
        self.revisionsChanged.emit()
        self.message.emit("Revision saved")

    @Slot(int)
    def restore_revision(self, rid: int) -> None:
        row = self._con.execute(
            "SELECT name, description, settings FROM project_revision"
            " WHERE id = ?", (int(rid),)).fetchone()
        if row is None or self._current_id < 0:
            return
        try:
            settings = json.loads(row["settings"] or "{}")
        except ValueError:
            settings = {}
        core_projects.update_project(
            self._con, self._current_id, name=row["name"],
            description=row["description"], settings=settings)
        self._current = core_projects.get_project(self._con,
                                                  self._current_id) or {}
        self.currentChanged.emit()
        self._refresh()
        self.message.emit("Revision restored")

    @Slot(int)
    def delete_revision(self, rid: int) -> None:
        self._con.execute("DELETE FROM project_revision WHERE id = ?",
                          (int(rid),))
        self._con.commit()
        self.revisionsChanged.emit()

    # ------------------------------------------------------------- ask
    # the LLM chat tab pipes prompts + project context to a LOCAL helper
    # binary (`fengrid-llm`, or the `llm` CLI) — no keys, no network from
    # the app itself; a missing helper surfaces a setup note instead of
    # pretending to think.
    @Property(str, constant=True)
    def askHelper(self) -> str:
        tool = core_settings.get(self._con, "llm_command", "")
        for cand in ([tool] if tool else []) + ["fengrid-llm", "llm"]:
            if cand and shutil.which(cand):
                return cand
        return ""

    @Slot(str)
    def ask(self, prompt: str) -> None:
        helper = self.askHelper
        if not helper:
            self.askFailed.emit(
                "No local helper — install fengrid-llm (or the `llm` CLI),"
                " or set Settings → llm_command")
            return
        if self._ask_thread is not None and self._ask_thread.isAlive():
            self.askFailed.emit("A question is already running")
            return
        context = ("Project: %s — settings: %s" %
                   (self._current.get("name", ""),
                    json.dumps(self._current.get("settings") or {})))
        prompt_full = f"{context}\n\n{prompt}"
        project = self

        class _Runner(threading.Thread):
            def run(self):
                try:
                    out = subprocess.run(
                        [helper, prompt_full], capture_output=True, text=True,
                        timeout=120)
                    reply = (out.stdout or out.stderr or "").strip()
                    if not reply:
                        project.askFailed.emit("helper returned nothing")
                    else:
                        project.askDone.emit(reply[:4000])
                except Exception as exc:  # noqa: BLE001
                    project.askFailed.emit(str(exc)[:300])
                finally:
                    project._ask_thread = None

        self._ask_thread = _Runner(daemon=True)
        self._ask_thread.start()
