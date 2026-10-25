"""Regression tests for the pre-release security findings (SEC-1..4),
GitHub issues #3 #4 #5 #6."""

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

import pytest

from fengrid.core import indexer as core_indexer
from fengrid.core.snippets import _md_inline


@pytest.fixture()
def con(tmp_path):
    from PySide6.QtGui import QGuiApplication
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if QGuiApplication.instance() is None:
        QGuiApplication([])
    from fengrid.core import db as core_db
    c = core_db.connect(str(tmp_path / "t.db"))
    yield c
    c.close()


# ------------------------------------------------------ SEC-1 (#3)
def test_fiddle_doc_js_breakout_escaped(con, tmp_path):
    from fengrid.bridges.code import Code
    # an asset whose PATH carries a script-closing sequence
    src = con.execute(
        "INSERT INTO source(kind, path, label, enabled)"
        " VALUES ('folder', ?, 't', 1)", (str(tmp_path),)).lastrowid
    aid = con.execute(
        "INSERT INTO asset(source_id, kind, name, path)"
        " VALUES (?, 'icon', 'evil', ?)",
        (src, str(tmp_path) + "/x</script><img src=1>.svg")).lastrowid
    con.commit()
    code = Code(con)
    doc = code.fiddle_doc("<p>hi</p>", "p{}", "var p = \"[[ evil ]]\"")
    body = doc.split("<script>", 1)[1]
    # the expanded path inside the script element must not contain a
    # raw script-closing sequence
    assert "</script><img" not in body


def test_fiddle_doc_style_breakout_escaped(con):
    from fengrid.bridges.code import Code
    code = Code(con)
    doc = code.fiddle_doc("<p>hi</p>",
                          'a::after{content:"</style><script>x()"',
                          "")
    style = doc.split("<style>", 1)[1].split("</style>", 1)[0]
    assert "</style><script" not in style


# ------------------------------------------------------ SEC-2 (#4)
def test_md_inline_url_injection_escaped():
    out = _md_inline("![a](http://x\"><script>alert(1)</script>)")
    assert "<script>" not in out
    assert "&quot;" in out or "&lt;" in out
    # quotes inside the URL are neutralized before attribute embedding
    out2 = _md_inline('[click](http://x"onmouseover="alert(1))')
    assert out2.startswith('<a href="http://x&quot;onmouseover=')
    assert 'onmouseover="alert' not in out2


def test_md_inline_normal_markdown_unaffected():
    assert _md_inline("**bold** and `code` and [l](http://a.b)") == (
        "<strong>bold</strong> and <code>code</code>"
        ' and <a href="http://a.b">l</a>')


# ------------------------------------------------------ SEC-3 (#5)
def test_identify_skips_color_count_for_huge_headers(tmp_path, monkeypatch):
    import PIL.Image as PILImage

    class FakeIM(SimpleNamespace):
        def convert(self, mode):
            raise AssertionError("convert() must not run on huge rasters")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    fake = FakeIM(width=100000, height=100000, size=(100000, 100000),
                  mode="RGB")

    class FakeOpen:
        def __call__(self, path):
            return fake

    monkeypatch.setattr(core_indexer.Image, "open", FakeOpen())
    p = tmp_path / "huge.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n")     # existence only; open is faked
    info = core_indexer.identify(str(p))
    assert info["mono"] == 0
    assert info["width"] == 100000


def test_identify_small_raster_still_counts(tmp_path, monkeypatch):
    from PIL import Image as PILImage
    p = tmp_path / "tiny.png"
    PILImage.new("L", (4, 4), 128).save(p)
    info = core_indexer.identify(str(p))
    assert info["width"] == 4 and info["mono"] == 1


# ------------------------------------------------------ SEC-4 (#6)
def test_svg_doctype_rejected_without_defusedxml(tmp_path, monkeypatch):
    p = tmp_path / "bomb.svg"
    p.write_text('<?xml version="1.0"?><!DOCTYPE svg ['
                 '<!ENTITY a "aaaa"><!ENTITY b "&a;&a;">'
                 ']><svg xmlns="http://www.w3.org/2000/svg"'
                 ' width="10" height="10"><text>&b;</text></svg>',
                 encoding="utf-8")
    monkeypatch.setattr(core_indexer, "_HAVE_DEFUSEDXML", False)
    assert core_indexer._svg_parse_safe(str(p)) is None
    info = core_indexer.identify(str(p))
    assert info["width"] is None and info["height"] is None


def test_svg_plain_parses_without_defusedxml(tmp_path, monkeypatch):
    p = tmp_path / "plain.svg"
    p.write_text('<svg xmlns="http://www.w3.org/2000/svg"'
                 ' width="12" height="8"></svg>', encoding="utf-8")
    monkeypatch.setattr(core_indexer, "_HAVE_DEFUSEDXML", False)
    assert core_indexer._svg_parse_safe(str(p)) is not None
    info = core_indexer.identify(str(p))
    assert info["width"] == 12 and info["height"] == 8


def test_svg_with_defusedxml_parses_doctype(tmp_path, monkeypatch):
    p = tmp_path / "dt.svg"
    p.write_text('<?xml version="1.0"?><!DOCTYPE svg><svg'
                 ' xmlns="http://www.w3.org/2000/svg"'
                 ' width="5" height="5"></svg>', encoding="utf-8")
    monkeypatch.setattr(core_indexer, "_HAVE_DEFUSEDXML", True)
    assert core_indexer._svg_parse_safe(str(p)) is not None
