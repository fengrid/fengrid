"""Studio core (pages/blocks/templates) + Docker integration core.

Studio tests run on an in-memory DB; Docker tests skip cleanly when
the daemon is unreachable and only exercise read-only + validation
paths (no image pulls) — build/run are exercised manually via the UI.
"""

import json

import pytest

from fengrid.core import studio as st
from fengrid.core import db as core_db
from fengrid.core import docker as dk
from fengrid.core import projects as core_projects


@pytest.fixture()
def con():
    import sqlite3
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(core_db.SCHEMA)
    core_db._migrate(c)
    st.migrate(c)
    pid = core_projects.create_project(c, "Studio Demo")
    return c, pid


@pytest.fixture()
def page(con):
    c, pid = con
    pgid = st.create_page(c, pid, "Home")
    return c, pid, st.get_page(c, pgid)


# ───────────────────────────────────────────────────── pages CRUD
def test_migrate_creates_table(con):
    c, _ = con
    rows = c.execute("SELECT name FROM sqlite_master WHERE name ="
                     " 'studio_page'").fetchall()
    assert rows


def test_create_page_defaults_to_hero_section(page):
    c, _, pg = page
    assert pg["name"] == "Home"
    assert pg["payload"][0]["type"] == "section"
    assert pg["payload"][0]["id"]


def test_page_names_required(con):
    c, pid = con
    with pytest.raises(st.StudioError):
        st.create_page(c, pid, "  ")
    with pytest.raises(st.StudioError):
        st.create_page(c, pid + 999, "Ghost")


def test_list_pages_sorted(con):
    c, pid = con
    st.create_page(c, pid, "Home")
    st.create_page(c, pid, "Second")
    st.create_page(c, pid, "Third")
    names = [p["name"] for p in st.list_pages(c, pid)]
    assert names == ["Home", "Second", "Third"]


def test_save_page_rejects_bad_trees(page):
    c, _, pg = page
    with pytest.raises(st.StudioError):
        st.save_page(c, pg["id"], [{"type": "nope"}])
    with pytest.raises(st.StudioError):
        st.save_page(c, pg["id"], {"not": "a list"})
    deep = blk = {"id": "x", "type": "section", "props": {}, "children": []}
    for _ in range(14):
        blk["children"] = [dict(blk)]
        blk = blk["children"][0]
    with pytest.raises(st.StudioError):
        st.save_page(c, pg["id"], [deep])


# ──────────────────────────────────────────────── block operations
def test_add_move_remove_block(page):
    c, _, pg = page
    root_id = pg["payload"][0]["id"]
    b = st.add_block(pg, "heading", {"text": "Welcome", "level": 1},
                     parent_id=root_id)
    st.add_block(pg, "text", {"text": "hello"}, parent_id=root_id)
    assert len(pg["payload"][0]["children"]) == 2
    st.move_block(pg, b["id"], 1)               # heading now second
    assert pg["payload"][0]["children"][1]["type"] == "heading"
    st.remove_block(pg, b["id"])
    assert all(bl["type"] != "heading"
               for bl in pg["payload"][0]["children"])
    with pytest.raises(st.StudioError):
        st.move_block(pg, "ghost", 1)


def test_nested_add_requires_container(page):
    c, _, pg = page
    t = st.add_block(pg, "text", {"text": "x"})
    with pytest.raises(st.StudioError):
        st.add_block(pg, "text", {}, parent_id=t["id"])


def test_duplicate_block_gets_fresh_ids(page):
    c, _, pg = page
    root = pg["payload"][0]["id"]
    b = st.add_block(pg, "section", {"class": "card"}, parent_id=root)
    st.add_block(pg, "text", {"text": "child"}, parent_id=b["id"])
    dup = st.duplicate_block(pg, b["id"])
    assert dup["id"] != b["id"]
    assert dup["props"]["class"] == "card"
    assert dup["children"][0]["id"] != b["children"][0]["id"]


def test_set_block_props(page):
    c, _, pg = page
    b = st.add_block(pg, "button", {"text": "Go"})
    st.set_block_props(pg, b["id"], {"text": "Click", "href": "/x"})
    assert st._walk(pg["payload"], b["id"])[2]["props"]["href"] == "/x"


# ─────────────────────────────────────────────────────── rendering
def test_render_blocks_html(page):
    c, _, pg = page
    root = pg["payload"][0]["id"]
    st.add_block(pg, "heading", {"text": "Hi <b>you</b>"}, root)
    st.add_block(pg, "text", {"text": "body"}, root)
    html = st.render_blocks(c, pg["payload"])
    assert "<h2" in html and "Hi &lt;b&gt;you&lt;/b&gt;" in html
    assert "<p" in html and "body" in html


def test_render_escapes_and_missing_refs(con):
    c, pid = con
    blocks = [st._block("image", {"ref": "missing-slug"})]
    html = st.render_blocks(c, blocks)
    assert "fg-block-missing" not in html   # ref present → <img> attempt
    assert 'src="missing-slug"' in html
    blocks2 = [st._block("image", {})]
    assert "no reference set" in st.render_blocks(c, blocks2)


def test_render_palette_block(con):
    c, pid = con
    cur = c.execute("INSERT INTO palette(name, tags, created)"
                    " VALUES ('Brand', '', 0)")
    pid_palette = cur.lastrowid
    for i, h in enumerate(("#112233", "#39B8C4", "#F5C25C")):
        c.execute("INSERT INTO palette_color(palette_id, position, hex)"
                  " VALUES (?,?,?)", (pid_palette, i, h))
    c.commit()
    html = st.render_blocks(c, [st._block("palette", {"ref": str(pid_palette)})])
    assert "#39B8C4" in html


# ──────────────────────────────────────────────── templates/tenants
def test_apply_vars_substitution():
    out = st.apply_vars({"text": "Hello {{name}}", "n": 3,
                         "list": ["{{name}}", "plain"]},
                        {"name": "Acme"})
    assert out["text"] == "Hello Acme"
    assert out["list"] == ["Acme", "plain"]
    assert out["n"] == 3
    assert st.apply_vars("{{unknown}}", {}) == "{{unknown}}"


def test_set_template_var_validation():
    s = st.set_template_var({}, "tenant_name", "Acme")
    assert s["template_vars"]["tenant_name"] == "Acme"
    with pytest.raises(st.StudioError):
        st.set_template_var({}, "bad name!", "x")


def test_instantiate_template_copies_and_applies(con):
    c, pid = con
    pgid = st.create_page(c, pid, "Home")
    pg = st.get_page(c, pgid)
    root = pg["payload"][0]["id"]
    st.add_block(pg, "heading", {"text": "Welcome to {{tenant}}"}, root)
    st.save_page(c, pgid, pg["payload"])
    core_projects.update_project(c, pid, settings={
        "template_vars": {"tenant": "Default Co"}})

    new_id = st.instantiate_template(c, pid, "Acme build",
                                     overrides={"tenant": "Acme"})
    row = c.execute("SELECT settings FROM projects WHERE id = ?",
                    (new_id,)).fetchone()
    s = json.loads(row["settings"])
    assert s["template_of"] == pid
    assert s["template_vars"]["tenant"] == "Acme"
    inst_pages = st.list_pages(c, new_id)
    got = st.get_page(c, inst_pages[0]["id"])
    assert got["payload"][0]["children"][0]["props"]["text"] \
        == "Welcome to Acme"
    assert st.instances_of(c, pid)[0]["id"] == new_id


# ─────────────────────────────────────────────── characterization
def test_describe_usage_counts(con):
    c, pid = con
    pgid = st.create_page(c, pid, "Home")
    pg = st.get_page(c, pgid)
    root = pg["payload"][0]["id"]
    st.add_block(pg, "icon", {"ref": "brand-mark"}, root)
    st.add_block(pg, "text", {"text": "x"}, root)
    st.save_page(c, pgid, pg["payload"])
    d = st.describe_usage(c, pid)
    assert d["pages"] == 1
    assert d["block_types"]["icon"] == 1
    assert "brand-mark" in d["refs"]
    assert "brand-mark" in d["unresolved_refs"]   # nothing in the library


# ──────────────────────────────────────────────────────── docker
def test_docker_validation_paths():
    with pytest.raises(dk.DockerError):
        dk._check_port("zzz:80")
    with pytest.raises(dk.DockerError):
        dk._check_volume(":target")
    with pytest.raises(dk.DockerError):
        dk._safe_path("-rf")
    with pytest.raises(dk.DockerError):
        dk._safe_path("a;rm")
    with pytest.raises(dk.DockerError):
        dk.run("img", "n", env={"bad name": "v"})


def test_docker_probe_and_lists():
    if not dk.docker_available():
        pytest.skip("docker daemon not reachable")
    assert isinstance(dk.version(), str)
    assert isinstance(dk.ps(all_=True), list)
    assert isinstance(dk.images(), list)
    # state of a container that surely doesn't exist
    assert dk.state("fengrid-definitely-not-here") == {"exists": False}
