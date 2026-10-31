"""WebEngine availability gating (#32).

GL-less-display crash class: whether Chromium survives a display
without usable hardware GL is an EMPIRICAL question, so the app
measures it in a crash-isolated probe child (webengine_probe.py)
instead of assuming. The env contract pinned here:

- FENGRID_SOFTWARE_DISPLAY=1  — set by __main__ when the GL probe finds
  no usable GL (software scene graph / EGL-software display class).
- FENGRID_WEBENGINE_OK=1      — the probe child survived: previews stay.
- FENGRID_FORCE_WEBENGINE=1   — explicit user override (Settings
  "Always on" is the persisted equivalent).
- FENGRID_NO_WEBENGINE=1      — hard off (Settings "Off"); wins over
  everything.

These tests run WITHOUT QApplication: webengine_available() and
register_asset_scheme() are pure import/env checks, and
make_preview_profile() short-circuits to None before it touches the
connection.
"""

import pytest

from fengrid import web


@pytest.fixture
def _clean_webenv(monkeypatch):
    for var in ("FENGRID_NO_WEBENGINE", "FENGRID_SOFTWARE_DISPLAY",
                "FENGRID_WEBENGINE_OK", "FENGRID_FORCE_WEBENGINE"):
        monkeypatch.delenv(var, raising=False)


def test_normal_display_still_has_webengine(_clean_webenv):
    # QA/CI venv ships the full PySide6, so the wheel is importable.
    assert web.webengine_available() is True


def test_no_webengine_lever_still_wins(_clean_webenv, monkeypatch):
    monkeypatch.setenv("FENGRID_NO_WEBENGINE", "1")
    monkeypatch.setenv("FENGRID_FORCE_WEBENGINE", "1")
    monkeypatch.setenv("FENGRID_WEBENGINE_OK", "1")
    assert web.webengine_available() is False


def test_software_display_degrades_to_previewless(_clean_webenv, monkeypatch):
    # probe failed (or never ran) and nothing overrode it: preview-less
    monkeypatch.setenv("FENGRID_SOFTWARE_DISPLAY", "1")
    assert web.webengine_available() is False
    assert web.register_asset_scheme() is False
    assert web.initialize_webengine() is False
    assert web.make_preview_profile(None) is None


def test_probe_ok_keeps_previews_on_software_display(_clean_webenv,
                                                     monkeypatch):
    monkeypatch.setenv("FENGRID_SOFTWARE_DISPLAY", "1")
    monkeypatch.setenv("FENGRID_WEBENGINE_OK", "1")
    assert web.webengine_available() is True


def test_force_webengine_overrides_software_display(_clean_webenv,
                                                    monkeypatch):
    monkeypatch.setenv("FENGRID_SOFTWARE_DISPLAY", "1")
    monkeypatch.setenv("FENGRID_FORCE_WEBENGINE", "1")
    assert web.webengine_available() is True
