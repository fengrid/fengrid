"""Per-family custom preview text (#151).

The inspector's specimen field used to flip a pane-wide sampleCustom
flag whose only grid effect was the literal 'Fengrid 123' fallback —
typing a custom sample for the selected font blanked every other card
into the fallback. The custom sample now belongs to the FAMILY
(persisted as a JSON settings map), the grid reads it as one QVariantMap
property (no per-card slot calls — the #137 discipline), and the grid
chain is: master text (gridSample) → family sample → curated buckets.
"""
import json
import os
import sys

import pytest
from PySide6.QtCore import QCoreApplication as _QCoreApp  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from fengrid.bridges.fonts import Fonts         # noqa: E402
from fengrid.core import db as core_db          # noqa: E402
from fengrid.core import settings as core_settings  # noqa: E402


@pytest.fixture()
def fonts_bridge(tmp_path):
    # the Fonts bridge wires aboutToQuit at construction — an app object
    # must exist first (QCoreApplication suffices offscreen)
    _QCoreApp.instance() or _QCoreApp(sys.argv)

    con = core_db.connect(tmp_path / "library.db")
    sid = con.execute(
        "INSERT INTO source(kind, path, label, enabled)"
        " VALUES ('fontroot', ?, 't', 1)", (str(tmp_path),)).lastrowid
    for fam in ("Alpha", "Beta"):
        con.execute(
            "INSERT INTO asset(source_id, kind, name, path, family)"
            " VALUES (?, 'font', ?, ?, ?)",
            (sid, fam, str(tmp_path / f"{fam}.ttf"), fam))
    con.commit()
    db_path = str(tmp_path / "library.db")
    yield Fonts(con, db_path)
    con.close()


def test_family_sample_set_and_clear_persists(fonts_bridge):
    f = fonts_bridge
    assert f.familySamples == {}
    f.set_family_sample("Alpha", "Custom alpha passage")
    assert f.familySamples == {"Alpha": "Custom alpha passage"}
    # persisted to settings as JSON (survives a fresh bridge)
    stored = json.loads(core_settings.get(f._con, "family_samples", "{}"))
    assert stored == {"Alpha": "Custom alpha passage"}
    # whitespace-only text is treated as empty → cleared
    f.set_family_sample("Alpha", "   ")
    assert "Alpha" not in f.familySamples
    # unknown/empty family names are ignored, not stored
    f.set_family_sample("", "x")
    assert f.familySamples == {}


def test_family_sample_survives_rebuild(fonts_bridge):
    f = fonts_bridge
    f.set_family_sample("Beta", "Beta only")
    # a NEW bridge over the same db (what a restart does) still sees it
    f2 = Fonts(f._con, ".")
    assert f2.familySamples == {"Beta": "Beta only"}
    assert f2.familySamples["Beta"] == "Beta only"
