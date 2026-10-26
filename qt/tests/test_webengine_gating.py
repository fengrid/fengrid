"""WebEngine availability gating (#32).

GL-less-display crash class: when the GL probe finds no usable hardware
GL the whole app runs on the software scene graph, and Chromium's GPU
process segfaults natively there EVEN WITH --disable-gpu (reporter's
bisect run on a rebuilt bundle: FENGRID_NO_WEBENGINE=1 was the only
stable configuration). So __main__ sets FENGRID_SOFTWARE_DISPLAY=1 from
the probe result and WebEngine degrades to the preview-less shell — the
same graceful path as a machine without the QtWebEngineCore wheel.
FENGRID_FORCE_WEBENGINE=1 opts back in.

These tests pin the env-var contract. They run WITHOUT QApplication:
webengine_available() and register_asset_scheme() are pure import/env
checks, and make_preview_profile() short-circuits to None before it
touches the connection.
"""

import pytest

from fengrid import web


@pytest.fixture
def _clean_webenv(monkeypatch):
    for var in ("FENGRID_NO_WEBENGINE", "FENGRID_SOFTWARE_DISPLAY",
                "FENGRID_FORCE_WEBENGINE"):
        monkeypatch.delenv(var, raising=False)


def test_normal_display_still_has_webengine(_clean_webenv):
    # QA/CI venv ships the full PySide6, so the wheel is importable.
    assert web.webengine_available() is True


def test_software_display_degrades_to_previewless(_clean_webenv, monkeypatch):
    monkeypatch.setenv("FENGRID_SOFTWARE_DISPLAY", "1")
    assert web.webengine_available() is False
    assert web.register_asset_scheme() is False
    assert web.initialize_webengine() is False
    assert web.make_preview_profile(None) is None


def test_force_webengine_overrides_software_display(_clean_webenv,
                                                    monkeypatch):
    monkeypatch.setenv("FENGRID_SOFTWARE_DISPLAY", "1")
    monkeypatch.setenv("FENGRID_FORCE_WEBENGINE", "1")
    assert web.webengine_available() is True


def test_no_webengine_lever_still_wins(_clean_webenv, monkeypatch):
    monkeypatch.setenv("FENGRID_NO_WEBENGINE", "1")
    monkeypatch.setenv("FENGRID_FORCE_WEBENGINE", "1")
    assert web.webengine_available() is False
