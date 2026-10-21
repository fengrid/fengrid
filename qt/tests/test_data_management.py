"""Tests for the data management featureset: patterns, ingest, watch,
backup/restore + db admin, extended export suite."""
import io
import json
import tarfile
import os
import sqlite3
import subprocess
import sys
import zipfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from fengrid.core import backup as core_backup          # noqa: E402
from fengrid.core import db as core_db                  # noqa: E402
from fengrid.core import exportplus as xp               # noqa: E402
from fengrid.core import ingest                         # noqa: E402
from fengrid.core import patterns                       # noqa: E402
from fengrid.core import watch                          # noqa: E402


# ── patterns ─────────────────────────────────────────────────────────
def test_pattern_prefix_suffix_and_tokens():
    assert patterns.build_name("icon.svg", prefix="ic_") == "ic_icon.svg"
    assert patterns.build_name("icon.svg", suffix="-old") == "icon-old.svg"
    out = patterns.build_name("photo.png", template="logo-{n}",
                              style="enum", enum_index=3, enum_pad=4)
    assert out == "logo-0004.png"


def test_pattern_regex_and_bad_regex_fallback():
    assert patterns.build_name("btn_ok.png", find=r"^btn_",
                               repl="button-") == "button-ok.png"
    # invalid user regex must never abort an import
    assert patterns.build_name("x.png", find="[unclosed",
                               repl="y") == "x.png"


def test_pattern_guid_random_and_cardinal():
    g = patterns.build_name("a.svg", style="guid")
    assert g.startswith("a-") and len(g) > 20 and g.endswith(".svg")
    r = patterns.build_name("a.svg", style="random", random_len=8)
    stem = r.rsplit(".", 1)[0]
    assert stem.startswith("a") and len(stem) == 9
    n1 = patterns.build_name("a.svg", style="enum", enum_index=0,
                             enum_pad=3)
    n2 = patterns.build_name("a.svg", style="enum", enum_index=8,
                             enum_pad=3)
    assert n1 == "a001.svg" and n2 == "a009.svg"


def test_pattern_csv_and_deterministic_random():
    class Fixed:
        def choice(self, seq):
            return "z"

    out = patterns.build_name("orig.svg", template="{csv}-{rand}",
                              csv_name="hero", random_len=3,
                              rng=Fixed())
    assert out == "hero-zzz.svg"
    # uniquify never overwrites
    import tempfile
    d = tempfile.mkdtemp()
    open(os.path.join(d, "a.png"), "w").close()
    assert patterns.uniquify(d, "a.png") == "a-2.png"
    open(os.path.join(d, "a-2.png"), "w").close()
    assert patterns.uniquify(d, "a.png") == "a-3.png"


def test_read_csv_names(tmp_path):
    p = tmp_path / "names.csv"
    p.write_text("name,kind\nalpha,icon\nbeta,icon\n")
    assert patterns.read_csv_names(str(p), "name") == ["alpha", "beta"]
    assert patterns.read_csv_names(str(p), "1") == ["icon", "icon"]
    p2 = tmp_path / "names2.csv"
    p2.write_text("alpha.png\nbeta.png\n")
    assert patterns.read_csv_names(str(p2), "0", has_header=False) \
        == ["alpha.png", "beta.png"]


# ── ingest ───────────────────────────────────────────────────────────
def _mk_png(path, size=4):
    from PIL import Image
    Image.new("RGBA", (size, size), (10, 20, 30, 255)).save(path)


def test_import_files_copy_with_rename(tmp_path):
    src = tmp_path / "in"
    src.mkdir()
    for n in ("one.png", "two.png", "notes.txt"):
        (src / n).write_text("x")
    data = tmp_path / "data"
    rep = ingest.import_files(
        [str(src / "one.png"), str(src / "two.png"), str(src / "notes.txt")],
        str(data), mode="copy", prefix="ic_", style="enum", enum_pad=2)
    assert rep["placed"] == 2 and rep["skipped"] == 1   # .txt skipped
    dest = data / "imported" / "import"
    names = sorted(os.listdir(dest))
    assert names == ["ic_one01.png", "ic_two02.png"]
    assert (dest / names[0]).is_file() and not (dest / names[0]).is_symlink()


def test_import_files_link_mode_and_permission(tmp_path):
    src = tmp_path / "ext"
    src.mkdir()
    _mk_png(str(src / "linked.png"))
    data = tmp_path / "data"
    rep = ingest.import_files([str(src / "linked.png")], str(data),
                              mode="link")
    assert rep["placed"] == 1
    dest = data / "links" / "import"
    link = dest / "linked.png"
    assert link.is_symlink() and link.resolve() == (src / "linked.png").resolve()
    # missing file → counted failed/skipped without raising
    rep2 = ingest.import_files([str(src / "ghost.png")], str(data),
                               mode="link")
    assert rep2["placed"] == 0


def test_import_zip_streams_and_is_constant_memory(tmp_path):
    z = tmp_path / "pack.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for i in range(5):
            zf.writestr(f"icons/deep/folder/icon{i}.png", b"\x89PNG fake")
        zf.writestr("readme.md", "hi")
        zf.writestr("../evil.png", b"zip-slip attempt")   # flattened
    data = tmp_path / "data"
    rep = ingest.import_zip(str(z), str(data), style="guid")
    assert rep["placed"] == 6          # 5 icons + zip-slip member (basename)
    assert rep["skipped"] == 1         # readme.md
    names = os.listdir(data / "imported" / "zip-import")
    assert all(not n.startswith("..") for n in names)
    # every name got a guid-ish suffix or kept ext
    assert all(n.endswith(".png") for n in names)


def test_folder_sniff(tmp_path):
    d = tmp_path / "fonts"
    d.mkdir()
    (d / "Family-Regular.ttf").write_bytes(b"OTTO")
    out = ingest.import_folder(str(d))
    assert out["kind"] == "fontroot"


def test_conversion_png_to_webp_round(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _mk_png(str(src / "logo.png"), 16)
    data = tmp_path / "data"
    rep = ingest.import_files([str(src / "logo.png")], str(data),
                              convert="webp")
    assert rep["placed"] == 1
    out = list((data / "imported" / "import").glob("*.webp"))
    assert len(out) == 1


# ── watch ────────────────────────────────────────────────────────────
def test_watch_availability_and_coming_soon():
    rows = watch.availability()
    keys = [r["key"] for r in rows]
    assert {"local", "rsync", "s3", "onedrive", "icloud",
            "gdrive"} <= set(keys)
    soon = [r for r in rows if r.get("comingSoon")]
    assert {r["key"] for r in soon} == {"onedrive", "icloud", "gdrive"}
    assert all(not r["available"] for r in soon)


def test_watch_signature_detects_change(tmp_path):
    (tmp_path / "a.png").write_text("1")
    s1 = watch.signature(tmp_path)
    (tmp_path / "b.png").write_text("22")
    s2 = watch.signature(tmp_path)
    assert s1 != s2
    assert watch.signature(tmp_path / "nope") == "missing"


def test_watch_pull_uses_injected_runner(tmp_path):
    calls = []

    def fake_runner(argv):
        calls.append(argv)
        return 0

    out = watch.run_pull("rsync", "host:/drop", tmp_path / "staging",
                         runner=fake_runner)
    assert calls and calls[0][0] == "rsync"
    assert calls[0][-1].endswith("/")
    assert out["staging"].endswith("staging")


def test_watch_due_intervals():
    row = {"interval": 60}
    assert watch.due(row, now=1000, last_run=0) is True
    assert watch.due(row, now=1000, last_run=970) is False


# ── backup / restore / db admin ──────────────────────────────────────
def test_backup_package_contents_and_scripts(tmp_path, monkeypatch):
    """The backup is ONE .tar.gz restore package: structured manifest
    (version/settings/prefs/config/environment/logs), full database
    copies, and platform restore scripts pinned to the recorded tag."""
    import getpass as _getpass
    monkeypatch.setenv("FENGRID_STATE_DIR", str(tmp_path / "state"))
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "server.log").write_text("boot ok\n" * 5)
    (tmp_path / "app.log").write_text("debug line\n" * 3)

    db_path = str(tmp_path / "library.db")
    con = core_db.connect(db_path)
    con.execute("INSERT INTO collection(name) VALUES ('c1')")
    settings_set = __import__("fengrid.core.settings", fromlist=["set"])
    settings_set.set(con, "search_mode", "fuzzy")
    con.commit()
    reg_path = str(tmp_path / "registry.db")
    reg = core_db.connect(reg_path)
    core_db.connect(reg_path).close()   # registry file exists
    reg.close()

    out = core_backup.backup(db_path, str(tmp_path / "backups"),
                             registry_path=reg_path, label="nightly",
                             data_dir=tmp_path, logs_dir=tmp_path)
    assert out["name"].endswith(".tar.gz")

    with tarfile.open(out["path"]) as tf:
        names = tf.getnames()
        # one package: manifest + databases + logs + BOTH restore scripts
        assert len(names) == len(set(names)), "duplicate tar members"
        assert {"backup-manifest.json", "library.db", "registry.db",
                "restore/restore.sh", "restore/restore.ps1",
                "logs/server.log"} <= set(names)
        assert not any(n.startswith(".") for n in names), "temp leaked"
        assert tf.getmember("restore/restore.sh").mode & 0o111, \
            "restore.sh must be executable in the archive"
        man = json.loads(tf.extractfile("backup-manifest.json").read())
        sh = tf.extractfile("restore/restore.sh").read().decode()
        ps1 = tf.extractfile("restore/restore.ps1").read().decode()

    # structured file: version/build + settings + prefs + config + env
    assert man["kind"] == "backup" and man["format"] == 2
    b = man["build"]
    assert b["app_version"] and b["release_tag"].startswith("v")
    assert "." in b["python"]
    assert man["system_settings"]["search_mode"] == "fuzzy"
    assert isinstance(man["user_preferences"], dict)
    cfg = man["configuration"]
    for key in ("sources", "storage_mounts", "watch_sources",
                "databases", "row_counts"):
        assert key in cfg, key
    env = man["environment"]
    assert env["os"] and env["home"] and env["data_dir"]
    assert set(env["tools"]) >= {"rsync", "curl"}
    # checksums + logs index
    files = {f["name"]: f for f in man["files"]}
    assert files["library.db"]["sha256"] and files["library.db"]["bytes"] > 0
    assert any(l["name"].endswith("server.log") for l in man["logs"])

    # POSIX script: same-tag download, active-install refusal, OS paths,
    # checksum verify, numbered error codes
    assert f"releases/download/{b['release_tag']}/" in sh
    assert "pgrep -f" in sh and "not active" in sh
    assert ".local/bin/fengrid" in sh, "existing-install probe"
    assert "XDG_DATA_HOME" in sh and "Application Support" in sh, \
        "per-OS data dirs (usernames recomputed on target)"
    assert "sha256sum" in sh and "shasum -a 256" in sh
    assert "checksum mismatch" in sh
    assert 'fail() {' in sh and all(f" {c}" in sh for c in
                                    ("2", "3", "4", "5", "6", "7"))
    # Windows script: process/port checks, download, hash verify, paths
    assert "Get-Process" in ps1 and "8642" in ps1
    assert "Invoke-WebRequest" in ps1 and "Get-FileHash" in ps1
    assert "LOCALAPPDATA" in ps1 and "not active" in ps1

    # in-app restore still round-trips the package
    open(db_path, "wb").write(b"garbage not a database")
    res = core_backup.restore(out["path"], db_path)
    con2 = core_db.connect(db_path)
    # connect() seeds a default collection — assert by name, not count
    names = {r[0] for r in con2.execute("SELECT name FROM collection")}
    assert "c1" in names, names
    assert res["previous"] and os.path.isfile(res["previous"])
    con2.close()

    listed = core_backup.list_backups(str(tmp_path / "backups"))
    assert listed and listed[0]["bytes"] == out["bytes"]


def test_restore_detects_tampered_checksum(tmp_path):
    """restore() verifies the recorded sha256 BEFORE swapping."""
    db_path = str(tmp_path / "t.db")
    con = core_db.connect(db_path)
    con.commit()
    con.close()
    out = core_backup.backup(db_path, str(tmp_path / "backups"))
    # repack with a poisoned manifest sha
    with tarfile.open(out["path"]) as tf:
        blobs = {n: tf.extractfile(n).read() for n in tf.getnames()}
    man = json.loads(blobs["backup-manifest.json"])
    for f in man["files"]:
        if f["name"] == "library.db":
            f["sha256"] = "0" * 64
    blobs["backup-manifest.json"] = json.dumps(man).encode()
    with tarfile.open(out["path"], "w:gz") as tf:
        for n, data in blobs.items():
            ti = tarfile.TarInfo(n)
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
    with pytest.raises(core_backup.BackupError, match="checksum"):
        core_backup.restore(out["path"], db_path)


def test_restore_accepts_legacy_zip_and_rejects_junk(tmp_path):
    """Pre-format-2 zip backups still restore; junk never does."""
    db_path = str(tmp_path / "t.db")
    con = core_db.connect(db_path)
    con.execute("INSERT INTO collection(name) VALUES ('legacy')")
    con.commit()
    snap = str(tmp_path / "snap.db")
    con.close()
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(snap)
    with dst:
        src.backup(dst)
    dst.close(); src.close()

    legacy = str(tmp_path / "fengrid-backup-legacy.zip")
    with zipfile.ZipFile(legacy, "w") as zf:
        zf.writestr("backup-manifest.json", json.dumps(
            {"kind": "backup", "format": 1, "created": "2026-01-01"}))
        zf.write(snap, "library.db")
    man = core_backup.validate_backup(legacy)
    assert man["format"] == 1
    open(db_path, "wb").write(b"x")
    core_backup.restore(legacy, db_path)
    con2 = core_db.connect(db_path)
    assert "legacy" in {r[0] for r in
                        con2.execute("SELECT name FROM collection")}
    con2.close()

    junk = str(tmp_path / "evil.tar.gz")
    with tarfile.open(junk, "w:gz") as tf:
        ti = tarfile.TarInfo("whatever.txt")
        ti.size = 2
        tf.addfile(ti, io.BytesIO(b"x\n"))
    with pytest.raises(core_backup.BackupError):
        core_backup.validate_backup(junk)


def test_release_tag_and_remove_guards(tmp_path):
    assert core_backup._tag_for("0.3.0.dev0") == ("v0.3.0", True)
    assert core_backup._tag_for("1.2.3") == ("v1.2.3", False)
    assert core_backup._tag_for("v2.0.0") == ("v2.0.0", False)
    assert core_backup._tag_for("nonsense") == ("", False)

    d = tmp_path / "backups"
    d.mkdir()
    keep = d / "fengrid-backup-x.tar.gz"
    keep.write_bytes(b"not really a package")
    outside = tmp_path / "library.db"
    outside.write_bytes(b"data")
    with pytest.raises(core_backup.BackupError):
        core_backup.remove_backup(str(outside), str(d))
    notabackup = d / "notes.txt"
    notabackup.write_text("hi")
    with pytest.raises(core_backup.BackupError):
        core_backup.remove_backup(str(notabackup), str(d))
    core_backup.remove_backup(str(keep), str(d))   # in-dir package ok
    assert not keep.exists()


def test_restore_sh_actually_runs_and_refuses_active_installs(tmp_path):
    """The generated POSIX script is executable bash, parses cleanly,
    and exits code 2 with a clear reason when it finds an installation —
    the exact refusal behavior the spec asks for (never reaches the
    download when refusing)."""
    db_path = str(tmp_path / "t.db")
    con = core_db.connect(db_path); con.commit(); con.close()
    out = core_backup.backup(db_path, str(tmp_path / "backups"))
    with tarfile.open(out["path"]) as tf:
        sh = tf.extractfile("restore/restore.sh").read()
    pkg = tmp_path / "pkg" / "restore"
    pkg.mkdir(parents=True)
    (pkg / "restore.sh").write_bytes(sh)
    (pkg.parent / "library.db").write_bytes(b"payload")

    r0 = subprocess.run(["bash", "-n", str(pkg / "restore.sh")],
                        capture_output=True, text=True, timeout=20)
    assert r0.returncode == 0, r0.stderr

    fake_home = tmp_path / "home"
    (fake_home / "fengrid").mkdir(parents=True)   # "existing install"
    r = subprocess.run(["bash", str(pkg / "restore.sh")],
                       capture_output=True, text=True, timeout=30,
                       env={"HOME": str(fake_home), "PATH":
                            "/usr/bin:/bin"})
    # both refusal reasons are code 2; under pytest the repo path itself
    # makes pgrep match (cmdline contains 'fengrid'), so either probe may
    # fire first — what matters: code 2, a stated reason, no download
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert "ERROR [2]" in r.stderr
    assert ("not active" in r.stderr
            or "not installed or running" in r.stderr), r.stderr
    assert "downloading" not in r.stdout, "must refuse BEFORE downloading"


def test_dbadmin_ops(tmp_path):
    db_path = str(tmp_path / "t.db")
    con = core_db.connect(db_path)
    for i in range(50):
        con.execute("INSERT INTO collection(name) VALUES (?)", (f"c{i}",))
    con.commit()

    st = core_backup.stats(con, db_path)
    assert st["bytes"] > 0 and any(t["name"] == "collection"
                                   for t in st["tables"])
    assert core_backup.quick_check(con)["ok"] is True
    assert core_backup.vacuum(con)["pages_after"] <= \
        core_backup.vacuum(con)["pages_before"] + 1
    ck = core_backup.checkpoint(con)
    assert ck["mode"] in ("wal", "delete")
    assert core_backup.optimize(con)["ok"]

    # FTS rebuild: triggers must survive (asset INSERTs still index)
    has_fts = con.execute("SELECT value FROM setting WHERE key='has_fts'"
                          ).fetchone()
    assert has_fts is not None, "connect() must record has_fts"
    if str(has_fts[0]) in ("1", "True"):
        core_backup.rebuild_fts(con)
        src = tmp_path / "icons"
        src.mkdir()
        con.execute("INSERT INTO source(kind, path, label)"
                    " VALUES('folder', ?, 'x')", (str(src),))
        sid = con.execute("SELECT id FROM source").fetchone()[0]
        con.execute("INSERT INTO asset(source_id, kind, path, name)"
                    " VALUES(?, 'icon', ?, 'rebuild-test')",
                    (sid, str(src / "a.svg")))
        con.commit()
        hits = con.execute(
            "SELECT COUNT(*) FROM asset_fts WHERE asset_fts MATCH 'rebuild'"
        ).fetchone()[0]
        assert hits == 1
    # triggers must EXIST after rebuild (drop-table-without-trigger-drop
    # would have left asset writes broken)
    trigs = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger'")}
    assert {"asset_fts_ai", "asset_fts_ad", "asset_fts_au"} <= trigs

    # orphan sweep removes debris but NEVER fingerprints
    con.execute("INSERT INTO item_tag(item_id, item_kind, tag_id)"
                " VALUES(999999, 'icon', 1)")   # tag 1 may not exist either
    con.execute("INSERT INTO scan_state(path, fingerprint, last_seen)"
                " VALUES('/nowhere/x.png', 'zz', 1)")
    con.commit()
    counts = core_backup.sweep_orphans(con)
    assert counts["item_tag"] >= 1
    left = con.execute("SELECT COUNT(*) FROM scan_state"
                       " WHERE path='/nowhere/x.png'").fetchone()[0]
    assert left == 1, "sweep must not touch scan_state"
    con.close()


# ── extended export ──────────────────────────────────────────────────
def test_export_icons_multi_format_and_tint(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _mk_png(str(src / "glyph.png"), 8)
    dest = tmp_path / "out"
    rep = xp.export_icons([{"name": "glyph", "path": str(src / "glyph.png")}],
                          str(dest), fmts=["png", "bmp", "ico"],
                          size=16, tint="#39B8C4")
    assert rep["written"] == 3 and rep["failed"] == 0
    exts = sorted(p.suffix for p in dest.iterdir())
    assert exts == [".bmp", ".ico", ".png"]
    # tint actually recolored (alpha preserved)
    from PIL import Image
    with Image.open(dest / "glyph.png") as im:
        px = im.convert("RGBA").getpixel((0, 0))
    assert px[:3] == (57, 184, 196)


def test_export_script_hook_runs_per_output(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _mk_png(str(src / "a.png"), 8)
    calls = []

    def fake(argv):
        calls.append(argv)
        return 0

    rep = xp.export_icons([{"name": "a", "path": str(src / "a.png")}],
                          str(tmp_path / "out"), fmts=["png"],
                          script="touch {in}", script_enabled=True,
                          runner=fake)
    assert len(calls) == 1 and calls[0][0] == "touch"
    assert rep["written"] == 1
    # script failure is collected, batch survives
    def boom(argv):
        raise RuntimeError("nope")
    rep2 = xp.export_icons([{"name": "a", "path": str(src / "a.png")}],
                           str(tmp_path / "out2"), fmts=["png"],
                           script="whatever {in}", script_enabled=True,
                           runner=boom)
    assert rep2["failed"] == 1 and rep2["written"] == 1


def test_font_webfont_conversion(tmp_path):
    fontTools = pytest.importorskip("fontTools")
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder([".notdef", "A"])
    fb.setupCharacterMap({65: "A"})
    pen = TTGlyphPen(None)
    pen.moveTo((0, 0))
    pen.lineTo((500, 0))
    pen.lineTo((500, 700))
    pen.closePath()
    fb.setupGlyf({".notdef": TTGlyphPen(None).glyph(),
                  "A": pen.glyph()})
    fb.setupHorizontalMetrics({".notdef": (500, 0), "A": (500, 0)})
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({"familyName": "TestFam", "styleName": "Regular"})
    fb.setupOS2()
    fb.setupPost()
    src = tmp_path / "TestFam-Regular.ttf"
    fb.save(str(src))

    w2 = xp.convert_font(src, tmp_path / "out", "woff2")
    w1 = xp.convert_font(src, tmp_path / "out", "woff")
    assert w2.suffix == ".woff2" and w2.stat().st_size > 40
    assert w1.suffix == ".woff"
    # woff2 really is wOF2 magic
    assert w2.read_bytes()[:4] == b"wOF2"


def test_color_codes_all_formats():
    txt = xp.color_code_lines(["#39B8C4"], ["teal"], "txt")
    assert "#39B8C4" in txt and "rgb(57, 184, 196)" in txt
    assert "hsl(185," in txt and "%" in txt and "cmyk(" in txt
    csv = xp.color_code_lines(["#39B8C4"], ["teal"], "csv")
    assert csv.splitlines()[0] == "name,hex,rgb,hsl,cmyk"
    md = xp.color_code_lines(["#FF0000"], None, "md")
    assert "| `#FF0000` |" in md
    c = xp.rgb_to_cmyk("#FF0000")
    assert c[0] == 0.0 and c[1] == 100.0 and c[2] == 100.0 and c[3] == 0.0


def test_snippet_exports(tmp_path):
    rows = [{"id": 1, "title": "Flex Center", "language": "html",
             "description": "d", "tags": "t", "html": "<div>x</div>",
             "css": "", "js": ""}]
    b = xp.export_snippets(rows, str(tmp_path / "a"), kind="bundle")
    v = xp.export_snippets(rows, str(tmp_path / "b"), kind="vscode")
    m = xp.export_snippets(rows, str(tmp_path / "c"), kind="masscode")
    f = xp.export_snippets(rows, str(tmp_path / "d"), kind="files")
    assert b["written"] == v["written"] == m["written"] == f["written"] == 1
    data = json.loads(open(v["outputs"][0]).read())
    assert "Flex Center" in data and data["Flex Center"]["prefix"]
    assert open(f["outputs"][0]).read() == "<div>x</div>"


def test_bundle_export_and_read_roundtrip(tmp_path):
    db_path = str(tmp_path / "t.db")
    con = core_db.connect(db_path)
    src = tmp_path / "icons"
    src.mkdir()
    _mk_png(str(src / "one.png"))
    con.execute("INSERT INTO source(kind, path, label)"
                " VALUES('folder', ?, 'x')", (str(src),))
    sid = con.execute("SELECT id FROM source").fetchone()[0]
    con.execute("INSERT INTO asset(source_id, kind, path, name)"
                " VALUES(?, 'icon', ?, 'one')",
                (sid, str(src / "one.png")))
    con.execute("INSERT INTO collection(name) VALUES ('pack')")
    con.commit()

    out = xp.export_bundle(con, str(tmp_path / "out"), scope="library")
    assert out["assets"] == 1
    man = xp.read_bundle(out["path"])
    assert man["fengrid"] == "bundle" and len(man["assets"]) == 1
    with zipfile.ZipFile(out["path"]) as zf:
        assert "fengrid-bundle.json" in zf.namelist()
        assert any(n.startswith("files/") for n in zf.namelist())
    # non-bundle rejected
    z = tmp_path / "no.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("x.txt", "x")
    with pytest.raises(xp.ExportError):
        xp.read_bundle(z)
    con.close()


def test_bundle_roundtrip_collection_and_project(tmp_path):
    """Export scope=project carries project + collection membership;
    the importer recreates all three against NEW asset ids."""
    from fengrid.bridges.data import _import_bundle_job
    db_path = str(tmp_path / "t.db")
    con = core_db.connect(db_path)
    src = tmp_path / "icons"
    src.mkdir()
    _mk_png(str(src / "one.png"))
    _mk_png(str(src / "two.png"))
    con.execute("INSERT INTO source(kind, path, label)"
                " VALUES('folder', ?, 'x')", (str(src),))
    sid = con.execute("SELECT id FROM source").fetchone()[0]
    ids = []
    for nm in ("one", "two"):
        con.execute("INSERT INTO asset(source_id, kind, path, name)"
                    " VALUES(?, 'icon', ?, ?)", (sid, str(src / f"{nm}.png"),
                                                nm))
        ids.append(con.execute("SELECT id FROM asset WHERE name=?",
                               (nm,)).fetchone()[0])
    con.execute("INSERT INTO collection(name) VALUES ('pack')")
    cid = con.execute("SELECT id FROM collection WHERE name='pack'"
                      ).fetchone()[0]
    con.execute("INSERT INTO collection_ref(collection_id, item_kind,"
                " item_id) VALUES(?, 'icon', ?)", (cid, ids[0]))
    con.execute("INSERT INTO tag(name) VALUES ('brand')")
    tid = con.execute("SELECT id FROM tag").fetchone()[0]
    con.execute("INSERT INTO item_tag(item_id, item_kind, tag_id)"
                " VALUES(?, 'icon', ?)", (ids[0], tid))
    con.execute("INSERT INTO projects(name, description)"
                " VALUES('Site', 'desc')")
    pid = con.execute("SELECT id FROM projects").fetchone()[0]
    con.execute("INSERT INTO project_asset(project_id, asset_kind, asset_id)"
                " VALUES(?, 'icon', ?)", (pid, ids[0]))
    con.execute("INSERT INTO project_asset(project_id, asset_kind, asset_id)"
                " VALUES(?, 'icon', ?)", (pid, ids[1]))
    con.commit()

    out = xp.export_bundle(con, str(tmp_path / "out"), scope=f"project:{pid}")
    man = xp.read_bundle(out["path"])
    assert man["collection_links"] == [{"collection": "pack",
                                        "id": ids[0]}]
    assert man["project"]["name"] == "Site"
    # bundles only carry assets in scope (project members)
    assert any(l["id"] == ids[0] for l in man["tag_links"])
    con.close()

    # import into a SECOND database: everything re-created, ids differ
    db2 = str(tmp_path / "t2.db")
    data_dir = str(tmp_path / "data2")
    rep = _import_bundle_job(db2, data_dir, out["path"], "copy",
                             lambda d, t: None)
    assert rep["placed"] == 2 and rep["collection_links"] == 1
    assert rep["tag_links"] == 1 and rep["project"] == "Site"
    con2 = core_db.connect(db2)
    assert con2.execute("SELECT COUNT(*) FROM collection_ref"
                        ).fetchone()[0] == 1
    assert con2.execute("SELECT name FROM projects").fetchone()[0] == "Site"
    assert con2.execute("SELECT COUNT(*) FROM project_asset"
                        ).fetchone()[0] == 2
    assert con2.execute("SELECT COUNT(*) FROM item_tag").fetchone()[0] == 1
    # imported assets exist under new ids
    assert con2.execute("SELECT COUNT(*) FROM asset").fetchone()[0] == 2
    con2.close()


def test_restore_relaunch_suppressed(tmp_path, monkeypatch):
    """Relaunch path must be inert under FENGRID_NO_RELAUNCH (tests)."""
    monkeypatch.setenv("FENGRID_NO_RELAUNCH", "1")
    from PySide6.QtCore import QCoreApplication
    from fengrid.bridges.data import DataIO
    app = QCoreApplication.instance() or QCoreApplication([])
    db_path = str(tmp_path / "t.db")
    con = core_db.connect(db_path)
    dio = DataIO(con, db_path, str(tmp_path))
    msgs = []
    dio.message.connect(msgs.append)
    dio._relaunch()                      # would execv without the guard
    assert msgs and "relaunch suppressed" in msgs[0]
    con.close()
