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
