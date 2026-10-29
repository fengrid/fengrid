"""Taxonomy bridge: saved libraries, smart collections, custom fields,
generated IDs and links — a thin QVariantList adapter over core.taxonomy,
following the bridges/colors.py pattern (properties + notify signals, no
C++ models). The bridge holds no filter state itself: activating a
library or smart collection delegates to the pane bridges (library /
colors / code / fonts), which each keep their own filter state.

Entity inspection (Projects + saved Libraries): each carries an optional
git repository under <data-dir>/repos/<kind>-<slug> (same layout the
source-control bridge uses), and the Properties panel's Documentation /
License / Sources tabs read the repo tree — README.md, LICENSE.md, and a
git summary. Doc reads are cheap file reads; git actions run through
core.projects_git with the same argv-only discipline.
"""

from __future__ import annotations

import json
import os

from PySide6.QtCore import Property, QObject, Signal, Slot

from ..core import db as core_db
from ..core import licenses as core_licenses
from ..core import projects_git as core_git
from ..core import taxonomy as core_tax

_READ_CAP = 64_000          # chars of README/LICENSE fed to the inspector
_REPO_SUBDIR = "repos"


class Taxonomy(QObject):
    message = Signal(str)
    viewsChanged = Signal()
    smartsChanged = Signal()
    fieldsChanged = Signal()
    linksChanged = Signal()
    gitUpdated = Signal()       # any repo action → Sources tab re-reads

    def __init__(self, con, data_dir: str = "", parent=None):
        super().__init__(parent)
        self._con = con
        self._data_dir = str(data_dir or "")
        self._refresh()

    # ---------------------------------------------------------------- state
    def _refresh(self) -> None:
        self._views = []
        for v in core_tax.list_library_views(self._con):
            v["n"] = len(core_tax.library_view_assets(self._con, v["id"]))
            # per-kind counts so the rail shows a library only on panes
            # whose asset kind the view actually matches (icon vs font)
            v["counts"] = core_tax.library_view_kind_counts(
                self._con, v["id"])
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

    @Slot(str, result="QVariantList")
    def fields_for(self, kind: str) -> list:
        """Definitions scoped to one asset class (NULL = all classes)."""
        return core_tax.list_fields(self._con, kind or None)

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
    @Slot(str, str, str, str, result=int)
    def create_field(self, name: str, ftype: str, options_json: str,
                     kind: str = "") -> int:
        try:
            opts = json.loads(options_json or "{}")
            fid = core_tax.create_field(self._con, name, ftype, opts,
                                        kind or None)
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

    @Slot("QVariantList", int, str, str)
    def set_field_values_bulk(self, item_ids, field_id: int,
                              value: str, kind: str = "icon") -> None:
        try:
            core_tax.set_field_values_bulk(self._con, item_ids, field_id,
                                           value, kind)
        except ValueError as e:
            self.message.emit(str(e))
            return
        self.fieldsChanged.emit()

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

    @Slot(str, int, result="QVariantList")
    def related_by_tags(self, kind: str, item_id: int) -> list:
        """Entities of OTHER kinds sharing ≥1 tag with this item — the
        inspector's cross-type taxonomy section."""
        return core_tax.related_by_tags(self._con, kind, int(item_id))

    @Slot(str, int, str, result=bool)
    def set_slug(self, kind: str, item_id: int, slug: str) -> bool:
        """Set an object's [[ slug ]] link name (globally unique)."""
        try:
            core_db.set_slug(self._con, kind, int(item_id), str(slug or ""))
        except ValueError as e:
            self.message.emit(str(e))
            return False
        self.fieldsChanged.emit()
        return True

    @Slot(str, int, result=str)
    def guid_for(self, kind: str, item_id: int) -> str:
        """The tracked object's generated GUID (copyable in the inspector)."""
        table = core_db._SLUG_TABLE_FOR.get(kind)
        if table is None:
            return ""
        row = self._con.execute(
            f"SELECT guid FROM {table} WHERE id = ?",
            (int(item_id),)).fetchone()
        return (row["guid"] if row is not None else "") or ""

    # ------------------------------------------------------ entity inspection
    # Projects and saved Libraries each map to one git repo under
    # <data-dir>/repos/<slugify(kind:name)> — the SAME path the
    # source-control bridge uses, so both surfaces see the same history.
    def _entity_name(self, kind: str, item_id: int) -> str:
        if kind == "project":
            row = self._con.execute(
                "SELECT name FROM projects WHERE id = ?",
                (int(item_id),)).fetchone()
        elif kind == "library":
            row = self._con.execute(
                "SELECT name FROM library_view WHERE id = ?",
                (int(item_id),)).fetchone()
        else:
            return ""
        return (row["name"] if row is not None else "") or ""

    def _repo_dir(self, kind: str, label: str) -> str:
        """Repo path for an entity — empty string without a data dir."""
        if not self._data_dir or not label:
            return ""
        return os.path.join(self._data_dir, _REPO_SUBDIR,
                            core_git.slugify(f"{kind}:{label}"))

    def _entity_repo(self, kind: str, item_id: int) -> core_git.Repo | None:
        label = self._entity_name(kind, item_id)
        repo_dir = self._repo_dir(kind, label)
        if not repo_dir:
            return None
        return core_git.Repo(repo_dir)

    def _read_doc_file(self, repo_dir: str,
                       names: tuple[str, ...]) -> dict:
        """{path, exists, text, truncated} for the first matching file."""
        out = {"path": "", "exists": False, "text": "", "truncated": False}
        if not repo_dir:
            return out
        for name in names:
            p = os.path.join(repo_dir, name)
            if not os.path.isfile(p):
                continue
            out.update({"path": p, "exists": True})
            try:
                with open(p, "r", encoding="utf-8", errors="replace") as fh:
                    text = fh.read(_READ_CAP + 1)
            except OSError:
                continue
            if len(text) > _READ_CAP:
                out["text"] = text[:_READ_CAP]
                out["truncated"] = True
            else:
                out["text"] = text
            break
        return out

    def _entity_meta(self, kind: str, item_id: int) -> dict:
        """Documentation / License / Sources payloads for Projects and
        saved Libraries. Reads (never writes) the entity's repo tree."""
        label = self._entity_name(kind, item_id)
        repo_dir = self._repo_dir(kind, label)
        meta = {
            "name": label,
            "repo": {"dir": repo_dir, "exists": False},
            "readme": {"path": "", "exists": False, "text": "",
                       "truncated": False},
            "license": {"path": "", "exists": False, "standard": None},
        }
        if not repo_dir:
            return meta
        meta["repo"]["exists"] = os.path.isdir(
            os.path.join(repo_dir, ".git"))
        readme = self._read_doc_file(
            repo_dir, ("README.md", "README.markdown", "README"))
        meta["readme"] = readme
        lic = self._read_doc_file(
            repo_dir, ("LICENSE.md", "LICENSE.txt", "LICENSE", "COPYING",
                       "COPYING.txt", "LICENCE.md"))
        meta["license"] = {
            "path": lic["path"], "exists": lic["exists"],
            "standard": None if not lic["exists"]
            else core_licenses.recognize(lic["text"]),
        }
        return meta

    # ------------------------------------------------------------- git slots
    def _git_repo(self, kind: str, item_id: int) -> core_git.Repo | None:
        """The entity's repo, or None after emitting a message when
        git is unusable / the repo isn't initialized yet."""
        repo = self._entity_repo(kind, item_id)
        if repo is None:
            self.message.emit("No repository for this item yet —"
                              " initialize it from the Sources tab")
            return None
        if not repo.exists():
            self.message.emit("Repository not initialized —"
                              " use Initialize first")
            return None
        return repo

    @Slot(str, int, result="QVariantMap")
    def git_summary(self, kind: str, item_id: int) -> dict:
        """Repo snapshot for the Sources tab (branch, remote, status
        counts, last commit). Read-only — never initializes."""
        repo = self._entity_repo(kind, item_id)
        label = self._entity_name(kind, item_id)
        out = {"kind": kind, "id": int(item_id), "name": label}
        if repo is None or not repo.path:
            out["exists"] = False
            return out
        out["path"] = str(repo.path)
        if not repo.exists():
            out["exists"] = False
            return out
        out["exists"] = True
        try:
            st = repo.status()
        except core_git.GitError as e:
            # fresh init has no commits — branch read fails; report the
            # repo as alive but unborn
            out["branch"] = ""
            out["staged"] = []
            out["unstaged"] = []
            out["untracked"] = []
            out["clean"] = False
            out["note"] = str(e)
            return out
        out.update({
            "branch": st.get("branch", ""),
            "staged": st.get("staged", []),
            "unstaged": st.get("unstaged", []),
            "untracked": st.get("untracked", []),
            "clean": st.get("clean", False),
        })
        remotes = repo.remotes()
        out["remote"] = next(iter(remotes.values()), "") if remotes else ""
        try:
            history = repo.log(1)
        except core_git.GitError:
            history = []
        if history:
            entry = history[0]
            out["last_commit"] = {
                "sha": entry.get("sha", ""),
                "subject": entry.get("message", ""),
                "when": entry.get("ts", ""),
            }
        return out

    @Slot(str, int)
    def git_init(self, kind: str, item_id: int) -> None:
        repo = self._entity_repo(kind, item_id)
        if repo is None:
            self.message.emit("Cannot locate a repo folder for this item")
            return
        if repo.exists():
            self.message.emit("Repository already initialized")
            return
        try:
            repo.init()
        except core_git.GitError as e:
            self.message.emit(f"git init failed: {e}")
            return
        self.message.emit("Repository initialized")
        self.gitUpdated.emit()

    @Slot(str, int, str)
    def git_commit(self, kind: str, item_id: int, message: str) -> None:
        repo = self._git_repo(kind, item_id)
        if repo is None:
            return
        try:
            sha = repo.commit_all((message or "").strip())
        except core_git.GitError as e:
            self.message.emit(f"git commit failed: {e}")
            return
        self.message.emit("Nothing to commit"
                          if sha is None else f"Committed {sha[:10]}")
        self.gitUpdated.emit()

    @Slot(str, int)
    def git_push(self, kind: str, item_id: int) -> None:
        repo = self._git_repo(kind, item_id)
        if repo is None:
            return
        remotes = repo.remotes()
        remote = next(iter(remotes), "origin")
        try:
            repo.push(remote)
        except core_git.GitError as e:
            self.message.emit(f"git push failed: {e}")
            return
        self.message.emit(f"Pushed to {remote}")
        self.gitUpdated.emit()

    @Slot(str, int)
    def git_pull(self, kind: str, item_id: int) -> None:
        repo = self._git_repo(kind, item_id)
        if repo is None:
            return
        remotes = repo.remotes()
        remote = next(iter(remotes), "origin")
        try:
            repo.pull(remote)
        except core_git.GitError as e:
            self.message.emit(f"git pull failed: {e}")
            return
        self.message.emit(f"Pulled from {remote}")
        self.gitUpdated.emit()

    @Slot(str, int, str, bool)
    def git_commit_push(self, kind: str, item_id: int, message: str,
                        push: bool) -> None:
        """Save & Push — the Sources tab's one-click sync."""
        repo = self._git_repo(kind, item_id)
        if repo is None:
            return
        try:
            sha = repo.commit_all((message or "").strip())
            if sha is None:
                self.message.emit("Nothing to commit")
            else:
                self.message.emit(f"Committed {sha[:10]}")
            if push:
                remotes = repo.remotes()
                remote = next(iter(remotes), "origin")
                repo.push(remote)
                self.message.emit(f"Pushed to {remote}")
        except core_git.GitError as e:
            self.message.emit(f"git failed: {e}")
            return
        self.gitUpdated.emit()

    @Slot(str, int)
    def git_discard(self, kind: str, item_id: int) -> None:
        """Hard rollback of the working tree — QML confirms first."""
        repo = self._git_repo(kind, item_id)
        if repo is None:
            return
        try:
            repo.discard_all()
        except core_git.GitError as e:
            self.message.emit(f"git discard failed: {e}")
            return
        self.message.emit("Working tree reset to HEAD")
        self.gitUpdated.emit()

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
            # payload ("Value is undefined…", frozen-build terminal
            # flood). Shape the null case like a real payload.
            meta = {}
            if kind in ("project", "library"):
                meta = self._entity_meta(kind, item_id)
            return {"kind": kind, "id": item_id, "tags": [], "fields": [],
                    "links": [], "meta": self._shaped_meta(meta),
                    "starred": False}
        tags = core_db.tags_for(self._con, item_id, kind)
        fields = core_tax.asset_field_values(self._con, item_id, kind)
        links = core_tax.links_for(self._con, kind, item_id, "both")
        return {"kind": kind, "id": item_id, "tags": tags,
                "fields": fields,
                "links": links,
                "meta": self._shaped_meta(self._kind_meta(kind, item_id)),
                "starred": core_db.is_starred(self._con, item_id, kind)}

    def _shaped_meta(self, meta: dict) -> dict:
        """Merge the full meta shape the QML panels read over a
        kind-specific payload. The Properties panel evaluates EVERY
        page's bindings (docs, license, font, palette, snippet) against
        whatever payload is current — including during the itemKind
        change window before reload() swaps payloads, and at startup
        against the last-saved palette's row (#58). A key the payload
        lacks reads as `undefined`, which the engine logs as
        'Unable to assign [undefined] to bool/QString', and a missing
        list's `.length` throws TypeError. Defaults first; the kind
        payload wins on conflicts."""
        shaped = {"readme": {"exists": False, "path": "", "text": ""},
                  "license": {"exists": False, "path": "",
                              "standard": None},
                  "family": "", "name": "", "path": "", "title": "",
                  "colors": []}
        shaped.update(meta or {})
        return shaped

    def _kind_meta(self, kind: str, item_id: int) -> dict:
        """Kind-specific detail payload for the inspector's pages."""
        from ..core import colors as core_colors
        from ..core import snippets as core_snippets
        if kind == "font":
            rows = self._con.execute(
                "SELECT family FROM asset WHERE id = ?", (item_id,)).fetchone()
            family = rows["family"] if rows else ""
            files = self._con.execute(
                "SELECT COUNT(*) FROM asset WHERE kind = 'font'"
                " AND family = ?", (family,)).fetchone()[0]
            return {"family": family, "files": files}
        if kind == "palette":
            row = self._con.execute(
                "SELECT name FROM palette WHERE id = ?",
                (item_id,)).fetchone()
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
        if kind in ("project", "library"):
            # Documentation / License / Sources tabs read the entity's
            # repo tree under <data-dir>/repos/<kind>-<slug>
            return self._entity_meta(kind, item_id)
        if kind == "preset":
            row = self._con.execute(
                "SELECT name, kind, summary, tags, remote FROM"
                " preset_library WHERE id = ?", (item_id,)).fetchone()
            if row is None:
                return {}
            n = self._con.execute(
                "SELECT COUNT(*) FROM preset_entry WHERE library_id = ?",
                (item_id,)).fetchone()[0]
            return {"name": row["name"], "pack_kind": row["kind"],
                    "summary": row["summary"], "entries": n,
                    "remote": bool(row["remote"])}
        if kind == "preset_entry":
            row = self._con.execute(
                "SELECT * FROM preset_entry WHERE id = ?",
                (item_id,)).fetchone()
            if row is None:
                return {}
            return {"name": row["name"], "repo": row["repo"],
                    "url": row["url"], "branch": row["branch"],
                    "description": row["description"],
                    "license": row["license"],
                    "homepage": row["homepage"],
                    "downloaded": bool(row["downloaded"]),
                    "local_path": row["local_path"]}
        return {}

    # ----------------------------------------------------------- internals
    def refresh_all(self) -> None:
        self._refresh()
        self.viewsChanged.emit()
        self.smartsChanged.emit()
        self.fieldsChanged.emit()


def ensure_taxonomy_defaults(con) -> None:
    """Seed the two demo-friendly id/label fields people expect (idempotent)."""
    core_db.ensure_defaults(con)
