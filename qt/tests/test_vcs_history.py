"""Git revision control (core.projects_git) + bounded undo/redo history.

Exercises a REAL git binary in temp repos (git is required on this
host's CI/dev image; tests skip cleanly when it is absent). Covers:
init with fengrid-main, commit-all, branches, merge, delete-refusal,
maintenance sweep, batch operations (keep/discard/failure rollback),
and the History stack's caps + bulk suppression.
"""

import os
import time

import pytest

from fengrid.core import projects_git as pg
from fengrid.core.history import History, bulk_guard


@pytest.fixture()
def repo(tmp_path):
    if not pg.git_available():
        pytest.skip("git not available")
    r = pg.Repo(tmp_path / "proj")
    r.init()
    (r.path / "manifest.json").write_text('{"name": "proj"}')
    r.commit_all("initial snapshot")
    return r


# ──────────────────────────────────────────────────── repo lifecycle
def test_init_uses_fengrid_main(repo):
    assert repo.branch() == "fengrid-main"
    assert repo.status()["clean"]


def test_commit_all_reports_nothing_to_commit(repo):
    assert repo.commit_all("empty") is None
    (repo.path / "extra.txt").write_text("x")
    sha = repo.commit_all("add extra")
    assert sha and len(sha) >= 7
    assert repo.status()["clean"]


def test_lfs_tracking_setup(repo):
    if not pg.lfs_available():
        pytest.skip("git-lfs not available")
    out = repo._run("lfs", "track")
    assert "*.zip" in out          # core patterns registered


# ──────────────────────────────────────────────── branch workflow
def test_branch_create_checkout_merge_delete(repo):
    repo.create_branch("experiment")
    assert repo.branch() == "experiment"
    (repo.path / "wip.txt").write_text("wip")
    repo.commit_all("work")
    repo.checkout("fengrid-main")
    assert not (repo.path / "wip.txt").exists()
    repo.merge_into_current("experiment")
    assert (repo.path / "wip.txt").exists()
    repo.delete_branch("experiment")
    assert repo.branches() == ["fengrid-main"]


def test_delete_default_branch_refused(repo):
    with pytest.raises(pg.GitError):
        repo.delete_branch("fengrid-main")


def test_delete_unmerged_branch_refuses_without_force(repo):
    repo.create_branch("dangling")
    (repo.path / "x.txt").write_text("x")
    repo.commit_all("unmerged work")
    repo.checkout("fengrid-main")
    with pytest.raises(pg.GitError):
        repo.delete_branch("dangling")            # -d refuses
    repo.delete_branch("dangling", force=True)    # -D is explicit
    assert repo.branches() == ["fengrid-main"]


def test_merged_branches_listing(repo):
    repo.create_branch("done")
    (repo.path / "d.txt").write_text("d")
    repo.commit_all("done work")
    repo.checkout("fengrid-main")
    repo.merge_into_current("done")           # actually merge first
    assert "done" in repo.merged_branches()
    assert "fengrid-main" not in repo.merged_branches()


def test_log_returns_recent_commits(repo):
    rows = repo.log(5)
    assert rows and rows[-1]["message"] == "initial snapshot"


# ─────────────────────────────────────────────────── batch operations
def test_batch_keep_merges_and_cleans_up(repo):
    with pg.BatchOp(repo, "recolor batch") as op:
        (repo.path / "batch.txt").write_text("b")
        assert repo.branch().startswith("batch/")
    assert op.committed is not None
    result = op.finish(keep=True)
    assert result["kept"] is True
    assert (repo.path / "batch.txt").exists()
    assert repo.branches() == ["fengrid-main"]     # branch auto-deleted
    assert repo.branch() == "fengrid-main"


def test_batch_discard_rolls_back(repo):
    before = sorted(os.listdir(repo.path))
    with pg.BatchOp(repo, "dropped") as op:
        (repo.path / "temp.txt").write_text("t")
    result = op.finish(keep=False)
    assert result["kept"] is False
    assert sorted(os.listdir(repo.path)) == before
    assert repo.branches() == ["fengrid-main"]


def test_batch_failure_rolls_back(repo):
    before = sorted(os.listdir(repo.path))
    with pytest.raises(RuntimeError):
        with pg.BatchOp(repo, "boom") as op:
            (repo.path / "bad.txt").write_text("b")
            raise RuntimeError("boom")
    assert sorted(os.listdir(repo.path)) == before
    assert repo.branches() == ["fengrid-main"]


# ─────────────────────────────────────────────────────── maintenance
def test_maintenance_drops_merged_branch(repo):
    repo.create_branch("stale")
    (repo.path / "s.txt").write_text("s")
    repo.commit_all("stale work")
    # backdate the branch's last commit while ON it (env-var dates)
    repo._run("commit", "--allow-empty", "-m", "noop",
              env_extra={"GIT_COMMITTER_DATE": "2000-01-01T00:00:00",
                         "GIT_AUTHOR_DATE": "2000-01-01T00:00:00"})
    repo.checkout("fengrid-main")
    repo.merge_into_current("stale")          # merged into fengrid-main
    report = pg.maintenance(repo)
    # 'stale' is merged into fengrid-main AND old → force-dropped
    assert "stale" in report["dropped"]


def test_maintenance_reports_uncommitted(repo):
    (repo.path / "dirty.txt").write_text("d")
    report = pg.maintenance(repo)
    assert report["uncommitted"] == 1


# ──────────────────────────────────────────────────────── remotes
def test_token_embedding():
    assert pg._apply_token(
        "https://github.com/u/r.git", "ghp_12345678") == \
        "https://ghp_12345678@github.com/u/r.git"
    # non-https URLs pass through untouched
    assert pg._apply_token("git@example.com:u/r.git", "tok12345678") == \
        "git@example.com:u/r.git"
    # invalid tokens are ignored
    assert pg._apply_token("https://github.com/u/r.git", "short") == \
        "https://github.com/u/r.git"


# ─────────────────────────────────────────────── undo/redo history
def test_history_undo_redo_cycle():
    h = History()
    h.push("step1", {"v": 1}, {"v": 0})
    h.push("step2", {"v": 2}, {"v": 1})
    assert h.can_undo() and not h.can_redo()
    assert h.pop_undo().label == "step2"
    assert h.can_redo()
    assert h.pop_undo().label == "step1"
    assert not h.can_undo()
    assert h.pop_redo().label == "step1"
    # a fresh push clears the redo arm (step1 + step3 on the undo stack)
    h.push("step3", {"v": 3}, {"v": 1})
    assert not h.can_redo() and h.depth == 2
    assert h.pop_undo().label == "step3"


def test_history_entry_cap_drops_oldest():
    h = History(max_entries=3)
    for i in range(6):
        h.push(f"n{i}", i, i)
    assert h.depth == 3
    assert h.peek_undo_label() == "n5"          # newest kept
    assert h.peek_redo_label() == ""


def test_history_byte_cap():
    h = History(max_bytes=1500)
    h.push("big1", "x" * 700, "y" * 700)        # ~1.4KB
    h.push("big2", "x" * 700, "y" * 700)
    assert h.depth == 1                          # older dropped by bytes
    assert h.bytes_used <= 1500


def test_bulk_guard_suppresses_and_clears():
    h = History()
    h.push("normal", 1, 1)
    with bulk_guard(h):
        h.push("bulk-should-vanish", 2, 2)
        assert h.depth == 0                     # suppressed live
    assert h.depth == 0 and not h.can_undo()    # cleared after
    h.push("after", 3, 3)
    assert h.can_undo()


def test_slugify():
    assert pg.slugify("My Cool Project!") == "my-cool-project"
    assert pg.slugify("") == "project"
    assert pg.slugify("a/b\\c") == "a-b-c"
