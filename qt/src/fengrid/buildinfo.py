"""Build provenance for the About screen (#43).

The commit the running binary was built from resolves in two tiers:

1. A ``.build-commit`` stamp file the build scripts write before the
   PyInstaller run and bundle via ``--add-data`` — the authoritative
   source for frozen builds.
2. ``git rev-parse`` in the source checkout — authoritative for dev runs
   (skipped when frozen: a frozen binary has no repo around it).

An empty string means "not recorded"; the About screen hides the row.
"""

import os
import subprocess
import sys

_STAMP_NAME = ".build-commit"


def _default_stamp_paths() -> "list[str]":
    """Where a stamp file could live, most specific first.

    Frozen (PyInstaller onedir): datas land under ``_MEIPASS``. Source
    tree: the repo root (``qt/..``) — build scripts stamp there too, so
    a source run next to a recent build still shows the right commit.
    """
    paths = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        paths.append(os.path.join(meipass, _STAMP_NAME))
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.abspath(os.path.join(here, "..", "..", ".."))
    paths.append(os.path.join(repo_root, _STAMP_NAME))
    return paths


def _git_commit(repo_root: str) -> str:
    """Best-effort `git rev-parse HEAD` — empty on any failure."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo_root,
            capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def build_commit(stamp_paths=None) -> str:
    """The commit hash for this build, or '' when it cannot be resolved."""
    for cand in (stamp_paths if stamp_paths is not None
                 else _default_stamp_paths()):
        try:
            if os.path.isfile(cand):
                with open(cand, encoding="utf-8") as f:
                    v = f.read().strip()
                if v:
                    return v
        except OSError:
            pass
    if getattr(sys, "frozen", False):
        return ""
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.abspath(os.path.join(here, "..", "..", ".."))
    return _git_commit(repo_root)
