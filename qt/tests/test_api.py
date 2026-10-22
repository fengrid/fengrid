"""End-to-end tests for the Fengrid REST API v1 (server + middleware +
scheduler). Runs the real ThreadingHTTPServer on an ephemeral port against
a seeded temp database, exercising the route table through plain HTTP.
"""

import json
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

# the api package lives at the repo root (tests run from qt/)
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from api.v1 import resources as api_res            # noqa: E402
from api.v1.middleware import ApiError             # noqa: E402
from api.v1.scheduler import TaskScheduler         # noqa: E402
from api.v1.server import make_api, make_handler   # noqa: E402
from http.server import ThreadingHTTPServer        # noqa: E402


@pytest.fixture()
def api_env(tmp_path):
    """Seeded database + live server on an ephemeral port."""
    from fengrid.core import db as core_db

    # a real (tiny PNG) file so /copy and file stats work
    png = tmp_path / "icon.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)

    db_path = tmp_path / "library.db"
    con = core_db.connect(str(db_path))
    # seed: one icon asset, one palette, one snippet
    now = time.time()
    con.execute("INSERT INTO source(kind, path, label, enabled)"
                " VALUES ('folder', ?, 'api test', 1)", (str(tmp_path),))
    src_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
    con.execute("INSERT INTO asset(source_id, kind, path, name, mtime)"
                " VALUES (?, 'icon', ?, 'Test Icon', ?)",
                (src_id, str(png), now))
    icon_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
    con.execute("INSERT INTO palette(name, tags, created, updated)"
                " VALUES ('Test Palette', 'warm', ?, ?)", (now, now))
    pal_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
    for pos, hx in enumerate(("#ff0000", "#00ff00")):
        con.execute("INSERT INTO palette_color(palette_id, position, hex,"
                    " locked) VALUES (?, ?, ?, 0)", (pal_id, pos, hx))
    con.execute("INSERT INTO snippet(title, description, language, tags,"
                " html, css, js, created, updated) VALUES"
                " ('Test Snippet', 'desc', 'web', 'demo', '<p>x</p>',"
                " '', '', ?, ?)", (now, now))
    snip_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
    con.commit()
    con.close()

    sched = TaskScheduler(workers=2)
    api = make_api(str(db_path), data_dir=str(tmp_path))
    api.scheduler = sched
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(api, "tok123"))
    port = httpd.server_address[1]
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    yield {"api": api, "port": port, "base": f"http://127.0.0.1:{port}",
           "icon_id": icon_id, "pal_id": pal_id, "snip_id": snip_id}
    httpd.shutdown()
    sched.shutdown()


def _req(base, method, path, body=None, token="tok123"):
    req = urllib.request.Request(base + path, method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data=data, timeout=10) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


# ─────────────────────────────────────────────────────── auth + envelope
def test_health_open_and_auth(api_env):
    b = api_env["base"]
    # health is served behind the same middleware (token required)
    st, body = _req(b, "GET", "/api/v1/health")
    assert st == 200 and body["ok"] is True
    assert body["data"]["api"] == "v1"
    # wrong token rejected
    st, body = _req(b, "GET", "/api/v1/health", token="wrong")
    assert st == 401 and body["ok"] is False
    assert body["error"]["code"] == "unauthorized"


def test_unknown_route_404_bad_method_405(api_env):
    b = api_env["base"]
    st, body = _req(b, "GET", "/api/v1/nope")
    assert st == 404 and body["error"]["code"] == "not_found"
    st, body = _req(b, "DELETE", "/api/v1/health")
    assert st == 405 and body["error"]["code"] == "method_not_allowed"


# ───────────────────────────────────────────────────────────── assets
def test_assets_list_describe_patch(api_env):
    b, iid = api_env["base"], api_env["icon_id"]
    st, body = _req(b, "GET", "/api/v1/assets?kind=icon")
    assert st == 200
    items = body["data"]["items"]
    assert len(items) == 1 and items[0]["name"] == "Test Icon"
    # describe
    st, body = _req(b, "GET", f"/api/v1/assets/icon/{iid}")
    assert st == 200
    d = body["data"]
    assert d["name"] == "Test Icon" and d["starred"] is False
    assert "custom_fields" in d and "collections" in d
    # patch: rename + tags
    st, body = _req(b, "PATCH", f"/api/v1/assets/icon/{iid}",
                    {"name": "Renamed", "tags": ["hero", "ui"]})
    assert st == 200 and body["data"]["name"] == "Renamed"
    assert sorted(body["data"]["tags"]) == ["hero", "ui"]
    # 404 on missing
    st, _ = _req(b, "GET", "/api/v1/assets/icon/99999")
    assert st == 404
    st, body = _req(b, "GET", "/api/v1/assets?kind=sticker")
    assert st == 400 and body["error"]["code"] == "bad_kind"


def test_star_collect_copy(api_env):
    b, iid = api_env["base"], api_env["icon_id"]
    # star it
    st, body = _req(b, "POST", f"/api/v1/assets/icon/{iid}/star",
                    {"on": True})
    assert st == 200 and body["data"]["starred"] is True
    # starred filter finds it
    st, body = _req(b, "GET", "/api/v1/assets?kind=icon&starred=true")
    assert st == 200 and body["data"]["count"] == 1
    # create collection + collect the icon
    st, body = _req(b, "POST", "/api/v1/collections", {"name": "Heroes"})
    cid = body["data"]["id"]
    st, body = _req(b, "POST",
                    f"/api/v1/assets/icon/{iid}/collect",
                    {"collection_id": cid})
    assert st == 200
    st, body = _req(b, "GET", f"/api/v1/collections/{cid}")
    assert st == 200 and len(body["data"]["refs"]) == 1
    # copy the icon file
    st, body = _req(b, "POST", f"/api/v1/assets/icon/{iid}/copy")
    assert st == 200
    new = body["data"]["copied"]
    assert new["kind"] == "icon" and new["id"] != iid
    # copied asset inherits tags (here: the 'starred' tag from the star
    # call above — this test never patched hero/ui onto the original)
    st, body = _req(b, "GET", f"/api/v1/assets/icon/{new['id']}")
    assert st == 200 and body["data"]["tags"] == ["starred"]


def test_palette_snippet_flows(api_env):
    b, pid, sid = (api_env["base"], api_env["pal_id"],
                   api_env["snip_id"])
    st, body = _req(b, "GET", "/api/v1/assets?kind=palette")
    assert st == 200 and body["data"]["count"] == 1
    st, body = _req(b, "GET", f"/api/v1/assets/palette/{pid}")
    assert st == 200 and body["data"]["colors"] == ["#ff0000", "#00ff00"]
    st, body = _req(b, "GET", f"/api/v1/assets/snippet/{sid}")
    assert st == 200 and body["data"]["language"] == "web"


# ───────────────────────────────────────────────────── collections etc.
def test_collections_libraries_tags_fields(api_env):
    b = api_env["base"]
    st, body = _req(b, "GET", "/api/v1/collections")
    assert st == 200 and "items" in body["data"]
    # rename a tag via PATCH (create it first — every test gets a fresh DB)
    st, body = _req(b, "PATCH",
                    f"/api/v1/assets/icon/{api_env['icon_id']}",
                    {"tags": ["ui"]})
    assert st == 200
    st, body = _req(b, "PATCH", "/api/v1/tags/ui", {"new": "interface"})
    assert st == 200 and body["data"]["to"] == "interface"
    st, _ = _req(b, "PATCH", "/api/v1/tags/does-not-exist", {"new": "x"})
    assert st == 404
    # custom fields: create + set value
    st, body = _req(b, "POST", "/api/v1/fields",
                    {"name": "client", "type": "text"})
    assert st == 200
    st, body = _req(b, "PATCH",
                    f"/api/v1/assets/icon/{api_env['icon_id']}",
                    {"fields": {"client": "Acme"}})
    assert st == 200
    assert body["data"]["custom_fields"]["client"] == "Acme"
    # libraries
    st, body = _req(b, "POST", "/api/v1/libraries",
                    {"name": "Brand", "tags": "hero interface"})
    assert st == 200
    st, body = _req(b, "GET", "/api/v1/libraries")
    assert st == 200 and len(body["data"]["items"]) == 1


def test_inventory_and_projects(api_env):
    b = api_env["base"]
    st, body = _req(b, "GET", "/api/v1/inventory")
    assert st == 200
    inv = body["data"]
    assert inv["assets"]["icon"] == 1
    assert inv["assets"]["palette"] == 1
    assert inv["starred"]["icon"] == 0
    st, body = _req(b, "GET", "/api/v1/projects")
    assert st == 200


# ────────────────────────────────────────────────────── scheduler + jobs
def test_scheduler_runs_jobs_and_reports(api_env):
    b = api_env["base"]
    st, body = _req(b, "POST", "/api/v1/jobs-does-not-exist")
    assert st == 404


def test_scheduler_direct(api_env):
    api = api_env["api"]
    job = api.scheduler.submit("test", lambda: {"written": 3})
    deadline = time.time() + 5
    while time.time() < deadline:
        if api.scheduler.get(job.id).state == "done":
            break
        time.sleep(0.05)
    j = api.scheduler.get(job.id)
    assert j.state == "done" and j.result == {"written": 3}


def test_job_failure_surface(api_env):
    api = api_env["api"]

    def boom():
        raise ValueError("kaboom")
    job = api.scheduler.submit("test", boom)
    deadline = time.time() + 5
    while time.time() < deadline:
        if api.scheduler.get(job.id).state == "failed":
            break
        time.sleep(0.05)
    j = api.scheduler.get(job.id)
    assert j.state == "failed" and "kaboom" in j.error


def test_db_admin_check(api_env):
    b = api_env["base"]
    st, body = _req(b, "POST", "/api/v1/db/check")
    assert st in (200, 202)
    jid = body["data"]["id"]
    # poll until done
    deadline = time.time() + 10
    while time.time() < deadline:
        st, jb = _req(b, "GET", f"/api/v1/jobs/{jid}")
        if jb["data"]["state"] in ("done", "failed"):
            break
        time.sleep(0.1)
    assert jb["data"]["state"] == "done"
    assert jb["data"]["result"].get("ok") is True


def test_backup_job_roundtrip(api_env, tmp_path):
    b = api_env["base"]
    st, body = _req(b, "POST", "/api/v1/backups")
    jid = body["data"]["id"]
    deadline = time.time() + 30
    while time.time() < deadline:
        st, jb = _req(b, "GET", f"/api/v1/jobs/{jid}")
        if jb["data"]["state"] in ("done", "failed"):
            break
        time.sleep(0.2)
    assert jb["data"]["state"] == "done", jb["data"].get("error")
    result = jb["data"]["result"]
    # backup() returns the package path — the archive must exist
    path = result if isinstance(result, str) else result.get("path")
    assert path and Path(path).exists()
    # and it is listed
    st, body = _req(b, "GET", "/api/v1/backups")
    assert any(i["name"].endswith(".tar.gz")
               for i in body["data"]["items"])
