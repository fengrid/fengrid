"""Project/Library revision control: one git repository per Project or
Library.

Why git: Fengrid projects are file trees (manifest.json, tokens.css,
site templates) plus references to library rows, so a repository with a
`fengrid-main` default branch gives Projects real revision control —
initial snapshot at creation, a commit on every Save, working branches
for experiments, merge-back with optional delete of the working branch.
Libraries (saved tag-set views) are tracked the same way.

Large files (exported bundles, webfont packages) ride git-lfs when the
tool exists (probed at setup); git-annex is detected but the layout is
git-lfs-first. Nothing external is required for the core flow: the git
binary is probed once, and every command is an argv list (no shell, no
injection). Remote push is optional — access tokens for GitHub /
Codeberg / Forgejo / Gitea-style forges are stored in the Settings
store, never in the repo itself.

Memory/robustness rules mirrored from the rest of core:
  - every subprocess is argv-list only, timeout-bounded, text decoded
  - repo paths resolve under the projects root; user-controlled names
    are slugged before they ever touch a path
  - outputs are parsed, never eval'd
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path

DEFAULT_BRANCH = "fengrid-main"
GIT_TIMEOUT = 60          # seconds per command (init/commit/status…)
PUSH_TIMEOUT = 600        # network push/pull
LFS_TRACK_PATTERNS = ("*.zip", "*.tar.gz", "*.tgz", "*.woff", "*.woff2",
                      "*.ttf", "*.otf", "*.png", "*.jpg", "*.jpeg",
                      "*.mp4", "*.mp3", "*.pdf", "assets/**")

TOKEN_RE = re.compile(r"^[A-Za-z0-9_\-\.~]{8,}$")

# git streams its clone progress to stderr ("Receiving objects: 45% (…)")
_PROGRESS_RE = re.compile(
    r"^(?:remote: )?(?P<stage>Counting objects|Compressing objects|"
    r"Receiving objects|Resolving deltas|Updating files):"
    r"\s+(?P<pct>\d{1,3})%")


def parse_git_progress(line: str) -> int | None:
    """Map one git progress line onto an overall clone percent (0-100).

    git reports each stage with its own percent; the stages are weighted
    onto a single monotonic curve so a caller can feed one number to a
    progress bar (#141, Preset Libraries download bars):
      counting 0-2, compressing 2-4, receiving 4-84, deltas 84-98,
      checkout (Updating files) 98-100. Non-progress lines → None.
    """
    m = _PROGRESS_RE.match(line.strip())
    if m is None:
        return None
    pct = min(100, max(0, int(m["pct"])))
    stage = m["stage"]
    if stage == "Counting objects":
        return pct * 2 // 100
    if stage == "Compressing objects":
        return 2 + pct * 2 // 100
    if stage == "Receiving objects":
        return 4 + pct * 80 // 100
    if stage == "Resolving deltas":
        return 84 + pct * 14 // 100
    return 98 + pct * 2 // 100          # Updating files


class GitError(RuntimeError):
    """Raised with a short user-facing message plus a git exit code."""

    def __init__(self, message: str, code: int = 1):
        super().__init__(message)
        self.code = code


def git_available() -> bool:
    try:
        return subprocess.run(
            ["git", "--version"], capture_output=True, text=True,
            timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def lfs_available() -> bool:
    try:
        return subprocess.run(
            ["git", "lfs", "version"], capture_output=True, text=True,
            timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def annex_available() -> bool:
    try:
        return subprocess.run(
            ["git", "annex", "version"], capture_output=True, text=True,
            timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9._-]+", "-", (name or "").strip().lower()).strip("-")
    return s or "project"


class Repo:
    """One project/library repository — a thin, testable git wrapper."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    # ----------------------------------------------------------- plumbing
    def _run(self, *args: str, timeout: int = GIT_TIMEOUT,
             env_extra: dict | None = None) -> str:
        if not git_available():
            raise GitError("git is not installed", 127)
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0",
               "GIT_ASKPASS": "echo"}
        if env_extra:
            env.update(env_extra)
        proc = subprocess.run(
            ["git", "-C", str(self.path), *args],
            capture_output=True, text=True, timeout=timeout, env=env)
        if proc.returncode != 0:
            raise GitError((proc.stderr or proc.stdout).strip()[:300],
                           proc.returncode)
        return proc.stdout

    @staticmethod
    def clone(url: str, dest: str | Path, branch: str = "",
              timeout: int = 900,
              progress: Callable[[int], None] | None = None) -> "Repo":
        """Clone a remote repository into dest (must not exist yet).

        Preset-library downloads use this: single-branch clone of the
        configured source URL (branch empty = remote HEAD). Long
        timeout — font/icon repos can be tens of megabytes.

        ``progress`` (#141): called with an overall percent 0-100 as git
        streams its progress report — the Preset Libraries dialog turns
        that into a live loading bar. Without it the clone is the plain
        blocking call it always was (existing callers unaffected).
        """
        if not git_available():
            raise GitError("git is not installed", 127)
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        args = ["git", "clone", "--single-branch"]
        if (branch or "").strip():
            args += ["--branch", branch.strip()]
        if progress is not None:
            args.append("--progress")     # force the report off a tty
        args += [url, str(dest)]
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0",
               "GIT_ASKPASS": "echo"}
        if progress is None:
            proc = subprocess.run(args, capture_output=True, text=True,
                                  timeout=timeout, env=env)
            if proc.returncode != 0:
                raise GitError((proc.stderr or proc.stdout).strip()[:300],
                               proc.returncode)
            return Repo(dest)
        # #141: stream git's stderr and map its progress lines onto one
        # overall percent. Progress lines end with \r, so the reader
        # splits on both \r and \n; monotonic — never emit a step back.
        proc = subprocess.Popen(args, stderr=subprocess.PIPE,
                                stdout=subprocess.DEVNULL)
        watchdog = threading.Timer(timeout, proc.kill)
        watchdog.daemon = True
        watchdog.start()
        last = 0
        buf = b""
        try:
            stream = proc.stderr
            while stream is not None:
                ch = stream.read(1)
                if not ch:
                    break
                if ch in (b"\r", b"\n"):
                    pct = parse_git_progress(buf.decode("utf-8", "replace"))
                    if pct is not None and pct >= last:
                        progress(pct)
                        last = pct
                    buf = b""
                else:
                    buf += ch
        finally:
            watchdog.cancel()
        proc.wait()
        if proc.returncode != 0:
            tail = buf.decode("utf-8", "replace").strip()
            raise GitError((tail or
                            f"git clone failed (exit {proc.returncode})"
                            )[:300], proc.returncode)
        progress(100)
        return Repo(dest)

    def exists(self) -> bool:
        return (self.path / ".git").exists()

    # --------------------------------------------------------------- stash
    def stash(self, message: str = "") -> bool:
        """Stash all changes (including untracked); False when there was
        nothing to stash (git exits 0 and says so — inspect the output)."""
        if not self.exists():
            return False
        args = ["stash", "push", "-u"]
        if (message or "").strip():
            args += ["-m", message.strip()]
        out = self._run(*args)
        return "No local changes to save" not in (out or "")

    def stash_list(self) -> list[str]:
        if not self.exists():
            return []
        try:
            out = self._run("stash", "list")
        except GitError:
            return []
        return [ln for ln in out.splitlines() if ln.strip()]

    def pop_stash(self, index: int = 0) -> None:
        """Apply and drop stash@<index> (newest first)."""
        if not self.exists():
            raise GitError("not a repository", 128)
        self._run("stash", "pop", f"stash@{{{int(index)}}}")

    # ------------------------------------------------------------- setup
    def init(self, author_name: str = "Fengrid",
             author_email: str = "fengrid@localhost") -> None:
        """Create the repo + fengrid-main + LFS tracking when available."""
        self.path.mkdir(parents=True, exist_ok=True)
        self._run("init", "-b", DEFAULT_BRANCH)
        self._run("config", "user.name", author_name)
        self._run("config", "user.email", author_email)
        if lfs_available():
            self._run("lfs", "install", "--local")
            self._run("lfs", "track", *LFS_TRACK_PATTERNS)

    def commit_all(self, message: str) -> str | None:
        """Stage everything and commit; returns the new commit sha, or
        None when there was nothing to commit."""
        self._run("add", "-A")
        proc = subprocess.run(
            ["git", "-C", str(self.path), "commit", "-m", message],
            capture_output=True, text=True, timeout=GIT_TIMEOUT,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
        if proc.returncode != 0:
            out = (proc.stderr or proc.stdout).lower()
            if "nothing to commit" in out:
                return None
            raise GitError((proc.stderr or proc.stdout).strip()[:300],
                           proc.returncode)
        return self._run("rev-parse", "HEAD").strip()

    # ------------------------------------------------------------ status
    def status(self) -> dict:
        """Porcelain v2-ish parse: staged / unstaged / untracked lists."""
        out = self._run("status", "--porcelain")
        staged, unstaged, untracked = [], [], []
        for line in out.splitlines():
            if not line.strip():
                continue
            x, y, rest = line[0], line[1], line[3:]
            if x == "?" and y == "?":
                untracked.append(rest)
            elif x != " ":
                staged.append(rest)
            if y != " " and y != "?":
                unstaged.append(rest)
        branch = self.branch()
        clean = not (staged or unstaged or untracked)
        return {"branch": branch, "staged": staged, "unstaged": unstaged,
                "untracked": untracked, "clean": clean}

    def branch(self) -> str:
        out = self._run("rev-parse", "--abbrev-ref", "HEAD")
        return out.strip()

    def branches(self) -> list[str]:
        out = self._run("branch", "--format=%(refname:short)")
        return [b.strip() for b in out.splitlines() if b.strip()]

    def current_clean(self) -> bool:
        return self.status()["clean"]

    def ahead_behind(self, other: str = DEFAULT_BRANCH) -> tuple[int, int]:
        out = self._run("rev-list", "--left-right", "--count",
                        f"{other}...HEAD")
        behind, ahead = out.split()
        return int(ahead), int(behind)

    def ahead_behind_from(self, branch: str,
                          base: str = DEFAULT_BRANCH) -> tuple[int, int]:
        """(ahead, behind) for `branch` relative to `base` — works for a
        branch that is not checked out."""
        out = self._run("rev-list", "--left-right", "--count",
                        f"{base}...{branch}")
        behind, ahead = out.split()
        return int(ahead), int(behind)

    # ----------------------------------------------------------- branches
    def create_branch(self, name: str, checkout: bool = True) -> None:
        """`name` must already be a valid branch name (BatchOp passes
        'batch/…' refs — no slugify here or the slash is destroyed)."""
        if name in self.branches():
            raise GitError(f"branch '{name}' already exists", 1)
        self._run("branch", name)
        if checkout:
            self.checkout(name)

    def checkout(self, name: str) -> None:
        self._run("checkout", name)

    def merge_into_current(self, name: str) -> dict:
        """Merge `name` into the CURRENT branch (ff when possible)."""
        out = self._run("merge", "--no-edit", name)
        return {"merged": name, "output": out.strip()[:500],
                "conflict": False}

    def merge_with_rebase(self, name: str) -> dict:
        """Guided rebasing: merge --no-ff first; on conflict, rebase the
        working branch onto the target so the user resolves once. Raises
        GitError('conflicts', 2) carrying the conflicted file list."""
        try:
            return self.merge_into_current(name)
        except GitError as e:
            if e.code != 1 or "CONFLICT" not in str(e):
                raise
            conflicted = [l.split(":", 1)[1].strip()
                          for l in str(e).splitlines()
                          if "CONFLICT" in l and ":" in l]
            self._run("merge", "--abort")
            self._run("rebase", self.branch())
            raise GitError("rebase: resolve conflicts in "
                           + ", ".join(conflicted[:10]), 2)

    def delete_branch(self, name: str, force: bool = False) -> None:
        if name == DEFAULT_BRANCH:
            raise GitError("refusing to delete the default branch", 1)
        self._run("branch", "-D" if force else "-d", name)

    def discard_all(self) -> None:
        """Hard rollback of the working tree: reset tracked files and
        remove untracked ones. Used by BatchOp failure/discard paths —
        these repos hold only Fengrid-generated content."""
        self._run("reset", "--hard", "HEAD")
        self._run("clean", "-fd")

    def merged_branches(self) -> list[str]:
        """Working branches already merged into fengrid-main (cleanup
        candidates). The default branch is never listed."""
        out = self._run("branch", "--merged", DEFAULT_BRANCH,
                        "--format=%(refname:short)")
        return [b.strip() for b in out.splitlines()
                if b.strip() and b.strip() != DEFAULT_BRANCH]

    def branch_older_than(self, name: str, days: float) -> bool:
        """A merged branch last committed > `days` days ago is stale."""
        try:
            out = self._run("log", "-1", "--format=%at", name)
            return time.time() - float(out.strip()) > days * 86400
        except (GitError, ValueError):
            return False

    def log(self, limit: int = 20) -> list[dict]:
        out = self._run("log", f"-{max(1, min(int(limit), 100))}",
                        "--format=%H%x1f%at%x1f%s")
        rows = []
        for line in out.splitlines():
            parts = line.split("\x1f")
            if len(parts) == 3:
                rows.append({"sha": parts[0][:10], "ts": float(parts[1]),
                             "message": parts[2]})
        return rows

    def worktrees(self) -> list[dict]:
        """`git worktree list --porcelain` parsed into dicts."""
        out = self._run("worktree", "list", "--porcelain")
        rows, cur = [], {}
        for line in out.splitlines():
            if not line.strip():
                if cur:
                    rows.append(cur)
                    cur = {}
                continue
            key, _, val = line.partition(" ")
            if key == "worktree":
                cur["path"] = val
            elif key == "HEAD":
                cur["sha"] = val[:10]
            elif key == "branch":
                cur["branch"] = val.replace("refs/heads/", "")
            elif key == "detached":
                cur["detached"] = True
        if cur:
            rows.append(cur)
        return rows

    def add_worktree(self, name: str, branch: str) -> str:
        """A linked worktree for parallel work on `branch`."""
        wt = self.path / ".worktrees" / slugify(name)
        self._run("worktree", "add", str(wt), branch)
        return str(wt)

    # ------------------------------------------------------------- remote
    def remotes(self) -> dict[str, str]:
        out = self._run("remote", "-v")
        remotes = {}
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 2 and "(push)" in line:
                remotes[parts[0]] = parts[1]
        return remotes

    def set_remote(self, name: str, url: str,
                   token: str | None = None) -> None:
        """Point a remote at a forge URL; the access token rides the URL
        only when given (stored in .git/config locally, never committed)."""
        url = _apply_token(url, token)
        try:
            self._run("remote", "remove", name)
        except GitError:
            pass
        self._run("remote", "add", name, url)

    def pull(self, remote: str = "origin",
             branch: str | None = None) -> str:
        """Fast-forward pull; GitError on conflicts / no upstream."""
        if not self.exists():
            raise GitError("not a repository", 128)
        args = ["pull", "--ff-only", remote]
        if branch:
            args.append(branch)
        return self._run(*args, timeout=PUSH_TIMEOUT)

    def push(self, remote: str = "origin", branch: str | None = None,
             set_upstream: bool = True) -> dict:
        args = ["push"]
        if set_upstream:
            args.append("-u")
        args.append(remote)
        args.append(branch or self.branch())
        out = self._run(*args, timeout=PUSH_TIMEOUT)
        return {"pushed": branch or self.branch(), "output": out[-400:]}

    def has_unpushed(self, remote: str = "origin") -> bool:
        try:
            self._run("rev-parse", "--verify", f"{remote}/{self.branch()}",
                      timeout=10)
        except GitError:
            return True
        ahead, _ = self.ahead_behind(f"{remote}/{self.branch()}")
        return ahead > 0


def _apply_token(url: str, token: str | None) -> str:
    """Embed an https access token into a forge URL (never stored in the
    repo contents — only .git/config, which is not committed)."""
    if not token or not TOKEN_RE.match(token):
        return url
    m = re.match(r"^(https?://)([^/@]+@)?([^/]+)(/.*)?$", url)
    if not m:
        return url
    return f"{m.group(1)}{token}@{m.group(3)}{m.group(4) or ''}"


# ────────────────────────────────────────────── maintenance sweep
def maintenance(repo: Repo, stale_days: float = 14.0) -> dict:
    """Repo cleanup: report uncommitted changes, prune dangling branches
    already merged into fengrid-main (force-drop stale ones), run gc.
    Called from Settings → Source control; never deletes the default."""
    if not repo.exists():
        raise GitError("not a git repository", 1)
    st = repo.status()
    report: dict = {"repo": str(repo.path), "uncommitted": len(
        st["staged"]) + len(st["unstaged"]) + len(st["untracked"]),
        "dropped": [], "kept": []}
    for b in repo.merged_branches():
        if repo.branch_older_than(b, stale_days):
            try:
                repo.delete_branch(b, force=True)
                report["dropped"].append(b)
                continue
            except GitError:
                pass
        report["kept"].append(b)
    try:
        repo._run("gc", "--auto", timeout=120)
        report["gc"] = True
    except GitError:
        report["gc"] = False
    return report


# ─────────────────────────────────────── batch-operations wrapper
class BatchOp:
    """Context manager for batch/bulk changes: creates an auto branch,
    commits on success (caller then merges back), restores `fengrid-main`
    on failure so the working tree is untouched."""

    def __init__(self, repo: Repo, label: str):
        self.repo = repo
        self.label = slugify(label)
        self.branch = f"batch/{self.label}"
        self.committed: str | None = None
        self._start = repo.branch()

    def __enter__(self) -> "BatchOp":
        if self.repo.exists():
            if self._start != DEFAULT_BRANCH:
                self.repo.checkout(DEFAULT_BRANCH)
            self.repo.create_branch(self.branch)
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is not None:
            # discard: hard-reset the tree, back to the default branch,
            # drop the batch branch
            try:
                self.repo.discard_all()
                self.repo.checkout(DEFAULT_BRANCH)
                self.repo.delete_branch(self.branch, force=True)
            except GitError:
                pass
            return False                      # propagate the error
        self.committed = self.repo.commit_all(f"batch: {self.label}")
        self.repo.checkout(DEFAULT_BRANCH)
        return False

    def finish(self, keep: bool) -> dict:
        """After review: merge the batch branch back into fengrid-main
        (keep=True) or discard it entirely (keep=False). The branch is
        always deleted after the decision — the spec's auto-cleanup."""
        if not self.repo.exists():
            return {"kept": False}
        if keep and self.committed:
            # only merge when the batch branch actually diverged
            ahead, _ = self.repo.ahead_behind_from(self.branch,
                                                   DEFAULT_BRANCH)
            if ahead > 0:
                self.repo.merge_into_current(self.branch)
            kept = True
        else:
            kept = False
        try:
            self.repo.delete_branch(self.branch, force=True)
        except GitError:
            pass                       # already gone (discard path)
        return {"kept": kept}
