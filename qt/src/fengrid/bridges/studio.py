"""Studio bridge — QML facade over core.studio + core.docker.

The Projects pane's multi-screen workspace (Design canvas, Templates,
Docker, Docs) talks to this bridge. It binds to the projects bridge so
"current project" stays the single source of truth, and owns:

  pages/blocks  — page CRUD + tree ops with a selection model
  rendering     — the page HTML the live preview loads (tokens from the
                  project settings + [[ asset ]] refs resolved)
  templates     — template vars + instance creation (tenants)
  docker        — build/run/stop/logs + container filesystem access
"""
from __future__ import annotations

import json
import os
import tempfile
import threading

from PySide6.QtCore import Property, QObject, Signal, Slot

from ..core import studio as core_studio
from ..core import docker as core_docker
from ..core import projects as core_projects
from ..core import db as core_db


class Studio(QObject):
    message = Signal(str)
    pagesChanged = Signal()
    pageChanged = Signal()
    selectionChanged = Signal()
    dockerChanged = Signal()
    dockerLog = Signal(str)

    def __init__(self, con, parent=None):
        super().__init__(parent)
        self._con = con
        # cheap idempotent migration — covers embeds (API server, QA
        # rigs) that never pass through __main__'s startup path
        core_studio.migrate(con)
        self._projects = None            # projects bridge (bind_projects)
        self._page_id = -1
        self._sel_id = ""
        self._docker_thread = None

    # ----------------------------------------------------------- binding
    def bind_projects(self, projects_bridge) -> None:
        self._projects = projects_bridge
        projects_bridge.currentChanged.connect(self._project_switched)

    def _project_switched(self) -> None:
        self._page_id = -1
        self._sel_id = ""
        pages = self._pages_list()
        if pages:
            self._page_id = pages[0]["id"]
        self.pagesChanged.emit()
        self.pageChanged.emit()
        self.selectionChanged.emit()

    def _pid(self) -> int:
        if self._projects is None:
            return -1
        return int(self._projects.currentId)

    def _pages_list(self) -> list:
        pid = self._pid()
        return core_studio.list_pages(self._con, pid) if pid > 0 else []

    def _docker_cfg(self) -> dict:
        pid = self._pid()
        if pid < 0:
            return {}
        row = self._con.execute(
            "SELECT settings FROM projects WHERE id = ?", (pid,)).fetchone()
        s = json.loads(row["settings"] or "{}") if row else {}
        cfg = s.get("docker") or {}
        return dict(cfg) if isinstance(cfg, dict) else {}

    def _require_page(self) -> dict:
        pg = core_studio.get_page(self._con, self._page_id)
        if pg is None:
            raise core_studio.StudioError("no page open")
        return pg

    # --------------------------------------------------------- properties
    @Property("QVariantList", notify=pagesChanged)
    def pages(self) -> list:
        return self._pages_list()

    @Property(int, notify=pageChanged)
    def currentPageId(self) -> int:
        return self._page_id

    @Property("QVariantList", notify=pageChanged)
    def pagePayload(self) -> list:
        try:
            return self._require_page()["payload"]
        except core_studio.StudioError:
            return []

    @Property(str, notify=selectionChanged)
    def selectedBlockId(self) -> str:
        return self._sel_id

    @Property("QVariant", notify=selectionChanged)
    def selectedBlock(self):
        if not self._sel_id:
            return {}
        try:
            hit = core_studio._walk(self._require_page()["payload"],
                                    self._sel_id)
            return hit[2] if hit else {}
        except core_studio.StudioError:
            return {}

    @Property(bool, constant=True)
    def dockerOk(self) -> bool:
        return core_docker.docker_available()

    # ------------------------------------------------------------ pages
    @Slot(str)
    def addPage(self, name: str) -> None:
        pid = self._pid()
        if pid < 0:
            return
        try:
            self._page_id = core_studio.create_page(self._con, pid, name)
        except core_studio.StudioError as e:
            self.message.emit(str(e))
            return
        self.pagesChanged.emit()
        self.pageChanged.emit()

    @Slot(int, str)
    def renamePage(self, page_id: int, name: str) -> None:
        try:
            core_studio.rename_page(self._con, page_id, name)
        except core_studio.StudioError as e:
            self.message.emit(str(e))
            return
        self.pagesChanged.emit()

    @Slot(int)
    def deletePage(self, page_id: int) -> None:
        core_studio.delete_page(self._con, page_id)
        if self._page_id == page_id:
            self._page_id = -1
            pages = self.pages
            self._page_id = pages[0]["id"] if pages else -1
        self.pagesChanged.emit()
        self.pageChanged.emit()

    @Slot(int)
    def setPage(self, page_id: int) -> None:
        self._page_id = int(page_id)
        self._sel_id = ""
        self.pageChanged.emit()
        self.selectionChanged.emit()

    # ----------------------------------------------------------- blocks
    @Slot(str)
    def addBlock(self, btype: str) -> None:
        """Insert into the selected section/grid, else at page root."""
        self._mutate(lambda pg: core_studio.add_block(
            pg, btype, _default_props(btype),
            parent_id=self._sel_id if self._container_ok(pg) else None),
            label=f"Add {btype}")

    def _container_ok(self, pg: dict) -> bool:
        if not self._sel_id:
            return False
        hit = core_studio._walk(pg["payload"], self._sel_id)
        return bool(hit and hit[2]["type"] in ("section", "grid"))

    @Slot(int)
    def moveBlock(self, delta: int) -> None:
        self._mutate(lambda pg: core_studio.move_block(pg, self._sel_id,
                                                       delta), "Reorder")

    @Slot()
    def removeBlock(self) -> None:
        self._mutate(lambda pg: core_studio.remove_block(pg, self._sel_id),
                     "Remove block")

    @Slot()
    def duplicateBlock(self) -> None:
        self._mutate(lambda pg: core_studio.duplicate_block(pg, self._sel_id),
                     "Duplicate block")

    @Slot(str)
    def selectBlock(self, block_id: str) -> None:
        self._sel_id = block_id or ""
        self.selectionChanged.emit()

    @Slot(str)
    def setProps(self, props_json: str) -> None:
        try:
            props = json.loads(props_json or "{}")
        except ValueError:
            self.message.emit("Inspector: invalid JSON")
            return
        self._mutate(lambda pg: core_studio.set_block_props(
            pg, self._sel_id, props), "Edit properties")

    def _mutate(self, fn, label: str) -> None:
        """Run a tree op + persist in one step (blocks are cheap to
        rewrite wholesale; ids are stable so the canvas selection and
        the editor undo survive)."""
        try:
            pg = self._require_page()
            fn(pg)
            core_studio.save_page(self._con, pg["id"], pg["payload"])
        except core_studio.StudioError as e:
            self.message.emit(str(e))
            return
        self.pageChanged.emit()
        self.selectionChanged.emit()

    # -------------------------------------------------------- rendering
    @Slot(result=str)
    def pageHtml(self) -> str:
        """Full HTML document for the live preview: token CSS from the
        project settings + the rendered block tree."""
        pid = self._pid()
        if pid < 0:
            return "<html><body><p style='font-family:sans-serif'>No" \
                   " project open</p></body></html>"
        try:
            pg = self._require_page()
        except core_studio.StudioError:
            return "<html><body><p>Add a page to start designing</p>" \
                   "</body></html>"
        project = core_projects.get_project(self._con, pid) or {}
        s = project.get("settings") or {}
        g = core_projects._gather(self._con, project)
        lines, _roles = core_projects.build_tokens("fg", s, g["palettes"])
        body = core_studio.render_blocks(self._con, pg["payload"])
        return _page_doc("\n".join(lines), body,
                         str(s.get("prefix", "fg")))

    # -------------------------------------------------------- templates
    @Property("QVariantList", notify=pagesChanged)
    def templateVars(self) -> list:
        s = self._settings()
        return [{"name": k, "value": v}
                for k, v in (s.get("template_vars") or {}).items()]

    def _settings(self) -> dict:
        pid = self._pid()
        if pid < 0:
            return {}
        row = self._con.execute(
            "SELECT settings FROM projects WHERE id = ?", (pid,)).fetchone()
        return json.loads(row["settings"] or "{}") if row else {}

    # instance registry (Templates screen)
    instancesChanged = Signal()

    @Property("QVariantList", notify=instancesChanged)
    def instancesList(self) -> list:
        pid = self._pid()
        return core_studio.instances_of(self._con, pid) if pid > 0 else []

    @Slot()
    def refreshInstances(self) -> None:
        self.instancesChanged.emit()

    @Slot(str, str)
    def setVar(self, name: str, value: str) -> None:
        pid = self._pid()
        if pid < 0:
            return
        try:
            s = dict(self._settings())
            s.setdefault("template_vars", {})
            if value == "":
                s["template_vars"].pop(name, None)   # empty = delete
            else:
                s = core_studio.set_template_var(s, name, value)
        except core_studio.StudioError as e:
            self.message.emit(str(e))
            return
        core_projects.update_project(self._con, pid, settings=s)
        self.pagesChanged.emit()
        self.instancesChanged.emit()
        self.message.emit(f"Variable {name} saved" if value
                          else f"Variable {name} removed")

    @Slot(str, str, result="QVariant")
    def instantiate(self, name: str, overrides_json: str):
        pid = self._pid()
        if pid < 0:
            return -1
        try:
            overrides = json.loads(overrides_json or "{}")
            new_id = core_studio.instantiate_template(
                self._con, pid, name, overrides)
        except (core_studio.StudioError, ValueError) as e:
            self.message.emit(str(e))
            return -1
        self.pagesChanged.emit()
        self.instancesChanged.emit()
        self.message.emit(f"Instance created: {name}")
        return new_id

    @Slot(result="QVariant")
    def usage(self):
        pid = self._pid()
        return core_studio.describe_usage(self._con, pid) if pid > 0 else {}

    # ----------------------------------------------------------- docker
    # config lives in project settings under "docker"
    @Property("QVariant", notify=dockerChanged)
    def dockerCfg(self):
        return self._docker_cfg()

    @Slot(str)
    def setDockerCfg(self, cfg_json: str) -> None:
        pid = self._pid()
        if pid < 0:
            return
        try:
            cfg = json.loads(cfg_json or "{}")
        except ValueError:
            self.message.emit("Docker config: invalid JSON")
            return
        row = self._con.execute(
            "SELECT settings FROM projects WHERE id = ?", (pid,)).fetchone()
        s = json.loads(row["settings"] or "{}") if row else {}
        s["docker"] = cfg
        core_projects.update_project(self._con, pid, settings=s)
        self.dockerChanged.emit()
        self.message.emit("Docker config saved")

    @Slot()
    def dockerBuild(self) -> None:
        """Build the project image in a background thread; progress goes
        to dockerLog, completion to dockerChanged (the CLI streams build
        output; we tail it from the subprocess pipe)."""
        pid = self._pid()
        if pid < 0:
            return
        cfg = self._docker_cfg()
        tag = str(cfg.get("image") or "").strip() \
            or f"fengrid/project-{pid}:latest"
        ctx = str(cfg.get("context") or "").strip()
        if not ctx or not os.path.isdir(ctx):
            self.message.emit(
                "Set a build context directory (the exported project "
                "folder) before building")
            return

        def work():
            try:
                proc = _streamed(["build", "-t", tag, ctx])
                self.dockerLog.emit(proc or "build finished")
                self.message.emit(f"Built {tag}")
            except core_docker.DockerError as e:
                self.message.emit(f"Build failed: {e}")
            finally:
                self.dockerChanged.emit()

        self._spawn(work)

    @Slot()
    def dockerRun(self) -> None:
        pid = self._pid()
        if pid < 0:
            return
        cfg = self._docker_cfg()
        image = str(cfg.get("image") or "").strip() \
            or f"fengrid/project-{pid}:latest"
        name = str(cfg.get("name") or "").strip() \
            or f"fengrid-project-{pid}"
        try:
            core_docker.run(image, name,
                            ports=list(cfg.get("ports") or []),
                            volumes=list(cfg.get("volumes") or []),
                            env=dict(cfg.get("env") or {}))
            self.message.emit(f"Container {name} running")
        except core_docker.DockerError as e:
            self.message.emit(f"Run failed: {e}")
        self.dockerChanged.emit()

    @Slot()
    def dockerStop(self) -> None:
        cfg = self._docker_cfg()
        name = str(cfg.get("name") or "").strip()
        if not name:
            return
        try:
            core_docker.stop(name)
            self.message.emit(f"Stopped {name}")
        except core_docker.DockerError as e:
            self.message.emit(f"Stop failed: {e}")
        self.dockerChanged.emit()

    @Slot()
    def dockerRm(self) -> None:
        cfg = self._docker_cfg()
        name = str(cfg.get("name") or "").strip()
        if not name:
            return
        try:
            core_docker.rm(name, force=True)
            self.message.emit(f"Removed {name}")
        except core_docker.DockerError as e:
            self.message.emit(f"Remove failed: {e}")
        self.dockerChanged.emit()

    @Slot(int)
    def dockerLogs(self, tail: int = 200) -> None:
        cfg = self._docker_cfg()
        name = str(cfg.get("name") or "").strip()
        if not name:
            return
        try:
            self.dockerLog.emit(core_docker.logs(name, tail))
        except core_docker.DockerError as e:
            self.message.emit(f"Logs failed: {e}")

    @Slot(result="QVariant")
    def dockerState(self):
        cfg = self._docker_cfg()
        name = str(cfg.get("name") or "").strip()
        return core_docker.state(name) if name else {"exists": False}

    @Slot(str, result="QVariant")
    def dockerBrowse(self, path: str):
        cfg = self._docker_cfg()
        name = str(cfg.get("name") or "").strip()
        if not name:
            return []
        try:
            return core_docker.browse(name, path or "/")
        except core_docker.DockerError as e:
            self.message.emit(f"Browse failed: {e}")
            return []

    @Slot(str, result=str)
    def dockerCopyOut(self, path: str) -> str:
        """Copy a container path into a scratch dir under the profile
        cache; returns the host path so scans/imports can chew on it."""
        cfg = self._docker_cfg()
        name = str(cfg.get("name") or "").strip()
        if not name:
            return ""
        dest = os.path.join(tempfile.gettempdir(),
                            "fengrid-container-copy")
        try:
            out = core_docker.copy_out(name, path, dest)
            self.message.emit(f"Copied to {out}")
            return out
        except core_docker.DockerError as e:
            self.message.emit(f"Copy failed: {e}")
            return ""

    def _spawn(self, fn) -> None:
        if self._docker_thread is not None and \
                self._docker_thread.is_alive():
            self.message.emit("A docker operation is already running")
            return
        self._docker_thread = threading.Thread(target=fn, daemon=True)
        self._docker_thread.start()


def _streamed(args: list[str]) -> str:
    """Run a docker command capturing combined output (for build)."""
    import subprocess
    if not core_docker.docker_available():
        raise core_docker.DockerError("docker is not available", 127)
    proc = subprocess.run(["docker", *args], capture_output=True,
                          text=True, timeout=core_docker.LONG_TIMEOUT)
    if proc.returncode != 0:
        raise core_docker.DockerError(
            (proc.stderr or proc.stdout).strip()[:400], proc.returncode)
    return (proc.stdout or "").strip()


def _default_props(btype: str) -> dict:
    return {
        "heading": {"text": "Heading", "level": 2},
        "text": {"text": "Double-click to edit this text."},
        "button": {"text": "Get started", "href": "#"},
        "spacer": {"height": 24},
        "grid": {"columns": 3},
        "section": {"class": "block"},
    }.get(btype, {})


def _page_doc(token_css: str, body_html: str, prefix: str) -> str:
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<style>{token_css}\n"
        "body{margin:0;padding:32px;background:var(--%s-bg);"
        "color:var(--%s-ink);font-family:var(--%s-font-body);"
        "font-size:var(--%s-fs-base)}\n"
        "h1,h2,h3{font-family:var(--%s-font-head);margin:.4em 0}\n"
        ".fg-button{display:inline-block;padding:10px 18px;"
        "border-radius:var(--%s-radius);background:var(--%s-accent);"
        "color:var(--%s-bg);text-decoration:none}\n"
        ".fg-block-missing{color:#F5C25C;font-family:monospace;"
        "border:1px dashed var(--%s-border);padding:8px;border-radius:6px}\n"
        "img{max-width:100%%}\n"
        "</style></head><body>%s</body></html>"
        % (prefix, prefix, prefix, prefix, prefix, prefix, prefix,
           prefix, prefix, body_html))
