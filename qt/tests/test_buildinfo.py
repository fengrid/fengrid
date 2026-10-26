"""Build-provenance stamp resolution (#43).

The About screen's commit hash comes from fengrid.buildinfo.build_commit:
a `.build-commit` stamp file bundled by the build scripts wins, then a
best-effort `git rev-parse` for source runs, then '' (row hidden).
"""
import os
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from fengrid.buildinfo import build_commit       # noqa: E402


def test_stamp_file_wins(tmp_path):
    stamp = tmp_path / ".build-commit"
    stamp.write_text("deadbeefCAFE0123456789abdcef0123456789ab\n",
                     encoding="utf-8")
    assert build_commit(stamp_paths=[str(stamp)]) == \
        "deadbeefCAFE0123456789abdcef0123456789ab"


def test_empty_stamp_falls_through(tmp_path):
    stamp = tmp_path / ".build-commit"
    stamp.write_text("\n", encoding="utf-8")
    # next candidate does not exist → source-run git fallback applies
    # (or '' outside a repo); never an exception
    got = build_commit(stamp_paths=[str(stamp), str(tmp_path / "missing")])
    if got:
        head = subprocess.run(["git", "rev-parse", "HEAD"],
                              capture_output=True, text=True,
                              cwd=str(SRC)).stdout.strip()
        assert got == head


def test_frozen_without_stamp_is_empty(tmp_path, monkeypatch):
    """A frozen binary with no stamp must NOT run git (no repo around
    it) — it reports '' and the About row hides."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    assert build_commit(stamp_paths=[str(tmp_path / "missing")]) == ""
