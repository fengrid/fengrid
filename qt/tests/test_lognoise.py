"""Scan log-noise gate (issue #63): one line per warning class per scan.

fontTools logs a head-table timestamp warning (and, for WOFF2 files, a
missing-brotli ERROR) PER FILE during font scans; PIL warns per palette
PNG during icon scans. The gate dedupes both channels and summarizes the
suppressed repeats when the scan ends. Core tests are Qt-free.
"""
import logging
import os
import shutil
import sys
import warnings
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from fengrid.core import db, indexer, lognoise
from fengrid.core import fonts as ffx

REPO_FONT = (Path(__file__).resolve().parents[2] / "fonts"
             / "BebasNeue-Regular.ttf")


@pytest.fixture()
def lib(tmp_path):
    con = db.connect(tmp_path / "library.db")
    yield con
    con.close()


# ------------------------------------------------------------- brotli probe

def test_brotli_probe_returns_bool():
    assert isinstance(ffx.brotli_available(), bool)


def test_identify_font_skips_woff2_without_brotli(tmp_path, monkeypatch,
                                                  caplog):
    """The short-circuit must never reach fontTools' WOFF2Reader — the old
    path logged an ERROR per file (caplog proves no such record exists)."""
    monkeypatch.setattr(ffx, "brotli_available", lambda: False)
    from fontTools.ttLib import woff2 as ft_woff2

    def boom(*a, **k):
        raise AssertionError("WOFF2Reader was opened for a skipped file")

    monkeypatch.setattr(ft_woff2.WOFF2Reader, "__init__", boom)
    p = tmp_path / "FakeFont.woff2"
    p.write_bytes(b"wOF2 not really")
    with caplog.at_level(logging.ERROR):
        assert ffx.identify_font(str(p)) is None
    assert "Brotli" not in caplog.text


def test_identify_font_ttf_unaffected_by_brotli_probe(monkeypatch):
    if not REPO_FONT.exists():
        pytest.skip("bundled font missing from this checkout")
    monkeypatch.setattr(ffx, "brotli_available", lambda: False)
    meta = ffx.identify_font(str(REPO_FONT))
    assert meta is not None and meta["family"] == "Bebas Neue"


# ------------------------------------------------------------------- gate

def test_gate_dedupes_logging_and_counts(capsys):
    root = logging.getLogger()
    saved = root.handlers[:]
    root.handlers.clear()  # force records to reach logging.lastResort
    try:
        with lognoise.scan_noise_gate():
            lg = logging.getLogger("fontTools.ttLib.tables._h_e_a_d")
            for i in range(5):
                lg.warning("'%d' timestamp seems very low; "
                           "regarding as unix timestamp", 1700000000 + i)
        err = capsys.readouterr().err
    finally:
        root.handlers[:] = saved
    # first occurrence printed live once + once in the summary
    assert err.count("timestamp seems very low") == 2
    assert "(+4 more suppressed)" in err
    assert "[fontTools.ttLib.tables._h_e_a_d]" in err


def test_gate_dedupes_python_warnings(capsys):
    with lognoise.scan_noise_gate(), warnings.catch_warnings():
        warnings.simplefilter("always")
        for _ in range(3):
            warnings.warn("Palette images with Transparency expressed "
                          "in bytes should be converted to RGBA images")
    err = capsys.readouterr().err
    # the first warning is routed to the pre-existing showwarning (pytest's
    # recorder here); the gate's own proof is the counted summary line
    assert "fengrid: UserWarning: Palette images with Transparency" in err
    assert "(+2 more suppressed)" in err


def test_gate_counts_digit_varying_messages_together(capsys):
    """Per-file timestamps must not defeat the dedupe key."""
    root = logging.getLogger()
    saved = root.handlers[:]
    root.handlers.clear()
    try:
        with lognoise.scan_noise_gate():
            lg = logging.getLogger("fontTools.ttLib.tables._h_e_a_d")
            for stamp in range(3):
                lg.warning("'%d' timestamp out of range; ignoring top bytes",
                           stamp * 7919)
        err = capsys.readouterr().err
    finally:
        root.handlers[:] = saved
    assert "(+2 more suppressed)" in err


# ------------------------------------------------- scan_fonts woff2 skips

@pytest.fixture()
def fontroot(tmp_path, lib):
    if not REPO_FONT.exists():
        pytest.skip("bundled font missing from this checkout")
    root = tmp_path / "fnt"
    (root / "Bebas").mkdir(parents=True)
    shutil.copy(REPO_FONT, root / "Bebas" / "BebasNeue-Regular.ttf")
    for name in ("Some Web", "Other Web"):
        (root / "Bebas" / f"{name}.woff2").write_bytes(b"wOF2 fake")
    sources = indexer.ensure_sources(lib, [root], kinds=("fontroot",))
    return root, sources


def test_scan_fonts_skips_woff2_quietly_with_one_summary(
        fontroot, lib, monkeypatch, capsys):
    _root, sources = fontroot
    monkeypatch.setattr(ffx, "brotli_available", lambda: False)
    r = indexer.scan_fonts(lib, sources)
    assert r["new"] == 3 and r["total"] == 3
    # the woff2 rows keep filename + size, null font metadata
    rows = lib.execute(
        "SELECT name, family, bytes FROM asset WHERE kind = 'font'"
        " AND ext = 'woff2'").fetchall()
    assert len(rows) == 2
    assert all(row["family"] is None for row in rows)
    assert {row["name"] for row in rows} == {"Some Web", "Other Web"}
    err = capsys.readouterr().err
    assert "skipped WOFF2 identification for 2 font file(s)" in err
    assert "Brotli" not in err  # the per-file flood is gone
    # a second scan touches nothing pending → no duplicate summary
    r2 = indexer.scan_fonts(lib, sources)
    assert r2["unchanged"] == 3
    err2 = capsys.readouterr().err
    assert "skipped WOFF2" not in err2


def test_scan_fonts_no_summary_when_brotli_present(
        fontroot, lib, monkeypatch, capsys):
    _root, sources = fontroot
    monkeypatch.setattr(ffx, "brotli_available", lambda: True)
    indexer.scan_fonts(lib, sources)
    err = capsys.readouterr().err
    assert "skipped WOFF2" not in err