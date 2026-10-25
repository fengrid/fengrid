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


# ------------------------------------------------------ SEC-5 (#7)
def test_folder_sniff_ignores_symlinked_dirs(tmp_path):
    from fengrid.core.ingest import import_folder
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "font.ttf").write_bytes(b"\x00\x01\x00\x00\x00")
    root = tmp_path / "root"
    root.mkdir()
    (root / "pic.png").write_bytes(
        b"\x89PNG\r\n\x1a\n")                 # icon file
    os.symlink(str(outside), str(root / "link"))
    out = import_folder(str(root))
    # the symlink must NOT drag the outside font tree into the sniff
    assert out["kind"] == "folder"


def test_watch_signature_ignores_symlink_targets(tmp_path):
    from fengrid.core.watch import signature
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "a.png").write_bytes(b"x" * 10)
    root = tmp_path / "watchroot"
    root.mkdir()
    os.symlink(str(outside), str(root / "link"))
    sig = signature(str(root))
    assert sig == "0:0:0"          # no regular files inside the root


# ------------------------------------------------------ SEC-6 (#8)
def test_import_zip_member_budget(tmp_path, monkeypatch):
    import zipfile
    from fengrid.core import ingest as core_ingest
    monkeypatch.setattr(core_ingest, "_ZIP_MAX_MEMBER_BYTES", 100)
    zpath = tmp_path / "bomb.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("a.png", b"\x89PNG\r\n\x1a\n" + b"x" * 200)
    out = core_ingest.import_zip(str(zpath), str(tmp_path / "data"))
    assert out["placed"] == 0 and out["failed"] >= 1
    assert any("member cap" in e for e in out["errors"])


def test_import_zip_total_budget(tmp_path, monkeypatch):
    import zipfile
    from fengrid.core import ingest as core_ingest
    monkeypatch.setattr(core_ingest, "_ZIP_MAX_TOTAL_BYTES", 150)
    zpath = tmp_path / "two.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("a.png", b"\x89PNG\r\n\x1a\n" + b"x" * 100)
        zf.writestr("b.png", b"\x89PNG\r\n\x1a\n" + b"x" * 100)
    out = core_ingest.import_zip(str(zpath), str(tmp_path / "data"))
    assert out["placed"] == 1
    assert any("total uncompressed budget" in e for e in out["errors"])


# ------------------------------------------------------ SEC-7 (#9)
def test_apply_regex_rejects_nested_quantifiers():
    from fengrid.core.patterns import apply_regex
    stem = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaX"
    # classic catastrophic pattern — must be rejected, not executed
    assert apply_regex(stem, "(a+)+$", "x") == stem
    # overlong patterns rejected outright
    assert apply_regex(stem, "a" * 600, "x") == stem
    # ordinary patterns still work
    assert apply_regex("photo_0001", r"_(\d{4})$", r"-v\1") == "photo-v0001"


def test_apply_regex_probe_kills_detector_evasion():
    """SEC-7 depth: `x+x+y` has NO groups (the textual detector can't
    see it) yet backtracks exponentially — the regex module's C-level
    timeout must abort it."""
    import time
    from fengrid.core import patterns as P
    if P._regex_mod is None:
        import pytest
        pytest.skip("regex module not installed — detector-only mode")
    stem = "x" * 2000             # uncapped this takes many seconds
    pat = "x+x+y"
    t0 = time.perf_counter()
    out = P.apply_regex(stem, pat, "x")
    elapsed = time.perf_counter() - t0
    assert out == stem             # runaway pattern → stem unchanged
    assert elapsed < 1.0, elapsed  # aborted by the C timeout budget
    # invalid patterns also fall back to the stem (regex.error path)
    assert P.apply_regex("f.png", "[unclosed", "y") == "f.png"
    # ordinary patterns still work through the guarded path
    assert P.apply_regex("photo_0002", r"_(\d{4})$", r"-v\1") == \
        "photo-v0002"


# ------------------------------------------------------ SEC-8 (#10)
def test_scheme_path_must_be_under_registered_roots(con, tmp_path):
    import os as _os
    from types import SimpleNamespace
    from fengrid.web.handlers import AssetSchemeHandler
    src = con.execute(
        "INSERT INTO source(kind, path, label, enabled)"
        " VALUES ('folder', ?, 't', 1)", (str(tmp_path / "lib"),)).lastrowid
    outside = tmp_path / "outside" / "secret.txt"
    outside.parent.mkdir()
    outside.write_text("top secret")
    # a CRAFTED row: asset table knows a path OUTSIDE any source root
    con.execute(
        "INSERT INTO asset(source_id, kind, name, path)"
        " VALUES (?, 'icon', 'crafted', ?)", (src, str(outside)))
    con.commit()
    handler = SimpleNamespace(_con=con)
    check = AssetSchemeHandler._path_is_registered.__get__(handler)
    assert check(str(outside)) is False           # crafted row rejected
    inside = tmp_path / "lib" / "ok.svg"
    inside.parent.mkdir()
    inside.write_text("<svg/>")
    con.execute(
        "INSERT INTO asset(source_id, kind, name, path)"
        " VALUES (?, 'icon', 'ok', ?)", (src, str(inside)))
    con.commit()
    assert check(str(inside)) is True
    # post-scan symlink swap: index points inside the root, but the
    # file is now a symlink OUT of it → rejected
    link = tmp_path / "lib" / "swap.svg"
    os.symlink(str(outside), link)
    assert check(str(link)) is False


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
