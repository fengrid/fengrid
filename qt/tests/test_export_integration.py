"""Export-integration core: fonts.css package (preview + save).

Exercises the multi-family CSS export the FontsCssDialog drives:
relative package paths, weight/style mapping, and the on-disk layout
(fonts.css + fonts/<Family>/<file>.woff2|.woff). Uses a REAL ttf so
fontTools can convert it.
"""

import shutil
from pathlib import Path

import pytest

from fengrid.core import db as core_db
from fengrid.core import exportplus as ep

REAL_TTF = "/usr/share/fonts/truetype/tuffy/tuffy_bold_italic.ttf"


@pytest.fixture()
def con():
    import sqlite3
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(core_db.SCHEMA)
    core_db._migrate(c)
    if not Path(REAL_TTF).is_file():
        pytest.skip("system Tuffy font not present")
    src_id = c.execute(
        "INSERT INTO source(kind, path, label, enabled)"
        " VALUES ('folder','/usr/share/fonts/truetype/tuffy','t',1)"
    ).lastrowid
    c.execute(
        "INSERT INTO asset(source_id, kind, name, path, family, ext,"
        " weight, italic) VALUES (?, 'font', 'Tuffy Bold Italic', ?,"
        " 'Tuffy', 'ttf', 700, 1)", (src_id, REAL_TTF))
    c.commit()
    return c


def test_css_preview_relative_paths(con):
    out = ep.css_preview(con, ["Tuffy"], ["woff2", "woff"])
    css = out["css"]
    assert '@font-face' in css
    assert 'url("fonts/tuffy_bold_italic.woff2")' in css
    assert 'url("fonts/tuffy_bold_italic.woff")' in css
    assert "font-weight: 700" in css
    assert "font-style: italic" in css
    # nothing is written by the preview
    assert all(isinstance(item["src"], str) for item in out["plan"])


def test_css_preview_unknown_family_is_empty(con):
    out = ep.css_preview(con, ["Ghost Family"])
    assert out["plan"] == []
    assert "@font-face" not in out["css"]


def test_css_package_writes_css_and_fonts(con, tmp_path):
    preview = ep.css_preview(con, ["Tuffy"], ["woff2", "woff"])
    out = ep.export_css_package(con, tmp_path, preview["css"],
                                ["Tuffy"], ["woff2", "woff"])
    assert out.name == "fonts.css"
    css = (tmp_path / "fonts.css").read_text(encoding="utf-8")
    assert 'url("fonts/tuffy_bold_italic.woff2")' in css
    # the referenced files exist AT the referenced relative paths, and
    # are real woff2/woff (fontTools flavors: 'wOF2' / 'wOFF' magic)
    woff2 = tmp_path / "fonts/tuffy_bold_italic.woff2"
    woff = tmp_path / "fonts/tuffy_bold_italic.woff"
    assert woff2.read_bytes()[:4] == b"wOF2"
    assert woff.read_bytes()[:4] == b"wOFF"


def test_css_package_saves_user_edited_css(con, tmp_path):
    ep.export_css_package(con, tmp_path,
                          "/* my custom stylesheet */\n@font-face {}",
                          ["Tuffy"], ["woff2"])
    assert "my custom stylesheet" in (
        tmp_path / "fonts.css").read_text(encoding="utf-8")


def test_css_package_no_families_raises(con, tmp_path):
    with pytest.raises(ep.ExportError):
        ep.export_css_package(con, tmp_path, "css", ["Ghost Family"])


def test_package_leaves_no_stage_dir(con, tmp_path):
    ep.export_css_package(con, tmp_path, "", ["Tuffy"], ["woff2"])
    assert not (tmp_path / ".fonts-stage").exists()


def test_fonts_zip_layout(con, tmp_path):
    """The spec layout: fonts.css at the root, fonts/<NAME>.<flavor>."""
    out = ep.export_fonts_zip(con, ["Tuffy"], tmp_path,
                              fmts=["woff2", "woff"],
                              include_original=True)
    import zipfile
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
    assert "fonts.css" in names
    assert "fonts/tuffy_bold_italic.woff2" in names
    assert "fonts/tuffy_bold_italic.woff" in names
    assert "fonts/tuffy_bold_italic.ttf" in names      # include_original
    css = out.read_bytes() if False else zipfile.ZipFile(out).read("fonts.css")
    assert b'url("fonts/tuffy_bold_italic.woff2")' in css
    assert b"file://" not in css                        # no absolute paths


def test_fonts_zip_user_css_verbatim(con, tmp_path):
    out = ep.export_fonts_zip(con, ["Tuffy"], tmp_path,
                              fmts=["woff2"], css_text="/* mine */")
    import zipfile
    assert zipfile.ZipFile(out).read("fonts.css") == b"/* mine */"
