"""Canvas core: boards, LWW op merge, undo, library bindings, export.

Headless — core/canvas.py is Qt-free.
"""
import json

import pytest
from PIL import Image

from fengrid.core import canvas as cv
from fengrid.core import db
from fengrid.core import projects as core_projects
from fengrid.core import snippets as core_snippets


@pytest.fixture()
def lib(tmp_path):
    con = db.connect(tmp_path / "library.db")
    cv.migrate(con)
    yield con
    con.close()


@pytest.fixture()
def board(lib):
    pid = core_projects.create_project(lib, "Site")
    return cv.create_board(lib, pid, "Home")


def _icon(lib, tmp_path, name="star"):
    lib.execute("INSERT OR IGNORE INTO source(kind, path, label) VALUES"
                " ('folder', ?, 'x')", (str(tmp_path),))
    src = lib.execute("SELECT id FROM source WHERE path = ?",
                      (str(tmp_path),)).fetchone()[0]
    p = tmp_path / f"{name}.png"
    Image.new("RGB", (32, 32), (10, 20, 30)).save(p)
    aid = lib.execute(
        "INSERT INTO asset(source_id, kind, path, name, ext, width, height,"
        " guid, slug) VALUES (?, 'icon', ?, ?, 'png', 32, 32, ?, ?)",
        (src, str(p), name, db.new_guid(), name)).lastrowid
    lib.commit()
    return aid


def _palette(lib, hexes=("#112233", "#445566", "#778899")):
    pid = lib.execute("INSERT INTO palette(name, guid) VALUES ('Brand', ?)",
                      (db.new_guid(),)).lastrowid
    for k, h in enumerate(hexes):
        lib.execute("INSERT INTO palette_color(palette_id, position, hex)"
                    " VALUES (?,?,?)", (pid, k, h))
    lib.commit()
    return pid


# ──────────────────────────────────────────────────────────── boards
def test_board_crud_and_snapshot(lib, board):
    b = cv.get_board(lib, board)
    assert b["name"] == "Home" and b["guid"]
    cv.rename_board(lib, board, "Landing")
    assert cv.list_boards(lib, b["project_id"])[0]["name"] == "Landing"
    nid, _, _ = cv.create_node(lib, board, "rect", 10, 20)
    snap = cv.snapshot(lib, board)
    assert [n["id"] for n in snap["nodes"]] == [nid]
    assert snap["head"] >= 1


def test_board_requires_project(lib):
    with pytest.raises(cv.CanvasError):
        cv.create_board(lib, 999, "nope")


def test_board_deleted_with_project(lib, board):
    cv.create_node(lib, board, "rect")
    pid = cv.get_board(lib, board)["project_id"]
    core_projects.delete_project(lib, pid)
    assert cv.get_board(lib, board) is None
    assert lib.execute("SELECT COUNT(*) FROM canvas_node").fetchone()[0] == 0


# ─────────────────────────────────────────────────────── node editing
def test_create_defaults_and_props(lib, board):
    nid, logged, inv = cv.create_node(lib, board, "sticky", 5, 6,
                                      props={"text": "hi"})
    n = cv.get_node(lib, board, nid)
    assert n["type"] == "sticky" and n["props"]["text"] == "hi"
    assert n["props"]["fill"] == "#F5C25C"           # default kept
    assert (n["w"], n["h"]) == cv.DEFAULT_SIZE["sticky"]
    assert inv == [{"node": nid, "fields": {"deleted": 1}}]


def test_unknown_type_and_bad_field_rejected(lib, board):
    with pytest.raises(cv.CanvasError):
        cv.create_node(lib, board, "spaceship")
    nid, _, _ = cv.create_node(lib, board, "rect")
    with pytest.raises(cv.CanvasError):
        cv.apply_local(lib, board, [{"node": nid, "fields": {"evil;": 1}}])
    with pytest.raises(cv.CanvasError):
        cv.apply_local(lib, board, [{"node": nid, "fields": {"x": "nan"}}])


def test_undo_is_an_inverse_edit(lib, board):
    nid, _, _ = cv.create_node(lib, board, "rect", 0, 0)
    _, inv = cv.update_node(lib, board, nid, {"x": 100, "p.fill": "#000"})
    assert cv.get_node(lib, board, nid)["x"] == 100
    _, redo = cv.edit(lib, board, inv)
    n = cv.get_node(lib, board, nid)
    assert n["x"] == 0 and n["props"]["fill"] == "#D9DEE3"
    cv.edit(lib, board, redo)
    assert cv.get_node(lib, board, nid)["x"] == 100


def test_undo_removes_added_prop(lib, board):
    nid, _, _ = cv.create_node(lib, board, "rect")
    _, inv = cv.set_props(lib, board, nid, {"shadow": "0 2px 4px #000"})
    cv.edit(lib, board, inv)
    assert "shadow" not in cv.get_node(lib, board, nid)["props"]


def test_move_carries_children_and_skips_locked(lib, board):
    fid, _, _ = cv.create_node(lib, board, "frame", 0, 0, 400, 300)
    a, _, _ = cv.create_node(lib, board, "rect", 10, 10, parent=fid)
    b, _, _ = cv.create_node(lib, board, "rect", 50, 50, parent=fid)
    cv.update_node(lib, board, b, {"locked": 1})
    cv.move_nodes(lib, board, [fid], 100, 5)
    assert cv.get_node(lib, board, fid)["x"] == 100
    assert cv.get_node(lib, board, a)["x"] == 110
    assert cv.get_node(lib, board, b)["x"] == 50


def test_delete_cascades_children_and_connectors(lib, board):
    fid, _, _ = cv.create_node(lib, board, "frame")
    kid, _, _ = cv.create_node(lib, board, "text", parent=fid)
    other, _, _ = cv.create_node(lib, board, "rect")
    con_id, _, _ = cv.create_node(lib, board, "connector",
                                  props={"from": kid, "to": other})
    _, inv = cv.delete_nodes(lib, board, [fid])
    alive = {n["id"] for n in cv.nodes(lib, board)}
    assert alive == {other}
    cv.edit(lib, board, inv)
    alive = {n["id"] for n in cv.nodes(lib, board)}
    assert alive == {fid, kid, other, con_id}


def test_duplicate_remaps_parents(lib, board):
    fid, _, _ = cv.create_node(lib, board, "frame", 0, 0)
    kid, _, _ = cv.create_node(lib, board, "rect", 5, 5, parent=fid)
    new_ids, _, _ = cv.duplicate_nodes(lib, board, [fid])
    assert len(new_ids) == 1 and new_ids[0] != fid
    copies = [n for n in cv.nodes(lib, board) if n["parent"] == new_ids[0]]
    assert len(copies) == 1 and copies[0]["x"] == 5 + 24
    assert cv.get_node(lib, board, kid)["parent"] == fid


def test_restack_and_group(lib, board):
    a, _, _ = cv.create_node(lib, board, "rect", 0, 0, 10, 10)
    b, _, _ = cv.create_node(lib, board, "rect", 20, 0, 10, 10)
    c, _, _ = cv.create_node(lib, board, "rect", 40, 0, 10, 10)
    cv.restack(lib, board, [a], "front")
    assert [n["id"] for n in cv.nodes(lib, board)][-1] == a
    cv.restack(lib, board, [a], "backward")
    order = [n["id"] for n in cv.nodes(lib, board)]
    assert order.index(a) == 1
    gid, _, _ = cv.group_nodes(lib, board, [b, c])
    g = cv.get_node(lib, board, gid)
    assert (g["x"], g["w"]) == (20, 30)
    assert cv.get_node(lib, board, b)["parent"] == gid
    cv.ungroup(lib, board, gid)
    assert cv.get_node(lib, board, b)["parent"] == ""
    assert cv.get_node(lib, board, gid)["deleted"]


def test_align_and_distribute(lib, board):
    ids = [cv.create_node(lib, board, "rect", x, x, 10, 10)[0]
           for x in (0, 13, 50)]
    cv.align(lib, board, ids, "top")
    assert {cv.get_node(lib, board, i)["y"] for i in ids} == {0}
    cv.align(lib, board, ids, "hdist")
    xs = sorted(cv.get_node(lib, board, i)["x"] for i in ids)
    assert xs == [0, 25, 50]


# ─────────────────────────────────────────────────────── collaboration
def test_concurrent_edits_to_different_fields_both_survive(lib, board):
    nid, _, _ = cv.create_node(lib, board, "rect")
    clk = cv.get_board(lib, board)["clock"]
    cv.apply_remote(lib, board, [
        {"node": nid, "fields": {"x": 50}, "clock": clk + 1, "actor": "a-1"},
        {"node": nid, "fields": {"p.fill": "#F00"}, "clock": clk + 1,
         "actor": "a-2"}])
    n = cv.get_node(lib, board, nid)
    assert n["x"] == 50 and n["props"]["fill"] == "#F00"


def test_lww_same_field_is_order_independent(tmp_path):
    """Two replicas receiving the same ops in opposite orders converge."""
    states = []
    for order in (0, 1):
        con = db.connect(tmp_path / f"r{order}.db")
        cv.migrate(con)
        pid = core_projects.create_project(con, "P")
        bid = cv.create_board(con, pid, "B")
        ops = [
            {"node": "n1", "fields": {"type": "rect", "x": 1},
             "clock": 1, "actor": "a"},
            {"node": "n1", "fields": {"x": 7}, "clock": 5, "actor": "b"},
            {"node": "n1", "fields": {"x": 9}, "clock": 5, "actor": "a"},
            {"node": "n1", "fields": {"deleted": 1}, "clock": 3,
             "actor": "c"},
        ]
        if order:
            ops.reverse()
        cv.apply_remote(con, bid, ops)
        n = cv.get_node(con, bid, "n1")
        states.append((n["x"], n["deleted"], n["type"]))
        con.close()
    assert states[0] == states[1] == (7.0, True, "rect")


def test_edit_before_create_merges(lib, board):
    cv.apply_remote(lib, board, [{"node": "late", "fields": {"x": 3},
                                  "clock": 9, "actor": "z"}])
    assert cv.nodes(lib, board) == []             # stub stays invisible
    cv.apply_remote(lib, board, [{"node": "late", "fields": {
        "type": "ellipse", "x": 0}, "clock": 2, "actor": "z"}])
    n = cv.get_node(lib, board, "late")
    assert n["type"] == "ellipse" and n["x"] == 3 and not n["deleted"]


def test_local_clock_advances_past_remote(lib, board):
    cv.apply_remote(lib, board, [{"node": "r", "fields": {"type": "rect"},
                                  "clock": 500, "actor": "peer"}])
    _, logged, _ = cv.create_node(lib, board, "rect")
    assert logged[0]["clock"] > 500
    logged2, _ = cv.update_node(lib, board, "r", {"x": 4})
    assert cv.get_node(lib, board, "r")["x"] == 4
    assert logged2[0]["actor"] == cv.local_actor(lib)


def test_superseded_ops_not_logged_and_ops_since(lib, board):
    nid, _, _ = cv.create_node(lib, board, "rect")
    h = cv.head(lib, board)
    got = cv.apply_remote(lib, board, [{"node": nid, "fields": {"x": 1},
                                        "clock": 0, "actor": "old"}])
    assert got == [] and cv.head(lib, board) == h
    cv.update_node(lib, board, nid, {"x": 2})
    since = cv.ops_since(lib, board, h)
    assert len(since) == 1 and since[0]["fields"] == {"x": 2.0}
    assert cv.ops_since(lib, board, h, exclude_actor=cv.local_actor(lib)) == []


def test_remote_ops_need_clock_and_actor(lib, board):
    with pytest.raises(cv.CanvasError):
        cv.apply_remote(lib, board, [{"node": "x", "fields": {"x": 1}}])


def test_duplicate_board_and_snapshot_import(lib, board, tmp_path):
    fid, _, _ = cv.create_node(lib, board, "frame")
    cv.create_node(lib, board, "text", parent=fid)
    pid = cv.get_board(lib, board)["project_id"]
    nb = cv.duplicate_board(lib, board)
    kids = [n for n in cv.nodes(lib, nb) if n["parent"]]
    assert len(cv.nodes(lib, nb)) == 2 and kids
    assert kids[0]["parent"] in {n["id"] for n in cv.nodes(lib, nb)}
    snap = json.loads(json.dumps(cv.snapshot(lib, board), default=str))
    ib = cv.import_snapshot(lib, pid, snap)
    assert len(cv.nodes(lib, ib)) == 2


def test_presence_and_comments(lib, board):
    cv.touch_presence(lib, board, "a-peer", "Kim", "#E879A6", (10, 20), ["n"])
    assert [p["name"] for p in cv.presence(lib, board)] == ["Kim"]
    assert cv.presence(lib, board, exclude_actor="a-peer") == []
    cid = cv.add_comment(lib, board, "tighten spacing", x=4, y=5)
    assert cv.comments(lib, board)[0]["body"] == "tighten spacing"
    cv.resolve_comment(lib, cid)
    assert cv.comments(lib, board) == []


# ─────────────────────────────────────────────────── library bindings
def test_place_icon_binds_and_hydrates(lib, board, tmp_path):
    aid = _icon(lib, tmp_path)
    nid, _, _ = cv.place_asset(lib, board, "icon", aid, 10, 10)
    n = cv.get_node(lib, board, nid)
    assert n["type"] == "icon" and n["bind"]["id"] == aid
    info = cv.hydrate(lib, n["bind"])
    assert info["ok"] and info["path"].endswith("star.png")
    assert cv.usage(lib, "icon", aid)[0]["uses"] == 1


def test_binding_survives_renumbered_row_by_guid(lib, board, tmp_path):
    aid = _icon(lib, tmp_path)
    nid, _, _ = cv.place_asset(lib, board, "icon", aid)
    guid = lib.execute("SELECT guid FROM asset WHERE id = ?",
                       (aid,)).fetchone()[0]
    lib.execute("UPDATE asset SET id = 4242 WHERE id = ?", (aid,))
    lib.commit()
    info = cv.hydrate(lib, cv.get_node(lib, board, nid)["bind"])
    assert info["ok"] and info["id"] == 4242 and info["guid"] == guid


def test_broken_binding_renders_placeholder(lib, board, tmp_path):
    aid = _icon(lib, tmp_path)
    nid, _, _ = cv.place_asset(lib, board, "icon", aid)
    lib.execute("DELETE FROM asset WHERE id = ?", (aid,))
    lib.commit()
    assert cv.hydrate(lib, cv.get_node(lib, board, nid)["bind"])["ok"] is False
    assert "fg-missing" in cv.render_html(lib, board)


def test_place_ref_by_slug(lib, board, tmp_path):
    aid = _icon(lib, tmp_path, "logo")
    nid, _, _ = cv.place_ref(lib, board, "[[ logo ]]")
    assert cv.get_node(lib, board, nid)["bind"]["id"] == aid
    with pytest.raises(cv.CanvasError):
        cv.place_ref(lib, board, "nothing-here")


def test_place_collection_lays_out_members(lib, board, tmp_path):
    ids = [_icon(lib, tmp_path, f"i{k}") for k in range(5)]
    cid = db.create_sub_collection(lib, "Nav icons", kind="icon")
    for i in ids:
        assert db.add_collection_ref(lib, cid, "icon", i)
    fid, _, _ = cv.place_collection(lib, board, cid, 0, 0, cols=3)
    frame = cv.get_node(lib, board, fid)
    kids = [n for n in cv.nodes(lib, board) if n["parent"] == fid]
    assert frame["type"] == "collection" and frame["bind"]["id"] == cid
    assert len(kids) == 5
    assert len({k["y"] for k in kids}) == 2           # two rows of 3+2
    for k in kids:                                    # inside the frame
        assert frame["x"] <= k["x"] and k["x"] + k["w"] <= frame["x"] + frame["w"]
        assert frame["y"] <= k["y"] and k["y"] + k["h"] <= frame["y"] + frame["h"]


def test_palette_node_and_explode(lib, board):
    pal = _palette(lib)
    nid, _, _ = cv.place_asset(lib, board, "palette", pal)
    assert cv.get_node(lib, board, nid)["w"] == 3 * 48
    assert cv.hydrate(lib, cv.get_node(lib, board, nid)["bind"])["hexes"][0] \
        == "#112233"
    ids, _, _ = cv.explode_palette(lib, board, pal)
    assert [cv.get_node(lib, board, i)["props"]["fill"] for i in ids] == \
        ["#112233", "#445566", "#778899"]


def test_sync_links_mirrors_usage(lib, board, tmp_path):
    aid = _icon(lib, tmp_path)
    nid, _, _ = cv.place_asset(lib, board, "icon", aid)
    pid = cv.get_board(lib, board)["project_id"]
    assert cv.sync_links(lib, board) == 1
    roles = lib.execute("SELECT to_kind, to_id, role FROM asset_link"
                        " WHERE from_kind='project' AND from_id=?",
                        (pid,)).fetchall()
    assert [tuple(r) for r in roles] == [("icon", aid, "canvas")]
    cv.delete_nodes(lib, board, [nid])
    assert cv.sync_links(lib, board) == 0
    assert lib.execute("SELECT COUNT(*) FROM asset_link").fetchone()[0] == 0


def test_code_cell_promotes_to_snippet(lib, board):
    nid, _, _ = cv.create_node(lib, board, "code", name="CTA")
    sid, _, _ = cv.code_to_snippet(lib, board, nid)
    n = cv.get_node(lib, board, nid)
    assert n["type"] == "snippet" and n["bind"]["id"] == sid
    assert core_snippets.get_snippet(lib, sid)["title"] == "CTA"
    info = cv.hydrate(lib, n["bind"])
    assert "btn" in info["html"]


# ──────────────────────────────────────────────────────────── export
def test_render_html_escapes_everything(lib, board):
    cv.create_node(lib, board, "text", props={
        "text": "<script>alert(1)</script>",
        "color": "red;background:url(javascript:x)",
        "fontFamily": "x';}</style><script>"})
    out = cv.render_html(lib, board)
    assert "<script>alert" not in out
    assert "javascript:" not in out
    assert "</style><script>" not in out


def test_code_cell_css_is_scoped(lib, board):
    nid, _, _ = cv.create_node(lib, board, "code", props={
        "html": "<p>x</p>", "css": "p{color:red} a,b{x:1} @media(x){p{}}"})
    out = cv.render_html(lib, board)
    assert f'[data-id="{nid}"] p{{color:red}}' in out
    assert f'[data-id="{nid}"] a,[data-id="{nid}"] b{{' in out


def test_export_bundle_copies_assets(lib, board, tmp_path):
    aid = _icon(lib, tmp_path)
    cv.place_asset(lib, board, "icon", aid)
    cv.create_node(lib, board, "ellipse", 100, 100)
    out = cv.export_bundle(lib, board, str(tmp_path / "out"))
    assert out["assets"] == 1 and out["nodes"] == 2
    html = (tmp_path / "out" / "index.html").read_text()
    assert 'src="assets/star.png"' in html
    assert (tmp_path / "out" / "assets" / "star.png").exists()
    svg = (tmp_path / "out" / "board.svg").read_text()
    assert svg.startswith("<svg") and "<ellipse" in svg


# ───────────────────────────────── Studio regression found in review
def test_studio_snippet_block_renders(lib):
    """core.studio._snippet_body used to SELECT a nonexistent `body`
    column; the bare except turned that into 'missing' for every
    snippet block on every page."""
    from fengrid.core import studio
    sid = core_snippets.create_snippet(lib, "Hero", "", "web",
                                       "<h1>hi</h1>", "h1{color:red}", "", "")
    out = studio._render_block(lib, {"type": "snippet", "props": {
        "ref": str(sid)}, "children": []}, 0)
    assert "<h1>hi</h1>" in out and "h1{color:red}" in out
    assert "fg-block-missing" not in out


def test_render_html_live_preview_links(lib, board, tmp_path):
    from fengrid.core import assetrefs
    aid = _icon(lib, tmp_path, 'we"ird')
    cv.place_asset(lib, board, "icon", aid)
    out = cv.render_html(lib, board,
                         assets=lambda p: assetrefs.url_for({"path": p}))
    assert "fengrid-asset://" in out
    assert 'we"ird' not in out and "we&quot;ird" in out


def test_project_delete_drops_its_links(lib, board, tmp_path):
    aid = _icon(lib, tmp_path)
    cv.place_asset(lib, board, "icon", aid)
    cv.sync_links(lib, board)
    pid = cv.get_board(lib, board)["project_id"]
    core_projects.delete_project(lib, pid)
    assert lib.execute("SELECT COUNT(*) FROM asset_link").fetchone()[0] == 0


def test_studio_image_ref_escaped(lib, tmp_path):
    """core.studio._ref put url_for() into src= unescaped (SEC-2 class)."""
    from fengrid.core import studio
    _icon(lib, tmp_path, 'q"uote')
    out = studio._render_block(lib, {"type": "image", "props": {
        "ref": 'q"uote'}, "children": []}, 0)
    assert 'q"uote' not in out and "q&quot;uote" in out
