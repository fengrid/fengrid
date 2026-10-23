"""Source-control bridge — one git repo per Project/Library, surfaced to
QML as a GittyUp/VS Code-style panel.

Follows the bridges/projects.py pattern: QVariant properties with notify
signals, plain-argv git via core.projects_git. The repo root is
<data_dir>/repos/<kind>-<slug> — outside the database, inside the app's
data dir, so backup/restore carries it and nothing escapes the user's
profile.

The bridge owns no git logic, only binding: init-on-demand, status
polling, commit/branch/merge/delete/push slots, and batch-operation
lifecycle for the Projects pane's bulk actions.

Perf note: gitAvailable/lfsAvailable are CACHED module-level probes —
a sync subprocess inside a QML binding (re-evaluated on every settings
interaction) froze the Settings screen.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Property, QObject, Signal, Slot

from ..core import projects_git as core_git
from ..core import settings as core_settings

_GIT_OK: bool | None = None
_LFS_OK: bool | None = None


def _probe_git() -> bool:
    global _GIT_OK
    if _GIT_OK is None:
        _GIT_OK = core_git.git_available()
    return _GIT_OK


def _probe_lfs() -> bool:
    global _LFS_OK
    if _LFS_OK is None:
        _LFS_OK = core_git.lfs_available()
    return _LFS_OK


class SourceControl(QObject):
    message = Signal(str)
    statusChanged = Signal()
    logChanged = Signal()
    branchesChanged = Signal()
    repoChanged = Signal()          # init/deinit — the panel re-renders

    def __init__(self, con, data_dir: str, parent=None):
        super().__init__(parent)
        self._con = con
        self._data_dir = data_dir
        self._repos_root = os.path.join(data_dir, "repos")
        self._current_repo = None            # core_git.Repo or None
        self._current_label = ""

    # ------------------------------------------------------------ context
    def _repo_for(self, name: str) -> core_git.Repo:
        """One repo per name (slug); created on demand."""
        path = os.path.join(self._repos_root, core_git.slugify(name))
        return core_git.Repo(path)

    @Slot(str, str)
    def attach(self, label: str, kind: str = "project") -> None:
        """Point the panel at a project/library repo; init on demand."""
        if not _probe_git():
            self.message.emit("git is not installed — version control "
                              "unavailable")
            return
        self._current_repo = self._repo_for(f"{kind}:{label}")
        self._current_label = f"{kind}:{label}"
        if not self._current_repo.exists():
            try:
                self._current_repo.init()
                self.message.emit(
                    f"Initialized repository for {label} "
                    f"({core_git.DEFAULT_BRANCH})")
            except core_git.GitError as e:
                self.message.emit(f"git init failed: {e}")
                self._current_repo = None
        self.repoChanged.emit()
        self.refresh()

    def detach(self) -> None:
        self._current_repo = None
        self._current_label = ""
        self.repoChanged.emit()
        self.statusChanged.emit()

    @Slot(result=bool)
    def hasRepo(self) -> bool:
        return self._current_repo is not None and self._current_repo.exists()

    # ------------------------------------------------------------- status
    def refresh(self) -> None:
        self.statusChanged.emit()
        self.logChanged.emit()
        self.branchesChanged.emit()

    @Property("QVariant", notify=statusChanged)
    def status(self):
        return self._read_status()

    def _read_status(self) -> dict:
        if self._current_repo is None or not self._current_repo.exists():
            return {}
        try:
            return self._current_repo.status()
        except core_git.GitError as e:
            return {"error": str(e)}

    @Property("QVariant", notify=logChanged)
    def history(self):
        if self._current_repo is None or not self._current_repo.exists():
            return []
        try:
            return self._current_repo.log(30)
        except core_git.GitError:
            return []

    @Property("QVariant", notify=branchesChanged)
    def branchList(self):
        if self._current_repo is None or not self._current_repo.exists():
            return []
        try:
            cur = self._current_repo.branch()
            return [{"name": b, "current": b == cur}
                    for b in self._current_repo.branches()]
        except core_git.GitError:
            return []

    @Property(str, notify=statusChanged)
    def currentBranch(self) -> str:
        if self._current_repo is None or not self._current_repo.exists():
            return ""
        try:
            return self._current_repo.branch()
        except core_git.GitError:
            return ""

    @Property("QVariant", notify=statusChanged)
    def clean(self):
        st = self._read_status()
        return bool(st) and st.get("clean", True)

    @Property("QVariant", notify=statusChanged)
    def hasUncommitted(self):
        st = self._read_status()
        return bool(st) and not st.get("clean", True)

    @Slot(result=bool)
    def gitAvailable(self) -> bool:
        """Cached probe — never spawns a subprocess from a QML binding
        (a sync subprocess in a binding froze the Settings screen)."""
        return _probe_git()

    @Slot(result=bool)
    def lfsAvailable(self) -> bool:
        return _probe_lfs()

    # ------------------------------------------------------------- actions
    @Slot(str)
    def commit(self, message: str) -> None:
        if self._current_repo is None or not (message or "").strip():
            return
        try:
            sha = self._current_repo.commit_all(message.strip())
            self.message.emit("Committed" if sha else "Nothing to commit")
        except core_git.GitError as e:
            self.message.emit(f"Commit failed: {e}")
        self.refresh()

    @Slot(str)
    def create_branch(self, name: str) -> None:
        if self._current_repo is None:
            return
        try:
            self._current_repo.create_branch(name.strip())
            self.message.emit(f"Branch created: {name.strip()}")
        except core_git.GitError as e:
            self.message.emit(f"Branch failed: {e}")
        self.refresh()

    @Slot(str)
    def checkout(self, name: str) -> None:
        if self._current_repo is None:
            return
        try:
            self._current_repo.checkout(name)
            self.message.emit(f"Switched to {name}")
        except core_git.GitError as e:
            self.message.emit(f"Checkout failed: {e}")
        self.refresh()

    @Slot(str)
    def merge(self, name: str) -> None:
        """Merge a working branch into the current branch (expected:
        fengrid-main); on conflict, guides into a rebase resolution."""
        if self._current_repo is None:
            return
        try:
            self._current_repo.merge_with_rebase(name)
            self.message.emit(f"Merged {name}")
        except core_git.GitError as e:
            if e.code == 2:
                self.message.emit(
                    f"Merge needs your input — {e}. Resolve, then run "
                    "Merge again.")
            else:
                self.message.emit(f"Merge failed: {e}")
        self.refresh()

    @Slot(str)
    def delete_branch(self, name: str) -> None:
        """Delete a working branch (default branch is refused)."""
        if self._current_repo is None:
            return
        try:
            self._current_repo.delete_branch(name)
            self.message.emit(f"Branch deleted: {name}")
        except core_git.GitError as e:
            if "not fully merged" in str(e).lower():
                self.message.emit(
                    f"'{name}' has unmerged work — delete anyway from "
                    "the branch menu (force) or merge it first")
            else:
                self.message.emit(f"Delete failed: {e}")
        self.refresh()

    @Slot(str, result=bool)
    def is_merged(self, name: str) -> bool:
        if self._current_repo is None or not self._current_repo.exists():
            return False
        return name in self._current_repo.merged_branches()

    # -------------------------------------------------------------- remote
    @Slot(str, str, str)
    def set_remote(self, name: str, url: str, token: str = "") -> None:
        """Attach a forge remote; the access token (Settings → Source
        control) is embedded in the stored URL only, never committed."""
        if self._current_repo is None:
            return
        tok = token or core_settings.get(self._con, "sc_token", "")
        try:
            self._current_repo.set_remote(name, url, tok or None)
            self.message.emit(f"Remote '{name}' set")
        except core_git.GitError as e:
            self.message.emit(f"Remote failed: {e}")

    @Slot(str)
    def push(self, remote: str = "origin") -> None:
        if self._current_repo is None:
            return
        try:
            out = self._current_repo.push(remote)
            self.message.emit(f"Pushed {out['pushed']} → {remote}")
        except core_git.GitError as e:
            self.message.emit(f"Push failed: {e}")

    # ------------------------------------------------------- batch support
    def batch_begin(self, label: str) -> core_git.BatchOp | None:
        """Projects' batch operations call this before mutating anything;
        None (with a message) when there is no repo."""
        if self._current_repo is None or not self._current_repo.exists():
            return None
        try:
            return core_git.BatchOp(self._current_repo, label).__enter__()
        except core_git.GitError as e:
            self.message.emit(f"Batch branch failed: {e}")
            return None

    @Slot(str, bool)
    def batch_finish(self, label: str, keep: bool) -> None:
        """Review outcome for a batch: commit+merge-back or discard; the
        batch branch is deleted either way.

        BatchOp.__exit__ (commit_all + checkout back) never runs for
        QML-initiated batches — QML cannot drive a Python context
        manager — so this slot does that work explicitly: commit the
        batch-branch working tree, return to fengrid-main, then merge
        or drop. Committing before checkout also makes the discard
        path safe (checkout won't refuse a dirty tree)."""
        repo = self._current_repo
        if repo is None:
            return
        op = core_git.BatchOp(repo, label)
        try:
            if op.branch not in repo.branches():
                self.message.emit("No batch branch to finish")
                return
            if repo.branch() == op.branch:
                op.committed = repo.commit_all(f"batch: {op.label}")
                repo.checkout(core_git.DEFAULT_BRANCH)
            if keep and op.committed:
                ahead, _ = repo.ahead_behind_from(op.branch,
                                                  core_git.DEFAULT_BRANCH)
                if ahead > 0:
                    repo.merge_into_current(op.branch)
            repo.delete_branch(op.branch, force=True)
            self.message.emit(
                f"Batch merged into {core_git.DEFAULT_BRANCH}" if keep
                else "Batch discarded")
        except core_git.GitError as e:
            self.message.emit(f"Batch finish failed: {e}")
        self.refresh()

    # --------------------------------------------------------- maintenance
    @Slot()
    def maintenance_all(self) -> None:
        """Settings → Source control: sweep every repo under repos/."""
        root = self._repos_root
        if not os.path.isdir(root):
            self.message.emit("No repositories yet")
            return
        dropped = kept = dirty = 0
        for name in sorted(os.listdir(root)):
            repo = core_git.Repo(os.path.join(root, name))
            if not repo.exists():
                continue
            try:
                rep = core_git.maintenance(repo)
                dropped += len(rep["dropped"])
                kept += len(rep["kept"])
                dirty += 1 if rep["uncommitted"] else 0
            except core_git.GitError:
                continue
        self.message.emit(
            f"Maintenance done — {dropped} merged branches removed, "
            f"{kept} kept, {dirty} repo(s) with uncommitted changes")
