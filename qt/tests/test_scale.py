"""Scalability work: scale indexes, synchronous=NORMAL, keyset grid
pagination + the debounced rail refresh (Library bridge), deterministic
search cap, adaptive watch interval, skip-when-clean auto-backup, and
bounded-lookahead parallel scan identification.

Core tests are Qt-free; the bridge tests follow test_command_bar.py's
fixture pattern.
"""
import os
import sqlite3
import sys

import pytest
from PIL import Image

from fengrid.core import backup as core_backup
from fengrid.core import db, indexer
from fengrid.core import search as core_search
from fengrid.core import watch as core_watch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

_APP = None


def _qapp():
    global _APP
    if _APP is None:
        from PySide6.QtGui import QGuiApplication
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        _APP = QGuiApplication.instance() or QGuiApplication([])
    return _APP


def make_icon(path, color=(10, 200, 180), size=(64, 64)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)


# ------------------------------------------------------------------ db
def test_scale_indexes_present_fresh(tmp_path):
    con = db.connect(tmp_path / "lib.db")
    try:
        names = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'")}
        for expected in ("idx_asset_grid", "idx_asset_kind_context",
                         "idx_asset_kind_ext", "idx_asset_kind_family",
                         "idx_asset_source", "idx_item_tag_tagid"):
            assert expected in names, expected
        # WAL + NORMAL: chunked scan commits must not fsync per chunk
        assert con.execute("PRAGMA synchronous").fetchone()[0] == 1
        assert con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        con.close()


def test_scale_indexes_recreated_on_legacy_connect(tmp_path):
    """An index dropped (or missing on an upgraded database) is restored
    by the next connect() — migrations run idempotently every open."""
    path = tmp_path / "lib.db"
    con = db.connect(path)
    con.execute("DROP INDEX idx_asset_grid")
    con.execute("DROP INDEX idx_item_tag_tagid")
    con.execute("DROP INDEX idx_asset_source")
    con.commit()
    con.close()
    con = db.connect(path)
    try:
        names = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'")}
        assert "idx_asset_grid" in names
        assert "idx_item_tag_tagid" in names
        assert "idx_asset_source" in names
    finally:
        con.close()


# ------------------------------------------------------------ sources summary
def test_sources_summary_counts_and_empty_sources(tmp_path):
    """#61: sources_summary feeds the first-run setup screen ON THE MAIN
    THREAD while the initial scans write. The old LEFT JOIN … GROUP BY
    visited the whole asset table per source (no source_id index); the
    single-pass aggregate + idx_asset_source keeps it off the freeze
    path. Also pins the LEFT JOIN semantics: a source with zero assets
    still lists with n=0."""
    con = db.connect(tmp_path / "lib.db")
    try:
        for label in ("alpha", "beta", "empty"):
            con.execute("INSERT INTO source(kind, path, label) VALUES"
                        " ('system', ?, ?)", (f"/{label}", label))
        for i in range(7):
            con.execute(
                "INSERT INTO asset(source_id, kind, path, name)"
                " VALUES (1, 'icon', ?, ?)", (f"/alpha/{i}.png", f"a{i}"))
        for i in range(3):
            con.execute(
                "INSERT INTO asset(source_id, kind, path, name)"
                " VALUES (2, 'icon', ?, ?)", (f"/beta/{i}.png", f"b{i}"))
        con.commit()
        rows = {r["label"]: r for r in indexer.sources_summary(con)}
        assert rows["alpha"]["n"] == 7
        assert rows["beta"]["n"] == 3
        assert rows["empty"]["n"] == 0        # LEFT JOIN semantics kept
        assert rows["empty"]["enabled"] in (0, 1)
        # kind, label ordering preserved
        order = [r["label"] for r in indexer.sources_summary(con)]
        assert order == sorted(order)
    finally:
        con.close()


# ------------------------------------------------------------ storage diagnostics
def test_filesystem_type_longest_mount_prefix(tmp_path):
    """#61: the crash-log launch line must name the filesystem — a read
    stall on a non-WAL (network) FS looks like a logic freeze in the
    dumps. Longest matching mount prefix wins (nested mounts)."""
    fake = tmp_path / "mounts"
    fake.write_text(
        "sysfs /sys sysfs rw 0 0\n"
        "/dev/nvme0n1p2 / ext4 rw,relatime 0 0\n"
        "nas:/volume1 /home nfs rw 0 0\n"
        "nas:/volume1/home /home/native nfs4 rw,relatime 0 0\n")
    assert db.filesystem_type("/home/native/dev/x.db",
                                   mounts_path=str(fake)) == "nfs4"
    assert db.filesystem_type("/usr/share/icons/x.svg",
                                   mounts_path=str(fake)) == "ext4"
    assert db.filesystem_type("/sys/class/x",
                                   mounts_path=str(fake)) == "sysfs"
    monkey_missing = tmp_path / "nope"
    assert db.filesystem_type("/x", mounts_path=str(monkey_missing)) == ""


def test_connect_warns_when_wal_unavailable(tmp_path, capsys):
    """#61: when journal_mode=WAL silently fails (network FS), the
    warning names the path, the fallback mode, and the filesystem —
    the user's terminal is where the freeze is first reported."""
    con = db.connect(tmp_path / "t.db")
    try:
        assert con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        # tmpfs/ext4 supports WAL here: no warning on a healthy FS
        assert "WAL unavailable" not in capsys.readouterr().err
    finally:
        con.close()


# -------------------------------------------------------------- search
def test_search_candidates_deterministic_order(tmp_path, monkeypatch):
    """The candidate cap must pick the NEWEST rows by id deterministically
    (plan-independent), never an arbitrary slice — #29: oldest-first made
    every freshly scanned asset invisible to fuzzy/regex above the cap."""
    monkeypatch.setattr(core_search, "MAX_CANDIDATES", 5)
    con = db.connect(tmp_path / "lib.db")
    try:
        con.execute("INSERT INTO source(kind, path, label) VALUES"
                    " ('system', '/x', 'x')")
        for i in range(10):
            con.execute(
                "INSERT INTO asset(source_id, kind, path, name)"
                " VALUES (1, 'icon', ?, ?)",
                (f"/x/{i:02d}.png", f"zzz{i:02d}"))
        con.commit()
        cands = core_search._candidates(con)
        # newest five: ids 6..10 are the searchable candidate set
        assert [c[0] for c in cands] == [10, 9, 8, 7, 6]
        # a term matching ONLY the oldest rows is still found via the
        # uncapped FTS path (handled by the library bridge, not here)
        from fengrid.bridges.library import Library, _ROLE_NAMES
        from PySide6.QtCore import QCoreApplication, Qt
        from PySide6.QtTest import QTest
        app = QCoreApplication.instance() or QCoreApplication([])
        lib = Library(con, str(tmp_path / "lib.db"), no_scan=True)
        try:
            lib.search = "zzz01"           # Property setter drives FTS
            QTest.qWait(50)                # debounced filter application
            name_role = Qt.ItemDataRole.UserRole + 1 + \
                _ROLE_NAMES.index("name")
            names = [lib._model.index(r).data(name_role)
                     for r in range(lib._model.rowCount())]
            assert any(n and "zzz01" in n for n in names), names
        finally:
            lib._on_about_to_quit()
    finally:
        con.close()


def test_search_content_ext_filter_in_sql(tmp_path):
    """Content search reads only text-like files — the ext filter runs in
    SQL so a 1M-row table isn't walked in Python just to discard rasters."""
    con = db.connect(tmp_path / "lib.db")
    try:
        con.execute("INSERT INTO source(kind, path, label) VALUES"
                    " ('system', '/x', 'x')")
        text = tmp_path / "readme.md"
        text.write_text("findme needle inside", encoding="utf-8")
        raster = tmp_path / "pic.png"
        make_icon(raster)
        for path, name in ((text, "readme"), (raster, "pic")):
            con.execute(
                "INSERT INTO asset(source_id, kind, path, name, ext)"
                " VALUES (1, 'icon', ?, ?, ?)",
                (str(path), name, path.suffix.lstrip(".")))
        con.commit()
        # text extension reads the file and finds the needle…
        hits = core_search.search_assets(con, "needle", mode="content")
        assert [h["name"] for h in hits] == ["readme"]
        # …and a term inside the raster never opens it (no text hit)
        assert core_search.search_assets(
            con, "absent-needle", mode="content") == []
    finally:
        con.close()


def test_search_fuzzy_quick_ratio_prefilter(tmp_path):
    """Hopeless candidates are rejected on quick_ratio without paying the
    quadratic SequenceMatcher.ratio() — results are still sane."""
    con = db.connect(tmp_path / "lib.db")
    try:
        con.execute("INSERT INTO source(kind, path, label) VALUES"
                    " ('system', '/x', 'x')")
        for name in ("alpha", "alpha2", "unrelated"):
            con.execute(
                "INSERT INTO asset(source_id, kind, path, name)"
                " VALUES (1, 'icon', ?, ?)", (f"/x/{name}.png", name))
        con.commit()
        hits = core_search.search_assets(con, "alpha", mode="fuzzy")
        names = [h["name"] for h in hits]
        assert names[:2] == ["alpha", "alpha2"]
        assert "unrelated" not in names
    finally:
        con.close()


# ---------------------------------------------------------------- watch
def test_scaled_interval_never_shortens_user_interval():
    assert core_watch.scaled_interval(60, 0) == 60
    assert core_watch.scaled_interval(60, 40_000) == 60      # small tree
    assert core_watch.scaled_interval(30, 40_000) == 30
    # 1M files ≈ 50 s per walk → a ~10% duty cycle needs ~500 s
    assert core_watch.scaled_interval(60, 1_000_000) == 500
    assert core_watch.scaled_interval(60, 10_000_000) == 600  # cap


def test_sig_count_parses_signature():
    assert core_watch.sig_count("1234:999:1700000000") == 1234
    assert core_watch.sig_count("") == 0
    assert core_watch.sig_count(None) == 0
    assert core_watch.sig_count("garbage") == 0


# --------------------------------------------------------------- backup
def test_auto_backup_skip_when_clean(tmp_path):
    dest = tmp_path / "backups"
    dbp = tmp_path / "lib.db"
    con = db.connect(dbp)
    con.close()
    assert core_backup.auto_backup_needed(dbp, dest)          # no state
    core_backup.record_auto_backup_state(dbp, dest)
    assert not core_backup.auto_backup_needed(dbp, dest)      # clean → skip
    # any write dirties the file → backup needed again
    con = sqlite3.connect(str(dbp))
    con.execute("CREATE TABLE t(x)")
    con.commit()
    con.close()
    assert core_backup.auto_backup_needed(dbp, dest)
    # a missing database is never "clean" of state it doesn't have
    assert core_backup.auto_backup_fingerprint(dbp, "")["library"]


def test_auto_backup_state_recorded_before_backup_is_stable(tmp_path):
    """The sidecar lives in the backups dir, NOT the database — recording
    it in the DB would dirty the file it describes."""
    dest = tmp_path / "backups"
    dbp = tmp_path / "lib.db"
    con = db.connect(dbp)
    con.close()
    core_backup.record_auto_backup_state(dbp, dest)
    # backup() itself writes snapshots into dest but not the databases —
    # a second 'needed?' check right after a real backup stays clean
    core_backup.backup(dbp, dest, label="auto")
    assert not core_backup.auto_backup_needed(dbp, dest)


# -------------------------------------------------- parallel identify
def _make_tree(root, n):
    for i in range(n):
        make_icon(root / "Adwaita" / "16x16" / "actions" / f"ic{i:03d}.png")
    return root


@pytest.mark.parametrize("parallel", ["1", "0"])
def test_scan_parallel_and_serial_agree(tmp_path, parallel, monkeypatch):
    """Both identification paths produce identical indexes (the env flag
    is the documented debug switch; correctness must not depend on it)."""
    monkeypatch.setenv("FENGRID_SCAN_PARALLEL", parallel)
    root = _make_tree(tmp_path / "icons", 60)
    con = db.connect(tmp_path / "lib.db")
    try:
        sources = indexer.ensure_sources(con, [root])
        rep = indexer.scan(con, sources)
        assert rep["new"] == 60 and rep["errors"] == 0
        # second scan: everything unchanged, nothing re-identified
        rep2 = indexer.scan(con, sources)
        assert rep2["unchanged"] == 60
        names = [r[0] for r in con.execute(
            "SELECT name FROM asset ORDER BY name")]
        assert len(names) == 60
    finally:
        con.close()


def test_scan_progress_counts_match_rows(tmp_path):
    root = _make_tree(tmp_path / "icons", 25)
    con = db.connect(tmp_path / "lib.db")
    try:
        sources = indexer.ensure_sources(con, [root])
        seen_paths = []
        rep = indexer.scan(con, sources,
                           progress=lambda n, p: seen_paths.append(p))
        assert rep["total"] == len(seen_paths)
        assert rep["total"] == con.execute(
            "SELECT COUNT(*) FROM asset").fetchone()[0]
    finally:
        con.close()


# ---------------------------------------------------- Library bridge
def test_grid_pagination_and_truncation_flag(tmp_path, monkeypatch):
    _qapp()
    import fengrid.bridges.library as lib_mod
    from fengrid.bridges.library import Library

    monkeypatch.setattr(lib_mod, "_MAX_FILTER_ROWS", 10)
    con = db.connect(tmp_path / "t.db")
    try:
        con.execute("INSERT INTO source(kind, path, label) VALUES"
                    " ('system', '/x', 'x')")
        for i in range(25):
            con.execute(
                "INSERT INTO asset(source_id, kind, path, name, theme)"
                " VALUES (1, 'icon', ?, ?, 't')",
                (f"/x/{i:04d}.png", f"n{i:04d}"))
        con.commit()
        lib = Library(con, str(tmp_path / "t.db"), no_scan=True)
        try:
            assert lib.gridTotal == 25
            assert lib.gridCapped is True
            assert lib.model.rowCount() == 10          # first keyset page
            lib.loadMore()
            assert lib.model.rowCount() == 20
            assert lib.gridCapped is True
            lib.loadMore()
            assert lib.model.rowCount() == 25
            assert lib.gridCapped is False             # exhausted
            lib.loadMore()                             # no-op now
            assert lib.model.rowCount() == 25
            # keyset order is stable and every row is distinct
            rows = lib.model.rows()
            keys = [(r["theme"], r["name"], r["id"]) for r in rows]
            assert keys == sorted(keys)
            assert len({r["id"] for r in rows}) == 25
        finally:
            lib._on_about_to_quit()
    finally:
        con.close()


def test_lists_refresh_coalesces_mutations(tmp_path):
    """N mutations schedule ONE debounced refresh — a 1000-item bulk
    star must not run the five rail aggregates 1000 times."""
    _qapp()
    from PySide6.QtTest import QTest

    from fengrid.bridges.library import Library

    con = db.connect(tmp_path / "t.db")
    try:
        lib = Library(con, str(tmp_path / "t.db"), no_scan=True)
        try:
            hits = []
            lib.listsChanged.connect(lambda: hits.append(1))
            # PERF-6: the constructor's own fill is a background worker —
            # let it land, then measure the COALESCING from here
            for _ in range(50):
                if not (lib._lists_thread is not None
                        and lib._lists_thread.is_alive()):
                    break
                QTest.qWait(20)
            QTest.qWait(50)                 # queued done→slot delivery
            base = len(hits)
            for _ in range(5):
                lib._mark_lists_dirty()
            assert lib._lists_dirty is True
            assert len(hits) == base        # nothing ran inline
            QTest.qWait(300)                # > the 150 ms debounce
            # background flush: wait for the (possibly trailing) worker
            for _ in range(50):
                if lib._lists_dirty is False and not (
                        lib._lists_thread is not None
                        and lib._lists_thread.is_alive()):
                    break
                QTest.qWait(20)
            QTest.qWait(50)                 # queued done→slot delivery
            assert lib._lists_dirty is False
            assert len(hits) - base == 1    # ONE flush for FIVE marks
        finally:
            lib._on_about_to_quit()
    finally:
        con.close()
