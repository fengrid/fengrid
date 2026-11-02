"""#98 — snippet import unification: VS Code location scan + kind inference.

The Code pane's dedicated import button/menu is gone; Settings → Import &
Watch now owns snippet importing. Two core pieces support it: a scanner
that finds .code-snippets/.json files at VS Code's default User/snippets
folders, and a kind inferrer that maps file extensions to import kinds
(.sqlite/.db = massCode, everything else = vscode).
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from fengrid.core import snippets as core_snippets


# ------------------------------------------------------------ kind inference
def test_infer_snippet_kind_vscode():
    assert core_snippets.infer_snippet_kind("/x/global.code-snippets") == "vscode"
    assert core_snippets.infer_snippet_kind("/x/javascript.json") == "vscode"
    assert core_snippets.infer_snippet_kind("/x/anything.txt") == "vscode"


def test_infer_snippet_kind_masscode():
    assert core_snippets.infer_snippet_kind("/x/masscode.sqlite") == "masscode"
    assert core_snippets.infer_snippet_kind("/x/snippets.db") == "masscode"
    assert core_snippets.infer_snippet_kind("/x/store.sqlite3") == "masscode"


def test_infer_snippet_kind_case_insensitive():
    assert core_snippets.infer_snippet_kind("/x/DB.SQLITE") == "masscode"


# ------------------------------------------------------- VS Code scan
def test_scan_finds_code_snippets(tmp_path, monkeypatch):
    """A .code-snippets file in the Code variant's snippets folder is found."""
    root = tmp_path / "Code" / "User" / "snippets"
    root.mkdir(parents=True)
    (root / "global.code-snippets").write_text('{"s": {"prefix": "s"}}')
    (root / "javascript.json").write_text('{"j": {"prefix": "j"}}')
    # files that should be skipped
    (root / ".hidden.json").write_text("{}")
    (root / "readme.txt").write_text("not a snippet")

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    results = core_snippets.scan_vscode_snippets()
    names = {r["name"] for r in results}
    assert "global" in names
    assert "javascript" in names
    # hidden files and non-snippet extensions are skipped
    assert ".hidden" not in names
    assert "readme" not in names
    # all results point at the Code variant
    assert all(r["app"] == "Code" for r in results)
    # paths are absolute
    assert all(Path(r["path"]).is_absolute() for r in results)


def test_scan_covers_variants(tmp_path, monkeypatch):
    """Multiple VS Code variants are scanned, not just the main one."""
    for variant in ("Code", "VSCodium", "Cursor"):
        root = tmp_path / variant / "User" / "snippets"
        root.mkdir(parents=True)
        (root / "test.code-snippets").write_text("{}")

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    results = core_snippets.scan_vscode_snippets()
    apps = {r["app"] for r in results}
    assert apps == {"Code", "VSCodium", "Cursor"}


def test_scan_empty_when_no_vscode(tmp_path, monkeypatch):
    """No VS Code installation → empty scan (not an error)."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert core_snippets.scan_vscode_snippets() == []


# -------------------------------------------- import via the unified path
def test_import_file_vscode_roundtrip(tmp_path):
    """The existing vscode parser still works via the unified import."""
    p = tmp_path / "test.code-snippets"
    p.write_text('{"my snippet": {"prefix": "ms", "body": ["<div>hi</div>"]}}')
    items = core_snippets.import_file("vscode", str(p))
    assert len(items) == 1
    assert items[0]["title"] == "my snippet"


def test_import_file_masscode_roundtrip(tmp_path):
    """massCode databases import through the same unified entry point."""
    import sqlite3
    db = tmp_path / "masscode.sqlite"
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE snippets (
            id INTEGER PRIMARY KEY, name TEXT, content TEXT,
            tags TEXT, created INTEGER, updated INTEGER);
        CREATE TABLE tags (id INTEGER PRIMARY KEY, name TEXT);
    """)
    con.execute("INSERT INTO snippets (id, name, content, tags)"
                " VALUES (1, 'test snippet', '<b>x</b>', '[]')")
    con.commit()
    con.close()
    items = core_snippets.import_file("masscode", str(db))
    assert len(items) == 1
    assert items[0]["title"] == "test snippet"
