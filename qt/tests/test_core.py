"""Core smoke tests: db, scanner, indexer, export, migrate, settings.

Pure headless — no Qt imports (the core is Qt-free by design). Run with:
    cd qt && .venv/bin/python -m pytest -q
"""

import pytest
from PIL import Image

from fengrid.core import db, indexer, migrate, scanner, settings
from fengrid.core import export as fx
from fengrid.core.export import ExportError


@pytest.fixture()
def lib(tmp_path):
    con = db.connect(tmp_path / "library.db")
    yield con
    con.close()


def make_icon(path, color=(10, 200, 180), size=(64, 64)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)


def make_svg(path, w=24, h=24):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}">'
        "<rect width='8' height='8'/></svg>", encoding="utf-8")


# --------------------------------------------------------------------- scanner

def test_derive_meta_theme_layout(tmp_path):
    root = tmp_path / "icons"
    p = root / "Adwaita" / "16x16" / "actions" / "foo.png"
    p.parent.mkdir(parents=True)
    meta = scanner.derive_meta(str(p), str(root))
    assert meta["name"] == "foo"
    assert meta["theme"] == "Adwaita"
    assert meta["context"] == "actions"
    assert meta["size_px"] == 16
    assert meta["ext"] == "png"


def test_derive_meta_scalable_and_pixmaps(tmp_path):
    root = tmp_path / "icons"
    meta = scanner.derive_meta(str(root / "Adwaita/scalable/apps/bar.svg"), str(root))
    assert meta["theme"] == "Adwaita"
    assert meta["context"] == "apps"
    assert meta["size_px"] is None
    meta = scanner.derive_meta(str(tmp_path / "pixmaps" / "baz.png"),
                               str(tmp_path / "pixmaps"))
    assert meta["theme"] == "pixmaps"
    assert meta["size_px"] is None


def test_fold_nested(tmp_path):
    a = tmp_path / "a"
    b = a / "b"
    a.mkdir()
    b.mkdir()
    out = scanner.fold_nested([b, a])
    assert [str(p) for p in out] == [str(a.resolve())]


# --------------------------------------------------------------------- indexer

def test_scan_incremental_and_prune(tmp_path, lib):
    root = tmp_path / "icons"
    make_icon(root / "Adwaita/16x16/actions/foo.png")
    make_svg(root / "Adwaita/scalable/apps/bar.svg")
    make_icon(root / "hicolor/48x48/mimetypes/baz.png", (0, 0, 0))

    sources = indexer.ensure_sources(lib, [root])
    r1 = indexer.scan(lib, sources)
    assert r1["new"] == 3 and r1["total"] == 3

    row = lib.execute(
        "SELECT theme, context, size_px, mono FROM asset WHERE name = 'foo'"
    ).fetchone()
    assert (row["theme"], row["context"], row["size_px"]) == ("Adwaita", "actions", 16)
    assert row["mono"] == 1  # single-color raster

    svg_row = lib.execute(
        "SELECT width, height, mono FROM asset WHERE name = 'bar'").fetchone()
    assert (svg_row["width"], svg_row["height"]) == (24, 24)
    assert svg_row["mono"] is None

    r2 = indexer.scan(lib, sources)
    assert r2["unchanged"] == 3 and r2["new"] == 0 and r2["changed"] == 0

    make_icon(root / "Adwaita/16x16/actions/foo.png", (255, 0, 0))
    r3 = indexer.scan(lib, sources)
    assert r3["changed"] == 1

    (root / "Adwaita/16x16/actions/foo.png").unlink()
    r4 = indexer.scan(lib, sources)
    assert r4["pruned"] == 1


def test_variants_query(lib, tmp_path):
    root = tmp_path / "icons"
    make_icon(root / "Adwaita/16x16/actions/foo.png", size=(16, 16))
    make_icon(root / "Adwaita/32x32/actions/foo.png", size=(32, 32))
    sources = indexer.ensure_sources(lib, [root])
    indexer.scan(lib, sources)
    aid = lib.execute("SELECT id FROM asset WHERE size_px = 16").fetchone()[0]
    variants = db.variants_for(lib, aid)
    assert len(variants) == 1
    assert variants[0]["size_px"] == 32


# ---------------------------------------------------------------------- search

def test_search(lib, tmp_path):
    root = tmp_path / "icons"
    make_icon(root / "Adwaita/16x16/actions/search-marker.png")
    make_icon(root / "Adwaita/16x16/actions/other.png", (1, 1, 1))
    sources = indexer.ensure_sources(lib, [root])
    indexer.scan(lib, sources)
    # search "marker" (a token inside the intended asset's name) — searching
    # "search" would also hit the other asset's indexed tmp_path token
    # "search0" from the pytest tmp dir name
    ids = db.search(lib, "marker")
    assert len(ids) == 1
    name = lib.execute(
        "SELECT name FROM asset WHERE id = ?", (ids[0],)).fetchone()[0]
    assert name == "search-marker"


# -------------------------------------------------------------------- settings

def test_settings_roundtrip(lib):
    settings.set(lib, "theme", "dark")
    assert settings.get(lib, "theme") == "dark"
    settings.set(lib, "theme", "light")
    assert settings.get(lib, "theme") == "light"
    assert settings.get(lib, "missing", "fallback") == "fallback"


# --------------------------------------------------------------------- migrate

def test_migrate_roundtrip(lib, tmp_path):
    root = tmp_path / "icons"
    make_icon(root / "Adwaita/16x16/actions/foo.png")
    sources = indexer.ensure_sources(lib, [root])
    indexer.scan(lib, sources)

    counts = migrate.import_state(lib, {
        "tags": {"pick": ["foo"]},
        "collections": {"faves": ["foo", "missing-asset"]},
    })
    assert counts["tag_links"] == 1
    assert counts["collection_links"] == 1
    assert counts["unmatched"] == 1

    aid = lib.execute("SELECT id FROM asset WHERE name = 'foo'").fetchone()[0]
    assert db.tags_for(lib, aid) == ["pick"]

    out = migrate.export_state(lib)
    assert out["tags"] == {"pick": ["foo"]}
    assert out["collections"] == {"faves": ["foo"]}

    # idempotent re-import
    counts2 = migrate.import_state(lib, {"tags": {"pick": ["foo"]}})
    assert counts2["tag_links"] == 1


# ---------------------------------------------------------------------- export

def test_export_png_to_ico(tmp_path):
    src = tmp_path / "in.png"
    make_icon(src, size=(64, 64))
    out = fx.export(src, tmp_path / "out", "my icon", "ico", 32)
    assert out.exists()
    with Image.open(out) as im:
        assert im.size == (32, 32)


def test_export_jpeg_default_size(tmp_path):
    src = tmp_path / "in.png"
    make_icon(src, size=(64, 64))
    out = fx.export(src, tmp_path / "out", "x", "jpeg", None)
    assert out.suffix == ".jpeg"
    with Image.open(out) as im:
        assert im.size == (64, 64)


def test_export_validation(tmp_path):
    src = tmp_path / "in.png"
    make_icon(src)
    with pytest.raises(ExportError):
        fx.export(src, tmp_path / "out", "x", "exe")
    with pytest.raises(ExportError):
        fx.export(src, tmp_path / "out", "x", "png", 4)      # below 8
    with pytest.raises(ExportError):
        fx.export(src, tmp_path / "out", "x", "png", 2048)   # above 1024


def test_export_svg_rejected_in_core(tmp_path):
    svg = tmp_path / "s.svg"
    make_svg(svg)
    with pytest.raises(ExportError):
        fx.export(svg, tmp_path / "out", "s", "png")


# ----------------------------------------------------------------------- fonts

import shutil
import zipfile
from pathlib import Path

from fengrid.core import fonts as ffx

REPO_FONT = (Path(__file__).resolve().parents[2] / "fonts"
             / "BebasNeue-Regular.ttf")


@pytest.fixture()
def fontroot(tmp_path, lib):
    if not REPO_FONT.exists():
        pytest.skip("bundled font missing from this checkout")
    root = tmp_path / "fnt"
    (root / "Bebas").mkdir(parents=True)  # shutil.copy does not mkdir
    shutil.copy(REPO_FONT, root / "Bebas" / "BebasNeue-Regular.ttf")
    sources = indexer.ensure_sources(lib, [root], kinds=("fontroot",))
    return root, sources


def test_font_columns_migrated(lib):
    cols = {r[1] for r in lib.execute("PRAGMA table_info(asset)")}
    assert {"family", "style", "weight", "italic"} <= cols


def test_font_columns_migrate_from_m1_schema(tmp_path):
    """An M1-era db (no font columns) must migrate on connect, not crash."""
    old = tmp_path / "old.db"
    con = db.connect(old)
    # simulate the M1 schema: drop the family index first (SQLite refuses to
    # drop a column an index depends on), then the columns _migrate added
    con.execute("DROP INDEX IF EXISTS idx_asset_family")
    for col in ("family", "style", "weight", "italic"):
        con.execute(f"ALTER TABLE asset DROP COLUMN {col}")
    con.commit()
    con.close()
    con2 = db.connect(old)  # reconnect: migration must restore the columns
    cols = {r[1] for r in con2.execute("PRAGMA table_info(asset)")}
    assert {"family", "style", "weight", "italic"} <= cols
    con2.close()


def test_identify_font():
    if not REPO_FONT.exists():
        pytest.skip("bundled font missing from this checkout")
    meta = ffx.identify_font(str(REPO_FONT))
    assert meta is not None
    assert meta["family"] == "Bebas Neue"
    assert meta["weight"] == 400
    assert meta["italic"] == 0


def test_identify_font_garbage(tmp_path):
    p = tmp_path / "x.ttf"
    p.write_bytes(b"definitely not a font file")
    assert ffx.identify_font(str(p)) is None


def test_scan_fonts_incremental(fontroot, lib):
    root, sources = fontroot
    r1 = indexer.scan_fonts(lib, sources)
    assert r1["new"] == 1 and r1["total"] == 1
    row = lib.execute(
        "SELECT family, weight, italic, ext, theme FROM asset"
        " WHERE kind = 'font'").fetchone()
    assert row["family"] == "Bebas Neue"
    assert row["weight"] == 400 and row["italic"] == 0
    assert row["ext"] == "ttf" and row["theme"] == "Bebas"
    r2 = indexer.scan_fonts(lib, sources)
    assert r2["unchanged"] == 1 and r2["new"] == 0 and r2["changed"] == 0


def test_scan_fonts_prune(fontroot, lib):
    root, sources = fontroot
    indexer.scan_fonts(lib, sources)
    (root / "Bebas" / "BebasNeue-Regular.ttf").unlink()
    r = indexer.scan_fonts(lib, sources)
    assert r["pruned"] == 1
    assert lib.execute(
        "SELECT COUNT(*) FROM asset WHERE kind = 'font'").fetchone()[0] == 0


def test_font_export_css(fontroot, lib, tmp_path):
    _, sources = fontroot
    indexer.scan_fonts(lib, sources)
    out = ffx.export_family_css(lib, "Bebas Neue", tmp_path / "out")
    text = out.read_text(encoding="utf-8")
    assert "@font-face" in text and "Bebas Neue" in text
    assert "font-weight: 400" in text


def test_font_export_zip(fontroot, lib, tmp_path):
    _, sources = fontroot
    indexer.scan_fonts(lib, sources)
    out = ffx.export_family_zip(lib, "Bebas Neue", tmp_path / "out")
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
    assert "css/fonts.css" in names
    assert any(n.startswith("fonts/") for n in names)
    assert "README.txt" in names


def test_font_export_unknown_family(lib, tmp_path):
    with pytest.raises(ValueError):
        ffx.export_family_css(lib, "Nope Sans", tmp_path)
    with pytest.raises(ValueError):
        ffx.export_family_zip(lib, "Nope Sans", tmp_path)


# ---------------------------------------------------------------------- colors

import json as _json

from fengrid.core import colors as fcx


def test_hex_hsl_conversions():
    assert fcx.rgb2hex(255, 0, 0) == "#ff0000"
    assert fcx.hex2rgb("#FF0000") == (255, 0, 0)
    assert fcx.hex2rgb("#F00") == (255, 0, 0)
    h, s, l = fcx.rgb2hsl(255, 0, 0)
    assert (round(h), round(s), round(l)) == (0, 100, 50)
    assert fcx.hsl2rgb(0, 100, 50) == (255, 0, 0)


def test_contrast_and_wcag_labels():
    assert abs(fcx.contrast((255, 255, 255), (0, 0, 0)) - 21.0) < 0.01
    assert fcx.wcag_label(21) == "AAA"
    assert fcx.wcag_label(4.6) == "AA"
    assert fcx.wcag_label(3.1) == "AA·lg"
    assert fcx.wcag_label(2.9) == "fail"
    # best_ink picks white on the dark brand bg
    assert fcx.best_ink((16, 20, 24)) == "#FFFFFF"


def test_generate_deterministic_locked_passthrough():
    sw = [{"hex": "#123456", "locked": True}]
    r1 = fcx.generate("triadic", sw, base_hue=100)
    r2 = fcx.generate("triadic", sw, base_hue=100)
    assert r1 == r2                                  # fixed seed = fixed roll
    assert r1[0] == {"hex": "#123456", "locked": True}   # locked passes through
    assert len(r1) == 5
    with pytest.raises(ValueError):
        fcx.generate("nope", [], base_hue=1)


def test_generate_all_rules_valid_hexes():
    for rule in fcx.HARMONIES:
        out = fcx.generate(rule, [], base_hue=50)
        assert len(out) == 5
        for s in out:
            assert s["hex"].startswith("#") and len(s["hex"]) == 7


def test_palette_crud_roundtrip(lib):
    pid = fcx.save_palette(lib, "Midnight Garden",
                           ["#101418", "#39B8C4", "#F5C25C"], "dark, brand")
    rows = fcx.list_palettes(lib)
    assert rows[0]["id"] == pid
    assert rows[0]["name"] == "Midnight Garden"
    assert rows[0]["colors"] == ["#101418", "#39B8C4", "#F5C25C"]
    # update path (same id)
    fcx.save_palette(lib, "Renamed", ["#FFFFFF"], "", palette_id=pid)
    rows = fcx.list_palettes(lib)
    assert rows[0]["name"] == "Renamed" and rows[0]["colors"] == ["#FFFFFF"]
    assert fcx.palette_colors(lib, pid) == [{"hex": "#FFFFFF", "locked": False}]
    # search + delete + unknown id
    assert fcx.list_palettes(lib, q="rename")[0]["id"] == pid
    assert fcx.list_palettes(lib, q="zzz") == []
    fcx.delete_palette(lib, pid)
    assert fcx.list_palettes(lib) == []
    with pytest.raises(ValueError):
        fcx.save_palette(lib, "x", ["#000000"], palette_id=999)


def test_color_name_anchors():
    assert fcx.color_name("#39B8C4") == "Pane Teal"
    assert fcx.color_name("#FFFFFF") == "White"
    assert fcx.color_name("#101418") == "Night Glass"


def test_color_exports(lib, tmp_path):
    hexes = ["#101418", "#39B8C4", "#F5C25C"]
    css = fcx.export_css("Midnight Garden", hexes)
    assert "--midnight-garden-1: #101418;" in css
    data = _json.loads(fcx.export_json("Midnight Garden", hexes))
    assert data["colors"] == hexes
    svg = fcx.board_svg("Midnight Garden", hexes)
    assert "<svg" in svg and "#101418" in svg and "fengrid" in svg
    assert fcx.write_exports("Midnight Garden", hexes, tmp_path, "css").exists()
    assert fcx.write_exports("Midnight Garden", hexes, tmp_path, "json").exists()
    assert fcx.write_exports("Midnight Garden", hexes, tmp_path, "svg").exists()
    png = fcx.write_exports("Midnight Garden", hexes, tmp_path, "png")
    assert png.exists() and png.stat().st_size > 5000  # 2x board render
    with pytest.raises(ValueError):
        fcx.write_exports("x", hexes, tmp_path, "exe")


# --------------------------------------------------------------------- glprobe

from fengrid import glprobe


def test_fallback_respects_explicit_overrides(monkeypatch):
    monkeypatch.setenv("QT_QUICK_BACKEND", "software")
    assert glprobe.needs_software_fallback() is False
    monkeypatch.delenv("QT_QUICK_BACKEND")
    monkeypatch.setenv("QSG_RHI_BACKEND", "opengl")
    assert glprobe.needs_software_fallback() is False
    monkeypatch.delenv("QSG_RHI_BACKEND")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    assert glprobe.needs_software_fallback() is False


def test_fallback_false_without_display(monkeypatch):
    # no display connections at all: Qt's own error is the honest signal,
    # and the ctypes probes must return False without crashing (XOpenDisplay
    # with no DISPLAY returns NULL)
    for var in ("QT_QUICK_BACKEND", "QSG_RHI_BACKEND", "QT_QPA_PLATFORM",
                "DISPLAY", "WAYLAND_DISPLAY", "WAYLAND_SOCKET"):
        monkeypatch.delenv(var, raising=False)
    assert glprobe.needs_software_fallback() is False
    assert glprobe._glx_ok() is False


def test_fallback_probes_egl_on_wayland(monkeypatch):
    monkeypatch.delenv("QT_QUICK_BACKEND", raising=False)
    monkeypatch.delenv("QSG_RHI_BACKEND", raising=False)
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setenv("WAYLAND_DISPLAY", "qa-test")  # enter the EGL branch
    # whatever _egl_ok reports, the decision must follow it without crashing
    result = glprobe.needs_software_fallback()
    assert result is (not glprobe._egl_ok())


# ------------------------------------------------------------------- snippets

from fengrid.core import snippets as snp


def test_map_language():
    assert snp.map_language("html") == ("html", "web", None)
    assert snp.map_language("md") == ("html", "markdown", None)
    assert snp.map_language("TypeScript") == ("js", "web", None)
    assert snp.map_language("javascriptreact") == ("js", "web", None)
    assert snp.map_language("cobol") == ("js", "web", "cobol")
    assert snp.map_language(None) == ("html", "web", None)


def test_jsonc_loads():
    text = ('{\n  // line comment\n  "a": {"prefix": "x", /* block */'
            ' "body": ["line1", "line2",]},\n}')
    data = snp.jsonc_loads(text)
    assert data["a"]["prefix"] == "x"
    assert data["a"]["body"] == ["line1", "line2"]


def test_parse_vscode():
    text = ('{ "make-a-button": {'
            '"title": "Make a button", "scope": "html", "prefix": "btn",'
            '"body": ["<button class=\\"x\\">hi</button>"] },'
            ' "raw": {"prefix": "raw", "scope": "cobol",'
            '"body": ["MOVE A TO B."]}}')
    out = snp.parse_vscode(text)
    assert len(out) == 2
    assert out[0]["title"] == "Make a button"
    assert out[0]["html"] == '<button class="x">hi</button>'
    assert out[0]["language"] == "web"
    assert "btn" in out[0]["tags"]
    assert out[1]["js"] == "MOVE A TO B."          # unmapped → JS pane
    assert "lang:cobol" in out[1]["tags"]


def test_masscode_import(tmp_path):
    import sqlite3 as s3
    db_path = tmp_path / "db.sqlite"
    conn = s3.connect(db_path)
    conn.execute("CREATE TABLE snippets (id INTEGER PRIMARY KEY, name TEXT,"
                 " content TEXT, tags TEXT, is_deleted INTEGER DEFAULT 0)")
    conn.execute("CREATE TABLE tags (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("CREATE TABLE snippet_tags (snippet_id INTEGER,"
                 " tag_id INTEGER)")
    conn.execute("INSERT INTO tags (id, name) VALUES (1, 'ui'), (2, 'css')")
    frag = ('[{"language": "css", "value": "body{color:red}"},'
            ' {"language": "javascript", "value": "console.log(1)"}]')
    conn.execute("INSERT INTO snippets (name, content, tags) VALUES"
                 " (?, ?, ?)", ("my snippet", frag, "[1, 2]"))
    conn.execute("INSERT INTO snippets (name, content) VALUES (?, ?)",
                 ("plain note", "just text"))
    conn.commit()
    conn.close()

    out = snp.parse_masscode_db(db_path)
    assert len(out) == 2
    assert out[0]["title"] == "my snippet"
    assert out[0]["css"] == "body{color:red}"
    assert out[0]["js"] == "console.log(1)"
    assert "ui" in out[0]["tags"] and "css" in out[0]["tags"]
    # plain-text row lands in the JS pane (0.x behaviour)
    assert out[1]["js"] == "just text"


def test_snippet_crud(lib):
    sid = snp.create_snippet(lib, "T", "d", "web", "<p>", "", "", "a, b")
    row = snp.get_snippet(lib, sid)
    assert row["title"] == "T" and row["tags"] == "a, b"
    snp.update_snippet(lib, sid, "T2", "d", "web", "", "", "", "")
    assert snp.get_snippet(lib, sid)["title"] == "T2"
    assert len(snp.list_snippets(lib, q="t2")) == 1
    assert len(snp.list_snippets(lib, lang="markdown")) == 0
    assert len(snp.list_snippets(lib, sort="title")) == 1
    snp.delete_snippet(lib, sid)
    assert snp.get_snippet(lib, sid) is None


def test_snippet_tag_cloud(lib):
    snp.create_snippet(lib, "A", "", "web", "", "", "", "x, y")
    snp.create_snippet(lib, "B", "", "web", "", "", "", "x")
    cloud = snp.tag_cloud(lib)
    names = [n for n, _ in cloud]
    assert names[0] == "x"          # highest count first
    assert dict(cloud)["y"] == 1
