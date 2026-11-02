"""#141: git clone progress — the parser's stage weighting and the
streaming Repo.clone(progress=...) callback.

The Preset Libraries dialog turns the callback's percent into a live
loading bar, so the numbers must be monotonic and end at 100 exactly
when the clone succeeds.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from fengrid.core.projects_git import GitError, Repo, parse_git_progress  # noqa: E402


# ------------------------------------------------------------- parser
def test_parse_git_progress_maps_every_stage():
    # counting 0-2, compressing 2-4, receiving 4-84, deltas 84-98,
    # checkout 98-100 — one monotonic curve
    assert parse_git_progress("Counting objects: 100% (5/5), done.") == 2
    assert parse_git_progress("Compressing objects:  50% (2/4)") == 3
    assert parse_git_progress("Receiving objects:   0% (1/1234)") == 4
    assert parse_git_progress("Receiving objects:  45% (556/1234)") == 40
    assert parse_git_progress(
        "Receiving objects: 100% (1234/1234), 2.11 MiB | 5.00 MiB/s") == 84
    assert parse_git_progress("Resolving deltas:  10% (12/120)") == 85
    assert parse_git_progress("Resolving deltas: 100% (120/120)") == 98
    assert parse_git_progress("Updating files:  37% (15/40)") == 98
    assert parse_git_progress("Updating files: 100% (40/40), done.") == 100


def test_parse_git_progress_ignores_other_lines():
    assert parse_git_progress("remote: Enumerating objects: 5, done.") is None
    assert parse_git_progress("Cloning into 'x'...") is None
    assert parse_git_progress("error: failed to push some refs") is None
    assert parse_git_progress("") is None
    assert parse_git_progress("Receiving objects") is None


def test_parse_git_progress_is_monotonic_across_a_real_stream():
    # a whole typical stderr stream must never step backwards
    stream = [
        "Cloning into 'pack'...",
        "remote: Enumerating objects: 240, done.",
        "remote: Counting objects: 100% (240/240), done.",
        "remote: Compressing objects: 100% (180/180), done.",
        "Receiving objects:   0% (1/240)",
        "Receiving objects:  33% (80/240)",
        "Receiving objects: 100% (240/240), 12.34 MiB | 3.21 MiB/s",
        "Resolving deltas:   0% (0/90)",
        "Resolving deltas: 100% (90/90), done.",
        "Updating files:  10% (2/20)",
        "Updating files: 100% (20/20), done.",
    ]
    pcts = [p for line in stream
            if (p := parse_git_progress(line)) is not None]
    assert pcts == sorted(pcts), f"progress stepped back: {pcts}"
    assert pcts[-1] == 100


# ------------------------------------------------- clone with progress
def _mk_repo(path: Path) -> Path:
    from fengrid.core.projects_git import Repo
    path.mkdir(parents=True, exist_ok=True)
    repo = Repo(path)
    repo.init()
    (path / "README.md").write_text("# t\n", encoding="utf-8")
    repo.commit_all("init")
    return path


def test_repo_clone_emits_monotonic_progress_ending_at_100(tmp_path):
    src = _mk_repo(tmp_path / "src")
    calls: list[int] = []
    repo = Repo.clone(str(src), tmp_path / "dest", progress=calls.append)
    assert repo.exists()
    assert (tmp_path / "dest" / ".git").exists()
    assert calls, "progress callback never fired"
    assert calls == sorted(calls), f"progress stepped back: {calls}"
    assert calls[-1] == 100, f"clone must end at 100: {calls}"


def test_repo_clone_without_progress_still_works(tmp_path):
    src = _mk_repo(tmp_path / "src")
    dest = tmp_path / "dest"
    Repo.clone(str(src), dest)
    assert (dest / ".git").exists()


def test_repo_clone_failure_raises_git_error_with_progress(tmp_path):
    missing = tmp_path / "no-such-repo"
    calls: list[int] = []
    with pytest.raises(GitError):
        Repo.clone(str(missing), tmp_path / "dest", progress=calls.append)
    # a failed clone must never report 100
    assert 100 not in calls
