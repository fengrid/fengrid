#!/usr/bin/env python3
"""
serve.py — optional local webshare for the Fengrid.

Serves the install directory on the local network so phones and tablets
can browse the showcase by scanning the QR code on the /_connect page.

CORS / security notes
---------------------
- The showcase makes NO cross-origin requests: the page, icons/, and data
  files are all served same-origin from this directory, so no CORS headers
  are required and none are added. Do not add permissive
  Access-Control-Allow-Origin headers to a LAN share.
- Directory listings are disabled; only real files are served.
- The listener binds to 0.0.0.0 by default (needed for other devices to
  reach it). Use --host 127.0.0.1 to keep it local-only — which is what
  the `fengrid` launcher does when it auto-starts the server.
- The /_connect page renders a QR code of the URL reachable from other
  devices; it is served with no-store caching.
"""

import argparse
import atexit
import email
import email.parser
import functools
import http.server
import io
import json
import os
import re
import shutil
import socket
import socketserver
import subprocess
import sqlite3
import sys
import tarfile
import tempfile
import threading
import time
import uuid
import zipfile
import urllib.parse
from urllib.parse import urlparse, parse_qs

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SERVER_DIR)
import import_engine  # noqa: E402  (server/import_engine.py lives next to us)
import snippet_import  # noqa: E402  (server/snippet_import.py lives next to us)
# The served web root is the parent of server/ — the install dir holding
# index.html, list.txt, fonts/ and icons/ (see install.sh layout).
WEB_ROOT = os.path.dirname(SERVER_DIR)


def lan_ip():
    """IP of the interface that would route to the internet (best guess)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("203.0.113.1", 80))  # TEST-NET, never actually sent
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def all_ips():
    """Every non-loopback interface address, best-first."""
    ips = []
    best = lan_ip()
    if best:
        ips.append(best)
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if not ip.startswith("127.") and ip not in ips:
                ips.append(ip)
    except OSError:
        pass
    return ips


class Handler(http.server.SimpleHTTPRequestHandler):
    # 'directory' is injected per-server via functools.partial in main()
    def list_directory(self, path):
        # disable directory listings
        self.send_error(404, "File not found")
        return None

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        if urlparse(self.path).path == "/_connect":
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        # fresh server state for already-open pages (no-store)
        if path == "/server-state.js":
            body = self.server.state_js()
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/convert":
            self.handle_convert()
            return
        if path == "/refresh":
            self.handle_refresh()
            return
        if path == "/import":
            self.handle_import()
            return
        if path == "/fonts-export":
            self.handle_fonts_export()
            return
        if path.startswith("/api/"):
            self.handle_api("GET")
            return
        # /_connect is a virtual path, so its relative asset refs resolve to
        # /vendor/... — serve those from the server/ dir explicitly
        if path.startswith("/vendor/") and "/" not in path[len("/vendor/"):]:
            f = os.path.join(SERVER_DIR, "vendor", os.path.basename(path))
            if os.path.isfile(f):
                ctype = "application/javascript" if f.endswith(".js") else "application/octet-stream"
                with open(f, "rb") as fh:
                    body = fh.read()
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
        if path == "/_connect":
            body = self.render_connect()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def render_connect(self):
        """Inject the LAN URL the connect page will QR-encode."""
        tpl = os.path.join(SERVER_DIR, "connect.html")
        with open(tpl, "rb") as f:
            html = f.read().decode("utf-8")
        alts = [ip for ip in all_ips() if ip != self.server.lan_host]
        html = html.replace("__LAN_URL__", self.server.lan_url)
        html = html.replace(
            "__ALT_INFO__",
            ("try http://<ip>:%d/ for: " % self.server.port) + ", ".join(alts)
            if alts else "run `ip addr` / `ifconfig` on this machine",
        )
        return html.encode("utf-8")

    # --- /convert: ImageMagick-backed export for the showcase UI -----------
    #
    # GET /convert?src=<rel under icons/>&fmt=<png|jpeg|webp|ico|pdf|gif|
    #                                      tiff|bmp>&size=<16..1024|orig>
    #
    # Security: `src` is strictly validated (relative, inside icons/, no
    # traversal, known extension); fmt and size are whitelisted; the source
    # is never passed through a shell. ImageMagick runs on user-supplied
    # image files — its security policy is the operator's configuration, as
    # with any server that shells out to IM.
    CONVERT_EXTS = {"png", "svg", "ico", "jpg", "jpeg", "gif", "webp", "bmp", "xpm"}
    FMT_OUT = {"png": "png", "jpeg": "jpeg", "jpg": "jpeg", "webp": "webp",
               "ico": "ico", "pdf": "pdf", "gif": "gif", "tiff": "tiff",
               "bmp": "bmp"}
    FMT_TYPE = {"png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp",
                "ico": "image/x-icon", "pdf": "application/pdf",
                "gif": "image/gif", "tiff": "image/tiff", "bmp": "image/bmp"}

    def handle_convert(self):
        qs = parse_qs(urlparse(self.path).query)
        src = (qs.get("src", [""])[0] or "").lstrip("/")
        fmt = (qs.get("fmt", ["png"])[0] or "png").lower()
        size = (qs.get("size", ["orig"])[0] or "orig").lower()

        if not re.fullmatch(r"icons/[A-Za-z0-9._\-/]+", src) or ".." in src:
            return self._convert_error(400, "bad src")
        ext = src.rsplit(".", 1)[-1].lower() if "." in src else ""
        if ext not in self.CONVERT_EXTS:
            return self._convert_error(400, "bad src extension")
        if fmt not in self.FMT_OUT:
            return self._convert_error(400, "unsupported format")
        if size != "orig" and not (size.isdigit() and 8 <= int(size) <= 1024):
            return self._convert_error(400, "bad size")

        imagemagick = shutil.which("magick") or shutil.which("convert")
        if not imagemagick:
            return self._convert_error(501, "ImageMagick not installed on this machine")

        src_path = os.path.normpath(os.path.join(self.server.app_dir, src))
        if not src_path.startswith(os.path.join(self.server.app_dir, "icons") + os.sep) \
                or not os.path.isfile(src_path):
            return self._convert_error(404, "not found")

        base = os.path.basename(src_path).rsplit(".", 1)[0] or "icon"
        base = re.sub(r"[^A-Za-z0-9._\-]", "_", base)[:80]
        out_ext = self.FMT_OUT[fmt]

        try:
            with tempfile.TemporaryDirectory(prefix="icon-export-") as tmp:
                out_path = os.path.join(tmp, "out." + out_ext)
                cmd = [imagemagick, src_path]
                if fmt == "ico":
                    cmd += ["-define", "icon:auto-resize=16,24,32,48,64"]
                if size != "orig" and fmt != "ico":
                    cmd += ["-resize", "%sx%s" % (size, size)]
                cmd += [out_path]
                proc = subprocess.run(cmd, capture_output=True, timeout=30)
                if proc.returncode != 0 or not os.path.isfile(out_path):
                    msg = proc.stderr.decode("utf-8", "replace").strip().splitlines()
                    return self._convert_error(500, msg[-1] if msg else "conversion failed")
                with open(out_path, "rb") as f:
                    body = f.read()
        except subprocess.TimeoutExpired:
            return self._convert_error(504, "conversion timed out")
        except Exception as exc:  # noqa: BLE001 — surfaced to the UI
            return self._convert_error(500, str(exc))

        suffix = "" if size == "orig" else "-" + size
        fname = "%s%s.%s" % (base, suffix, out_ext)
        self.send_response(200)
        self.send_header("Content-Type", self.FMT_TYPE[out_ext])
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Disposition", 'attachment; filename="%s"' % fname)
        self.end_headers()
        self.wfile.write(body)

    def _convert_error(self, code, msg):
        body = ("conversion failed: %s" % msg).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # --- /refresh: re-scan icons/ and update the metadata ledger -----------
    #
    # GET /refresh?mode=enabled|force
    #
    # Runs the install's own refresh-icons.sh (picks up manually dropped
    # files, prunes removed ones, regenerates list.js) and icon-meta.sh
    # (fingerprint-tracked metadata rebuild). mode=force re-identifies every
    # icon; enabled (default) only touches new/changed files. The UI calls
    # this from the refresh button — Shift-click sends force. A refresh can
    # take a while on large sets; one runs at a time (409 when busy).

    REFRESH_LOCK = threading.Lock()

    def _json_response(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def handle_refresh(self):
        qs = parse_qs(urlparse(self.path).query)
        mode = (qs.get("mode", ["enabled"])[0] or "enabled").lower()
        if mode not in ("enabled", "force"):
            return self._json_response(400, {"ok": False, "error": "bad mode (enabled|force)"})

        if not Handler.REFRESH_LOCK.acquire(blocking=False):
            return self._json_response(409, {"ok": False, "error": "a refresh is already running"})
        started = time.time()
        try:
            app = self.server.app_dir
            refresh = os.path.join(app, "refresh-icons.sh")
            meta = os.path.join(app, "icon-meta.sh")
            missing = [os.path.basename(p) for p in (refresh, meta) if not os.path.isfile(p)]
            if missing:
                return self._json_response(
                    501, {"ok": False, "error": "not installed: " + ", ".join(missing)})

            def run(cmd):
                p = subprocess.run(cmd, capture_output=True, timeout=900, text=True)
                return p.returncode, p.stdout.strip().splitlines(), p.stderr.strip()

            rc1, out1, err1 = run(["bash", refresh, "--dir", app, "--update-metadata", mode])
            rc2, out2, err2 = run(["bash", meta, app, "--quiet", "--mode", mode])
            notes = [l for l in (out1 + out2) if l][:8]
            ok = rc1 == 0 and rc2 == 0
            resp = {"ok": ok, "mode": mode, "seconds": round(time.time() - started, 1),
                    "notes": notes}
            if not ok:
                resp["error"] = (err1 or err2 or "refresh failed").splitlines()[-1][:200]
            return self._json_response(200 if ok else 500, resp)
        except subprocess.TimeoutExpired:
            return self._json_response(504, {"ok": False, "error": "refresh timed out"})
        except Exception as exc:  # noqa: BLE001 — surfaced to the UI
            return self._json_response(500, {"ok": False, "error": str(exc)})
        finally:
            Handler.REFRESH_LOCK.release()

    # ------------------------------------------------------------------
    # POST /import  — uploaded archives and picked folders (multipart)
    #
    # The browser cannot hand the page a filesystem path, so folder and
    # .zip imports arrive as a manually assembled multipart/form-data body:
    #   fields: kind ("zip" | "folder"), name (optional theme name)
    #   files:  filename = path relative to the picked folder's root
    # The body is parsed with the email package (multipart-aware), written
    # to a temp dir, then run through the same import + refresh + metadata
    # pipeline as the GET forms. One import/refresh at a time.
    # ------------------------------------------------------------------
    def do_POST(self):
        if urlparse(self.path).path.startswith("/api/"):
            self.handle_api("POST")
            return
        if urlparse(self.path).path == "/import":
            self.handle_import_post()
            return
        if urlparse(self.path).path == "/fonts-export":
            self.handle_fonts_export()
            return
        self.send_error(404, "Not found")

    def _read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > import_engine.MAX_DOWNLOAD:
            raise ValueError("empty or oversized upload (limit %d MB)"
                             % (import_engine.MAX_DOWNLOAD >> 20))
        return self.rfile.read(length)

    def handle_import_post(self):
        started = time.time()
        try:
            body = self._read_body()
        except Exception as exc:  # noqa: BLE001
            return self._json_response(400, {"ok": False, "error": str(exc)})
        if not Handler.REFRESH_LOCK.acquire(blocking=False):
            return self._json_response(
                409, {"ok": False, "error": "an import or refresh is already running"})
        started = time.time()
        tmpdir = tempfile.TemporaryDirectory(prefix="fengrid-upload-")
        try:
            msg = email.parser.BytesParser().parsebytes(
                b"Content-Type: " + self.headers.get("Content-Type", "").encode()
                + b"\r\nMIME-Version: 1.0\r\n\r\n" + body)
            fields, src_dir = {}, os.path.join(tmpdir.name, "src")
            os.makedirs(src_dir, exist_ok=True)
            for part in msg.walk():
                if part.is_multipart():
                    continue
                fname = part.get_filename()
                if fname:
                    rel = fname.replace("\\", "/").lstrip("/")
                    if ".." in rel.split("/"):
                        raise ValueError("unsafe upload path: " + fname)
                    dest = os.path.join(src_dir, rel)
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with open(dest, "wb") as f:
                        f.write(part.get_payload(decode=True) or b"")
                else:
                    fields[part.get_param("name", header="content-disposition")] = \
                        part.get_payload(decode=True).decode("utf-8", "replace")
            kind = fields.get("kind", "folder")
            name = fields.get("name") or None
            if kind == "zip":
                zips = [f for f in os.listdir(src_dir) if f.lower().endswith(".zip")]
                if len(zips) != 1:
                    raise ValueError("expected exactly one .zip file in the upload")
                with open(os.path.join(src_dir, zips[0]), "rb") as f:
                    data = f.read()
                result = import_engine.import_archive(
                    data, zips[0], self.server.app_dir, name)
            else:
                result = import_engine.import_folder(src_dir, self.server.app_dir, name)
            return self._finish_import(result, started)
        except Exception as exc:  # noqa: BLE001 — surfaced to the UI
            return self._json_response(500, {"ok": False, "error": str(exc)[:300]})
        finally:
            tmpdir.cleanup()
            Handler.REFRESH_LOCK.release()

    def handle_import(self):
        """GET /import?kind=folder|url|iconify|catalog — server-side sources."""
        qs = parse_qs(urlparse(self.path).query)
        kind = (qs.get("kind", [""])[0] or "").lower()
        app = self.server.app_dir
        try:
            if kind == "catalog":
                return self._json_response(200, {"ok": True,
                                                 "sets": import_engine.catalog()})
            if not Handler.REFRESH_LOCK.acquire(blocking=False):
                return self._json_response(
                    409, {"ok": False, "error": "an import or refresh is already running"})
            started = time.time()
            try:
                name = (qs.get("name", [""])[0] or "").strip() or None
                if kind == "folder":
                    result = import_engine.import_folder(
                        qs.get("path", [""])[0], app, name)
                elif kind == "url":
                    result = import_engine.import_url(
                        qs.get("url", [""])[0], app, name)
                elif kind == "iconify":
                    result = import_engine.import_iconify(
                        (qs.get("set", [""])[0] or "").strip(), app, name)
                else:
                    return self._json_response(
                        400, {"ok": False, "error": "bad kind (folder|url|iconify|catalog)"})
                return self._finish_import(result, started)
            finally:
                Handler.REFRESH_LOCK.release()
        except subprocess.TimeoutExpired:
            return self._json_response(504, {"ok": False, "error": "import timed out"})
        except Exception as exc:  # noqa: BLE001 — surfaced to the UI
            return self._json_response(500, {"ok": False, "error": str(exc)[:300]})

    def do_PUT(self):
        if urlparse(self.path).path.startswith("/api/"):
            self.handle_api("PUT")
            return
        self.send_error(404, "Not found")

    def do_DELETE(self):
        if urlparse(self.path).path.startswith("/api/"):
            self.handle_api("DELETE")
            return
        self.send_error(404, "Not found")

    # ------------------------------------------------------------------
    # /api/snippets — local SQLite-backed snippet store for code.html
    #
    # Schema: snippets(id, title, description, language, html, css, js,
    #                  tags, created, updated)
    # Tags are comma-separated in a single column (mirrors the icon
    # showcase's localStorage tag model); the /api/tags endpoint expands
    # them into a distinct list with counts.
    # ------------------------------------------------------------------
    def _snippet_db(self):
        conn = sqlite3.connect(os.path.join(self.server.app_dir, "snippets.db"))
        conn.row_factory = sqlite3.Row
        conn.execute("""CREATE TABLE IF NOT EXISTS snippets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL DEFAULT 'Untitled',
            description TEXT NOT NULL DEFAULT '',
            language TEXT NOT NULL DEFAULT 'web',
            html TEXT NOT NULL DEFAULT '',
            css TEXT NOT NULL DEFAULT '',
            js TEXT NOT NULL DEFAULT '',
            tags TEXT NOT NULL DEFAULT '',
            created TEXT NOT NULL DEFAULT (datetime('now')),
            updated TEXT NOT NULL DEFAULT (datetime('now'))
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS palettes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL DEFAULT 'Untitled palette',
            colors TEXT NOT NULL DEFAULT '[]',
            tags TEXT NOT NULL DEFAULT '',
            created TEXT NOT NULL DEFAULT (datetime('now')),
            updated TEXT NOT NULL DEFAULT (datetime('now'))
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            tags TEXT NOT NULL DEFAULT '',
            settings TEXT NOT NULL DEFAULT '{}',
            created TEXT NOT NULL DEFAULT (datetime('now')),
            updated TEXT NOT NULL DEFAULT (datetime('now'))
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS project_assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            asset_type TEXT NOT NULL,
            asset_key TEXT NOT NULL,
            label TEXT NOT NULL DEFAULT '',
            UNIQUE(project_id, asset_type, asset_key)
        )""")
        return conn

    # ------------------------------------------------------------------
    # Project asset resolution — maps an (asset_type, asset_key) pair to
    # real files in the install tree for archive export. Icon/font keys
    # are RELATIVE paths under icons/ or fonts/ (traversal-checked);
    # snippet/palette keys are row ids resolved from the database.
    # ------------------------------------------------------------------
    def _resolve_asset(self, app_dir, atype, key):
        if atype == "icon":
            p = os.path.realpath(os.path.join(app_dir, "icons", key))
            base = os.path.realpath(os.path.join(app_dir, "icons"))
            if not p.startswith(base + os.sep) or not os.path.isfile(p):
                return None
            return ("assets/icons/" + key.replace(os.sep, "/"), p)
        if atype == "font":
            p = os.path.realpath(os.path.join(app_dir, "fonts", key))
            base = os.path.realpath(os.path.join(app_dir, "fonts"))
            if not p.startswith(base + os.sep) or not os.path.isfile(p):
                return None
            return ("assets/fonts/" + key.replace(os.sep, "/"), p)
        return None

    def handle_api(self, method):
        path = urlparse(self.path).path
        qs = parse_qs(urlparse(self.path).query)
        try:
            conn = self._snippet_db()
            try:
                if path == "/api/tags" and method == "GET":
                    rows = conn.execute("SELECT tags FROM snippets WHERE tags != ''").fetchall()
                    counts = {}
                    for r in rows:
                        for t in r["tags"].split(","):
                            t = t.strip()
                            if t:
                                counts[t] = counts.get(t, 0) + 1
                    return self._json_response(200, {"ok": True, "tags": [
                        {"name": k, "count": v} for k, v in sorted(counts.items(), key=lambda x: -x[1])]})

                if path == "/api/snippets":
                    if method == "GET":
                        q = (qs.get("q", [""])[0] or "").strip()
                        tag = (qs.get("tag", [""])[0] or "").strip()
                        sort = (qs.get("sort", ["updated"])[0] or "updated")
                        sql = "SELECT id, title, description, language, tags, created, updated FROM snippets"
                        wh, args = [], []
                        if q:
                            wh.append("(title LIKE ? OR description LIKE ? OR tags LIKE ?)")
                            args += ["%" + q + "%"] * 3
                        if tag:
                            wh.append("(',' || tags || ',') LIKE ?")
                            args.append("%," + tag + ",%")
                        if wh:
                            sql += " WHERE " + " AND ".join(wh)
                        sql += " ORDER BY " + ("title COLLATE NOCASE" if sort == "title" else
                                               "created" if sort == "created" else "updated DESC")
                        rows = [dict(r) for r in conn.execute(sql, args).fetchall()]
                        return self._json_response(200, {"ok": True, "snippets": rows})

                    if method == "POST":
                        body = self._read_json()
                        cur = conn.execute(
                            "INSERT INTO snippets (title, description, language, html, css, js, tags) "
                            "VALUES (?,?,?,?,?,?,?)",
                            (body.get("title", "Untitled"), body.get("description", ""),
                             body.get("language", "web"), body.get("html", ""),
                             body.get("css", ""), body.get("js", ""),
                             body.get("tags", "")))
                        conn.commit()
                        row = conn.execute("SELECT * FROM snippets WHERE id = ?", (cur.lastrowid,)).fetchone()
                        return self._json_response(201, {"ok": True, "snippet": dict(row)})
                    return self._json_response(405, {"ok": False, "error": "method not allowed"})

                m = re.match(r"^/api/snippets/(\d+)$", path)
                if m:
                    sid = int(m.group(1))
                    if method == "GET":
                        row = conn.execute("SELECT * FROM snippets WHERE id = ?", (sid,)).fetchone()
                        if not row:
                            return self._json_response(404, {"ok": False, "error": "not found"})
                        return self._json_response(200, {"ok": True, "snippet": dict(row)})
                    if method == "PUT":
                        body = self._read_json()
                        fields, args = [], []
                        for k in ("title", "description", "language", "html", "css", "js", "tags"):
                            if k in body:
                                fields.append(k + " = ?")
                                args.append(body[k])
                        if not fields:
                            return self._json_response(400, {"ok": False, "error": "nothing to update"})
                        fields.append("updated = datetime('now')")
                        args.append(sid)
                        conn.execute("UPDATE snippets SET " + ", ".join(fields) + " WHERE id = ?", args)
                        conn.commit()
                        row = conn.execute("SELECT * FROM snippets WHERE id = ?", (sid,)).fetchone()
                        return self._json_response(200, {"ok": True, "snippet": dict(row)})
                    if method == "DELETE":
                        conn.execute("DELETE FROM snippets WHERE id = ?", (sid,))
                        conn.commit()
                        return self._json_response(200, {"ok": True})
                    return self._json_response(405, {"ok": False, "error": "method not allowed"})

                # ---------------- snippet import (VSCode / massCode) ------
                # GET  /api/snippets/import?kind=vscode[&path=…]   (no path:
                #      scans the editor's default snippets folders)
                # GET  /api/snippets/import?kind=masscode[&path=…] (no path:
                #      tries massCode's default db.sqlite locations)
                # POST /api/snippets/import — multipart: kind + file upload
                #      (.code-snippets/.json for vscode, .sqlite for masscode)
                if path == "/api/snippets/import":
                    kind = (qs.get("kind", ["vscode"])[0] or "vscode").strip().lower()
                    src_path = (qs.get("path", [""])[0] or "").strip()
                    if method == "POST":
                        kind, src_path = self._snippet_import_post_parts(kind)
                    try:
                        if kind == "masscode":
                            found = []
                            if not src_path:
                                found = snippet_import.masscode_default_paths()
                                if not found:
                                    return self._json_response(404, {
                                        "ok": False,
                                        "error": "no massCode database found — pass &path= to your db.sqlite"})
                            paths = [src_path] if src_path else found
                            for p in paths:
                                if not os.path.isfile(p):
                                    return self._json_response(400, {
                                        "ok": False, "error": "not a file: " + p})
                            incoming = []
                            for p in paths:
                                incoming.extend(snippet_import.parse_masscode_db(p))
                        else:
                            kind = "vscode"
                            paths = [src_path] if src_path else snippet_import.vscode_default_paths()
                            if not paths:
                                return self._json_response(404, {
                                    "ok": False,
                                    "error": "no VSCode snippets folders found — pass &path= to a .code-snippets or .json file"})
                            incoming = []
                            for p in paths:
                                if os.path.isdir(p):
                                    for fn in sorted(os.listdir(p)):
                                        if fn.endswith((".json", ".code-snippets")):
                                            with open(os.path.join(p, fn), encoding="utf-8", errors="replace") as f:
                                                incoming.extend(snippet_import.parse_vscode(f.read()))
                                elif os.path.isfile(p):
                                    with open(p, encoding="utf-8", errors="replace") as f:
                                        text = f.read()
                                    incoming.extend(snippet_import.parse_vscode(text))
                                else:
                                    return self._json_response(400, {
                                        "ok": False, "error": "path not found: " + p})
                    except (ValueError, json.JSONDecodeError) as exc:
                        return self._json_response(400, {"ok": False, "error": str(exc)[:300]})
                    except sqlite3.DatabaseError as exc:
                        return self._json_response(400, {
                            "ok": False, "error": "cannot read database: " + str(exc)[:200]})

                    inserted, skipped, titles = 0, 0, []
                    for sn in incoming:
                        dup = conn.execute(
                            "SELECT 1 FROM snippets WHERE title = ? AND html = ? "
                            "AND css = ? AND js = ?",
                            (sn["title"], sn["html"], sn["css"], sn["js"])).fetchone()
                        if dup:
                            skipped += 1
                            continue
                        conn.execute(
                            "INSERT INTO snippets (title, description, language, html, css, js, tags) "
                            "VALUES (?,?,?,?,?,?,?)",
                            (sn["title"], sn["description"], sn["language"],
                             sn["html"], sn["css"], sn["js"], sn["tags"]))
                        inserted += 1
                        titles.append(sn["title"])
                    if inserted:
                        conn.commit()
                    return self._json_response(200, {
                        "ok": True, "kind": kind, "imported": inserted,
                        "skipped": skipped, "titles": titles[:50]})

                # ---------------- palettes (colors.html) ----------------
                if path == "/api/palettes":
                    if method == "GET":
                        q = (qs.get("q", [""])[0] or "").strip()
                        tag = (qs.get("tag", [""])[0] or "").strip()
                        sort = (qs.get("sort", ["updated"])[0] or "updated")
                        sql = "SELECT id, name, colors, tags, created, updated FROM palettes"
                        wh, args = [], []
                        if q:
                            wh.append("(name LIKE ? OR tags LIKE ?)")
                            args += ["%" + q + "%"] * 2
                        if tag:
                            wh.append("(',' || tags || ',') LIKE ?")
                            args.append("%," + tag + ",%")
                        if wh:
                            sql += " WHERE " + " AND ".join(wh)
                        sql += " ORDER BY " + ("name COLLATE NOCASE" if sort == "name" else
                                               "created" if sort == "created" else "updated DESC")
                        rows = [dict(r) for r in conn.execute(sql, args).fetchall()]
                        for r in rows:
                            try:
                                r["colors"] = json.loads(r["colors"])
                            except Exception:
                                r["colors"] = []
                        return self._json_response(200, {"ok": True, "palettes": rows})
                    if method == "POST":
                        body = self._read_json()
                        colors = body.get("colors", [])
                        if not isinstance(colors, list) or not colors:
                            return self._json_response(400, {"ok": False, "error": "colors must be a non-empty list"})
                        cur = conn.execute("INSERT INTO palettes (name, colors, tags) VALUES (?,?,?)",
                                           (body.get("name", "Untitled palette"),
                                            json.dumps(colors), body.get("tags", "")))
                        conn.commit()
                        row = conn.execute("SELECT * FROM palettes WHERE id = ?", (cur.lastrowid,)).fetchone()
                        d = dict(row)
                        d["colors"] = json.loads(d["colors"])
                        return self._json_response(201, {"ok": True, "palette": d})
                    return self._json_response(405, {"ok": False, "error": "method not allowed"})

                mp = re.match(r"^/api/palettes/(\d+)$", path)
                if mp:
                    pid = int(mp.group(1))
                    if method == "GET":
                        row = conn.execute("SELECT * FROM palettes WHERE id = ?", (pid,)).fetchone()
                        if not row:
                            return self._json_response(404, {"ok": False, "error": "not found"})
                        d = dict(row)
                        d["colors"] = json.loads(d["colors"])
                        return self._json_response(200, {"ok": True, "palette": d})
                    if method == "PUT":
                        body = self._read_json()
                        fields, args = [], []
                        if "name" in body:
                            fields.append("name = ?"); args.append(body["name"])
                        if "colors" in body:
                            fields.append("colors = ?"); args.append(json.dumps(body["colors"]))
                        if "tags" in body:
                            fields.append("tags = ?"); args.append(body["tags"])
                        if not fields:
                            return self._json_response(400, {"ok": False, "error": "nothing to update"})
                        fields.append("updated = datetime('now')")
                        args.append(pid)
                        conn.execute("UPDATE palettes SET " + ", ".join(fields) + " WHERE id = ?", args)
                        conn.commit()
                        row = conn.execute("SELECT * FROM palettes WHERE id = ?", (pid,)).fetchone()
                        d = dict(row)
                        d["colors"] = json.loads(d["colors"])
                        return self._json_response(200, {"ok": True, "palette": d})
                    if method == "DELETE":
                        conn.execute("DELETE FROM palettes WHERE id = ?", (pid,))
                        conn.commit()
                        return self._json_response(200, {"ok": True})
                    return self._json_response(405, {"ok": False, "error": "method not allowed"})

                # ---------------- projects (projects.html) ----------------
                # Assets live in the join table project_assets — the same
                # (type, key) pair may appear in any number of projects.
                if path == "/api/projects":
                    if method == "GET":
                        q = (qs.get("q", [""])[0] or "").strip()
                        tag = (qs.get("tag", [""])[0] or "").strip()
                        sql = "SELECT id, name, description, tags, created, updated FROM projects"
                        wh, args = [], []
                        if q:
                            wh.append("(name LIKE ? OR description LIKE ? OR tags LIKE ?)")
                            args += ["%" + q + "%"] * 3
                        if tag:
                            wh.append("(',' || tags || ',') LIKE ?")
                            args.append("%," + tag + ",%")
                        if wh:
                            sql += " WHERE " + " AND ".join(wh)
                        sql += " ORDER BY updated DESC"
                        rows = [dict(r) for r in conn.execute(sql, args).fetchall()]
                        for r in rows:
                            r["asset_count"] = conn.execute(
                                "SELECT COUNT(*) c FROM project_assets WHERE project_id = ?",
                                (r["id"],)).fetchone()["c"]
                        return self._json_response(200, {"ok": True, "projects": rows})
                    if method == "POST":
                        body = self._read_json()
                        name = (body.get("name") or "").strip()
                        if not name:
                            return self._json_response(400, {"ok": False, "error": "name required"})
                        cur = conn.execute(
                            "INSERT INTO projects (name, description, tags, settings) VALUES (?,?,?,?)",
                            (name, body.get("description", ""), body.get("tags", ""),
                             json.dumps(body.get("settings", {}))))
                        conn.commit()
                        row = conn.execute("SELECT * FROM projects WHERE id = ?", (cur.lastrowid,)).fetchone()
                        d = dict(row)
                        d["settings"] = json.loads(d["settings"])
                        return self._json_response(201, {"ok": True, "project": d})
                    return self._json_response(405, {"ok": False, "error": "method not allowed"})

                mj = re.match(r"^/api/projects/(\d+)(/assets(/(\d+))?)?(/export)?$", path)
                if mj:
                    pid = int(mj.group(1))
                    row = conn.execute("SELECT * FROM projects WHERE id = ?", (pid,)).fetchone()
                    if not row:
                        return self._json_response(404, {"ok": False, "error": "not found"})
                    project = dict(row)
                    project["settings"] = json.loads(project["settings"] or "{}")

                    if mj.group(5):  # /export
                        if method != "POST":
                            return self._json_response(405, {"ok": False, "error": "POST required"})
                        return self._export_project(conn, project, self._read_json() if int(
                            self.headers.get("Content-Length") or 0) else {})

                    if mj.group(2) is None:  # project itself
                        if method == "GET":
                            assets = [dict(a) for a in conn.execute(
                                "SELECT id, asset_type, asset_key, label FROM project_assets "
                                "WHERE project_id = ? ORDER BY asset_type, id", (pid,)).fetchall()]
                            return self._json_response(200, {"ok": True, "project": project, "assets": assets})
                        if method == "PUT":
                            body = self._read_json()
                            fields, args = [], []
                            for k in ("name", "description", "tags"):
                                if k in body:
                                    fields.append(k + " = ?"); args.append(body[k])
                            if "settings" in body:
                                fields.append("settings = ?"); args.append(json.dumps(body["settings"]))
                            if not fields:
                                return self._json_response(400, {"ok": False, "error": "nothing to update"})
                            fields.append("updated = datetime('now')")
                            args.append(pid)
                            conn.execute("UPDATE projects SET " + ", ".join(fields) + " WHERE id = ?", args)
                            conn.commit()
                            row = conn.execute("SELECT * FROM projects WHERE id = ?", (pid,)).fetchone()
                            d = dict(row); d["settings"] = json.loads(d["settings"] or "{}")
                            return self._json_response(200, {"ok": True, "project": d})
                        if method == "DELETE":
                            conn.execute("DELETE FROM project_assets WHERE project_id = ?", (pid,))
                            conn.execute("DELETE FROM projects WHERE id = ?", (pid,))
                            conn.commit()
                            return self._json_response(200, {"ok": True})
                        return self._json_response(405, {"ok": False, "error": "method not allowed"})

                    # /assets
                    if method == "POST":
                        body = self._read_json()
                        atype = body.get("asset_type", "")
                        akey = str(body.get("asset_key", "")).strip()
                        if atype not in ("icon", "font", "snippet", "palette") or not akey:
                            return self._json_response(400, {"ok": False, "error": "asset_type/asset_key required"})
                        if atype in ("icon", "font") and not self._resolve_asset(
                                self.server.app_dir, atype, akey):
                            return self._json_response(400, {"ok": False, "error": "asset file not found: " + akey})
                        conn.execute(
                            "INSERT OR IGNORE INTO project_assets (project_id, asset_type, asset_key, label) "
                            "VALUES (?,?,?,?)",
                            (pid, atype, akey, body.get("label", "")))
                        conn.execute("UPDATE projects SET updated = datetime('now') WHERE id = ?", (pid,))
                        conn.commit()
                        assets = [dict(a) for a in conn.execute(
                            "SELECT id, asset_type, asset_key, label FROM project_assets "
                            "WHERE project_id = ? ORDER BY asset_type, id", (pid,)).fetchall()]
                        return self._json_response(201, {"ok": True, "assets": assets})
                    return self._json_response(405, {"ok": False, "error": "method not allowed"})

                ma = re.match(r"^/api/projects/(\d+)/assets/(\d+)$", path)
                if ma and method == "DELETE":
                    conn.execute("DELETE FROM project_assets WHERE id = ? AND project_id = ?",
                                 (int(ma.group(2)), int(ma.group(1))))
                    conn.commit()
                    return self._json_response(200, {"ok": True})

                return self._json_response(404, {"ok": False, "error": "unknown endpoint"})
            finally:
                conn.close()
        except Exception as exc:  # noqa: BLE001 — surfaced to the UI
            return self._json_response(500, {"ok": False, "error": str(exc)[:300]})

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > 4 * 1024 * 1024:
            raise ValueError("empty or oversized request body")
        return json.loads(self.rfile.read(length))

    def _snippet_import_post_parts(self, default_kind):
        """Parse the /api/snippets/import multipart POST.

        Returns (kind, upload_path): `kind` from the kind field (upload
        filename may override it), upload_path = a temp file holding the
        uploaded .code-snippets/.json/.sqlite payload, or '' when the
        request carried no file.
        """
        body = self._read_body()
        msg = email.parser.BytesParser().parsebytes(
            b"Content-Type: " + self.headers.get("Content-Type", "").encode()
            + b"\r\nMIME-Version: 1.0\r\n\r\n" + body)
        kind = default_kind
        upload = None
        for part in msg.walk():
            if part.is_multipart():
                continue
            name = part.get_param("name", header="content-disposition")
            fname = part.get_filename()
            if name == "kind" and not fname:
                kind = bytes(part.get_payload(decode=True) or b"").decode(
                    "utf-8", "replace").strip().lower() or default_kind
            elif fname:
                upload = (fname, part.get_payload(decode=True) or b"")
        if not upload:
            return kind, ""
        fname, data = upload
        if kind == "vscode" and fname.endswith((".sqlite", ".db")):
            kind = "masscode"
        elif kind == "masscode" and fname.endswith((".json", ".code-snippets")):
            kind = "vscode"
        suffix = os.path.splitext(fname)[1] or ".bin"
        tmp = tempfile.NamedTemporaryFile(prefix="fengrid-snippet-import-", suffix=suffix, delete=False)
        try:
            tmp.write(bytes(data))
        finally:
            tmp.close()
        return kind, tmp.name

    # ------------------------------------------------------------------
    # POST /api/projects/<id>/export — build a distributable archive
    # (.zip or .tar.gz) containing the project's selected assets plus
    # generated CSS/JS/template files. Everything is generated fresh from
    # the DB + install tree; nothing is cached.
    # ------------------------------------------------------------------
    def _export_project(self, conn, project, opts):
        app = self.server.app_dir
        pid = project["id"]
        assets = [dict(a) for a in conn.execute(
            "SELECT id, asset_type, asset_key, label FROM project_assets "
            "WHERE project_id = ? ORDER BY asset_type, id", (pid,)).fetchall()]
        s = project.get("settings") or {}
        prefix = re.sub(r"[^a-z0-9-]", "", str(s.get("prefix", "fg"))) or "fg"
        icon_px = int(s.get("iconSize", 32) or 32)

        palettes, snippets, icon_files, font_files = [], [], [], []
        for a in assets:
            if a["asset_type"] == "palette":
                row = conn.execute("SELECT * FROM palettes WHERE id = ?",
                                   (int(a["asset_key"]),)).fetchone()
                if row:
                    d = dict(row); d["colors"] = json.loads(d["colors"])
                    palettes.append(d)
            elif a["asset_type"] == "snippet":
                row = conn.execute("SELECT * FROM snippets WHERE id = ?",
                                   (int(a["asset_key"]),)).fetchone()
                if row:
                    snippets.append(dict(row))
            elif a["asset_type"] in ("icon", "font"):
                r = self._resolve_asset(app, a["asset_type"], a["asset_key"])
                if r:
                    (icon_files if a["asset_type"] == "icon" else font_files).append((a, r))

        def cssvar_name(pal, i):
            base = re.sub(r"[^a-z0-9]+", "-", (pal.get("name") or "palette").lower()).strip("-")
            return "--%s-%s-%d" % (prefix, base or "palette", i + 1)

        colors_css, fonts_css, icons_css, icons_js = [], [], [], []
        for pal in palettes:
            for i, c in enumerate(pal["colors"]):
                colors_css.append("  %s: %s;" % (cssvar_name(pal, i), c))
        if colors_css:
            colors_css.insert(0, ":root {")
            colors_css.append("}")
        for a, (arcname, abspath) in font_files:
            family = (a.get("label") or a["asset_key"].split("/")[0]).replace("_", " ")
            rel = arcname.split("/", 2)[2] if arcname.count("/") >= 2 else arcname
            ext = os.path.splitext(abspath)[1].lower()
            fmt = {"ttf": "truetype", "otf": "opentype", "woff": "woff",
                   ".woff2": "woff2"}.get(ext.lstrip("."), "truetype")
            fonts_css.append(
                "@font-face { font-family: '%s'; src: url('%s') format('%s'); }"
                % (family, arcname, fmt))
        for a, (arcname, abspath) in icon_files:
            stem = os.path.splitext(os.path.basename(a["asset_key"]))[0]
            cls = re.sub(r"[^a-z0-9-]", "-", (a.get("label") or stem).lower()).strip("-")
            icons_css.append(".%s-%s { background-image: url('%s'); }" % (prefix, cls, arcname))
            icons_js.append('  "%s": "%s"' % (stem, arcname))
        icons_js_s = ("window.%sIcons = {\n  %s\n};\n" % (prefix, ",\n  ".join(icons_js))
                      if icons_js else "window.%sIcons = {};\n" % prefix)

        # Demo template — uses the chosen palette, fonts, and icons.
        pal0 = palettes[0]["colors"] if palettes else []
        bg = s.get("bgColor") or (pal0[0] if pal0 else "#101418")
        fg = s.get("fgColor") or (pal0[-1] if pal0 else "#E7EDF2")
        accent = s.get("accentColor") or (pal0[min(2, len(pal0) - 1)] if pal0 else "#39B8C4")
        font_stack = ", ".join("'%s'" % (a.get("label") or a["asset_key"].split("/")[0]).replace("_", " ")
                               for a, _ in font_files[:3]) or "system-ui, sans-serif"
        icon_imgs = "\n".join(
            '      <div class="icon" style="background-image:url(\'%s\')" title="%s"></div>'
            % (arcname, os.path.splitext(os.path.basename(arcname))[0])
            for a, (arcname, _) in icon_files[:48])
        font_samples = "\n".join(
            '    <p style="font-family:\'%s\'">The quick brown fox jumps over the lazy dog — %s</p>'
            % ((a.get("label") or a["asset_key"].split("/")[0]).replace("_", " "),
               (a.get("label") or a["asset_key"].split("/")[0]).replace("_", " "))
            for a, _ in font_files[:8])
        swatches = "\n".join(
            '      <div class="swatch" style="background:%s"><span>%s</span></div>' % (c, c)
            for pal in palettes for c in pal["colors"])
        template = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>%s — generated by fengrid</title>
<link rel="stylesheet" href="css/colors.css">
<link rel="stylesheet" href="css/fonts.css">
<link rel="stylesheet" href="css/icons.css">
<style>
  body { margin:0; padding:40px; background:%s; color:%s;
         font-family:%s, system-ui, sans-serif; }
  .icons { display:flex; flex-wrap:wrap; gap:12px; }
  .icon { width:%dpx; height:%dpx; background-size:contain;
          background-repeat:no-repeat; background-position:center; }
  .swatches { display:flex; flex-wrap:wrap; gap:10px; margin:24px 0; }
  .swatch { width:96px; height:64px; border-radius:10px; display:flex;
            align-items:flex-end; justify-content:center; padding-bottom:6px;
            font:11px/1 monospace; color:rgba(255,255,255,.85);
            text-shadow:0 1px 2px rgba(0,0,0,.5); }
  h1, h2 { font-weight:600; }
</style>
</head>
<body>
  <h1>%s</h1>
  <p>%s</p>
  <h2>Palette</h2>
  <div class="swatches">
%s
  </div>
  <h2>Icons</h2>
  <div class="icons">
%s
  </div>
  <h2>Type</h2>
%s
  <script src="js/icons.js"></script>
</body>
</html>
""" % (project["name"], bg, fg, font_stack, icon_px, icon_px,
            project["name"], project.get("description") or "", swatches or
            '      <div class="swatch">no palette selected</div>', icon_imgs or
            '      <div class="icon"></div>', font_samples or
            "    <p>No fonts selected.</p>")

        manifest = {
            "name": project["name"], "description": project.get("description", ""),
            "tags": project.get("tags", ""), "settings": s,
            "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "generator": "fengrid",
            "assets": [{"type": a["asset_type"], "key": a["asset_key"], "label": a.get("label", "")}
                       for a in assets],
            "palettes": [{"name": p.get("name"), "colors": p["colors"]} for p in palettes],
        }
        readme = "# %s\n\n%s\n\nGenerated by fengrid (%s).\n\n" % (
            project["name"], project.get("description") or "", manifest["generated"])
        readme += ("## Contents\n\n"
                   "- `index.html` — demo template using the project's assets\n"
                   "- `css/colors.css` — palette custom properties\n"
                   "- `css/fonts.css` — @font-face rules\n"
                   "- `css/icons.css` — icon classes\n"
                   "- `js/icons.js` — icon name map\n"
                   "- `assets/` — the selected files\n"
                   "- `manifest.json` — project specification\n")

        fmt = "targz" if str(opts.get("format", s.get("format", "zip"))) in ("targz", "tar.gz", "tgz") else "zip"
        buf = io.BytesIO()
        if fmt == "zip":
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                def put(name, data):
                    z.writestr(name, data)
                put("manifest.json", json.dumps(manifest, indent=2))
                put("README.md", readme)
                if colors_css: put("css/colors.css", "\n".join(colors_css) + "\n")
                if fonts_css: put("css/fonts.css", "\n".join(fonts_css) + "\n")
                if icons_css: put("css/icons.css", "\n".join(icons_css) + "\n")
                put("js/icons.js", icons_js_s)
                put("index.html", template)
                if palettes: put("palettes.json", json.dumps(
                    [{"name": p["name"], "colors": p["colors"]} for p in palettes], indent=2))
                for i, sn in enumerate(snippets):
                    put("snippets/%02d-%s.html" % (i + 1, re.sub(r"[^a-z0-9-]+", "-",
                        sn["title"].lower()).strip("-") or "snippet"),
                        "<!DOCTYPE html>\n<!-- %s\n%s -->\n%s" % (
                            sn["title"], sn.get("description", ""), sn.get("html", "")))
                for a, (arcname, abspath) in icon_files + font_files:
                    with open(abspath, "rb") as f:
                        z.writestr(arcname, f.read())
        else:
            with tarfile.open(fileobj=buf, mode="w:gz") as t:
                def put(name, data):
                    info = tarfile.TarInfo(name)
                    raw = data.encode("utf-8")
                    info.size = len(raw); info.mtime = int(time.time())
                    t.addfile(info, io.BytesIO(raw))
                put("manifest.json", json.dumps(manifest, indent=2))
                put("README.md", readme)
                if colors_css: put("css/colors.css", "\n".join(colors_css) + "\n")
                if fonts_css: put("css/fonts.css", "\n".join(fonts_css) + "\n")
                if icons_css: put("css/icons.css", "\n".join(icons_css) + "\n")
                put("js/icons.js", icons_js_s)
                put("index.html", template)
                if palettes: put("palettes.json", json.dumps(
                    [{"name": p["name"], "colors": p["colors"]} for p in palettes], indent=2))
                for i, sn in enumerate(snippets):
                    put("snippets/%02d-%s.html" % (i + 1, re.sub(r"[^a-z0-9-]+", "-",
                        sn["title"].lower()).strip("-") or "snippet"),
                        "<!DOCTYPE html>\n<!-- %s\n%s -->\n%s" % (
                            sn["title"], sn.get("description", ""), sn.get("html", "")))
                for a, (arcname, abspath) in icon_files + font_files:
                    info = t.gettarinfo(abspath, arcname=arcname)
                    t.addfile(info, open(abspath, "rb"))

        data = buf.getvalue()
        fname = re.sub(r"[^a-z0-9-]+", "-", project["name"].lower()).strip("-") or "project"
        self.send_response(200)
        self.send_header("Content-Type",
                         "application/zip" if fmt == "zip" else "application/gzip")
        self.send_header("Content-Disposition",
                         'attachment; filename="%s.%s"' % (fname, "zip" if fmt == "zip" else "tar.gz"))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _finish_import(self, result, started):
        """Shared tail: refresh the list + metadata, then report."""
        app = self.server.app_dir
        refresh = os.path.join(app, "refresh-icons.sh")
        meta = os.path.join(app, "icon-meta.sh")
        notes = []
        ok = True
        for script, args in ((refresh, ["--dir", app, "--update-metadata", "enabled"]),
                             (meta, [app, "--quiet", "--mode", "enabled"])):
            if not os.path.isfile(script):
                notes.append("not installed: " + os.path.basename(script))
                ok = False
                continue
            p = subprocess.run(["bash", script] + args,
                               capture_output=True, timeout=1200, text=True)
            if p.returncode != 0:
                ok = False
                notes.append((p.stderr.strip() or "script failed").splitlines()[-1][:200])
            else:
                notes += [l for l in p.stdout.strip().splitlines() if l][:4]
        result.update({"ok": ok, "seconds": round(time.time() - started, 1),
                       "notes": notes[:8]})
        return self._json_response(200 if ok else 500, result)

    # ------------------------------------------------------------------
    # POST /fonts-export — package selected fonts as a ZIP download
    #
    # Body: JSON {"files": ["fonts/Family/file.ttf", ...], "css": "..."}
    # The server validates each path (must live under fonts/), bundles the
    # font files with the generated CSS and a README, and returns the ZIP.
    # ------------------------------------------------------------------
    def handle_fonts_export(self):
        if urlparse(self.path).path != "/fonts-export":
            return self.send_error(404)
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > 16 * 1024 * 1024:
                raise ValueError("empty or oversized request")
            body = json.loads(self.rfile.read(length))
            files = body.get("files", [])
            css = body.get("css", "")
            if not files or not isinstance(files, list):
                raise ValueError("no files given")
            if len(files) > 500:
                raise ValueError("too many fonts (limit 500)")

            app = self.server.app_dir
            fonts_root = os.path.normpath(os.path.join(app, "fonts"))
            valid = []
            for rel in files:
                # reject anything that could escape fonts/
                if not isinstance(rel, str) or ".." in rel or rel.startswith("/"):
                    continue
                full = os.path.normpath(os.path.join(app, rel))
                if not full.startswith(fonts_root + os.sep) or not os.path.isfile(full):
                    continue
                valid.append((rel, full))
            if not valid:
                raise ValueError("no valid font files matched")

            import zipfile as zf
            import io
            buf = io.BytesIO()
            with zf.ZipFile(buf, "w", zf.ZIP_DEFLATED) as z:
                readme = (
                    "fengrid fonts export\n"
                    "====================\n\n"
                    "%d font file(s) selected from your local collection.\n\n"
                    "Usage: include fonts.css in your project and reference the\n"
                    "font families in your CSS. Each @font-face rule maps a\n"
                    "family/style/weight to the file in fonts/.\n\n"
                    "Generated by fengrid — https://github.com/fengrid/fengrid\n"
                ) % len(valid)
                z.writestr("README.txt", readme)
                if css:
                    z.writestr("fonts.css", css)
                for rel, full in valid:
                    # keep the fonts/<Family>/<file> structure inside the zip
                    arcname = rel.replace("\\", "/").lstrip("/")
                    if not arcname.startswith("fonts/"):
                        arcname = "fonts/" + arcname
                    z.write(full, arcname)

            fname = "fengrid-fonts-%d.zip" % len(valid)
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(len(buf.getvalue())))
            self.send_header("Content-Disposition", 'attachment; filename="%s"' % fname)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(buf.getvalue())
        except Exception as exc:  # noqa: BLE001 — surfaced to the UI
            self.send_response(500)
            msg = json.dumps({"ok": False, "error": str(exc)[:300]}).encode()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)


class HTTPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    # set in main(); declared here so static analysis sees them
    lan_url = ""
    lan_host = ""
    port = 0
    app_dir = ""

    def state_js(self):
        # loopback-only servers advertise no LAN alternates
        ips = [i for i in all_ips()] if not self.lan_host.startswith("127.") \
            else ["127.0.0.1"]
        ips_js = ", ".join('"%s"' % i for i in ips)
        return ('window.LAN_WEBSHARE={url:"%s",port:%d,ips:[%s],started:"%s"};\n'
                % (self.lan_url, self.port, ips_js,
                   time.strftime("%Y-%m-%d %H:%M:%S"))).encode("utf-8")


def main():
    ap = argparse.ArgumentParser(description="Serve the Fengrid on the local network")
    ap.add_argument("--port", type=int, default=8642)
    ap.add_argument("--host", default="0.0.0.0", help="bind address (use 127.0.0.1 for local-only)")
    ap.add_argument("--dir", default=WEB_ROOT, help="directory to serve (default: the install dir above server/)")
    ap.add_argument("--kill-existing", action="store_true",
                    help="stop any other serve.py instances on this port before starting")
    ns = ap.parse_args()

    app_dir = os.path.abspath(ns.dir)
    os.chdir(app_dir)

    if ns.kill_existing and sys.platform != "win32":
        # stop other serve.py instances bound to the same port (a previous
        # backgrounded launch is the usual cause of EADDRINUSE)
        import subprocess
        try:
            out = subprocess.run(
                ["ps", "-eo", "pid,args"],
                capture_output=True, text=True, timeout=5,
            ).stdout
        except Exception:
            out = ""
        for line in out.splitlines():
            parts = line.strip().split(None, 1)
            if len(parts) != 2 or "serve.py" not in parts[1]:
                continue
            if "--kill-existing" in parts[1]:
                continue
            # only consider instances serving the same port
            if ("--port %d" % ns.port) not in parts[1] and ("--port=%d" % ns.port) not in parts[1]:
                continue
            try:
                os.kill(int(parts[0]), 15)
                print("  stopped existing server (pid %s)" % parts[0])
            except OSError:
                pass
        time.sleep(0.3)

    lan = lan_ip() or socket.gethostname()
    try:
        server = HTTPServer((ns.host, ns.port), functools.partial(Handler, directory=app_dir))
    except OSError as e:
        if getattr(e, "errno", None) == 98 or "already in use" in str(e):
            print("Port %d is already in use — another server (possibly an older" % ns.port)
            print("serve.py launch) is still running on it.")
            print("Fix: run with --kill-existing to stop it automatically, or")
            print("     pkill -f 'serve.py --port %d'" % ns.port)
            print("     …or pick another port:  --port 8643")
            sys.exit(1)
        raise
    if ns.host in ("127.0.0.1", "::1", "localhost"):
        # loopback bind (the launcher's local-only mode): the LAN URL would
        # be unreachable, so advertise the loopback address instead
        lan = "127.0.0.1"
    server.lan_url = "http://%s:%d/" % (lan, ns.port)
    server.lan_host = lan
    server.port = ns.port
    server.app_dir = app_dir

    # persist state so file:// pages can discover the LAN URL; removed on
    # clean shutdown (a stale file after SIGKILL is probed for reachability)
    state_file = os.path.join(app_dir, "server-state.js")
    with open(state_file, "w") as f:
        f.write(server.state_js().decode("utf-8"))

    def _cleanup():
        try:
            os.remove(state_file)
        except OSError:
            pass
    atexit.register(_cleanup)

    urls = []
    if ns.host == "0.0.0.0":
        urls.append(server.lan_url)
        urls.append("http://127.0.0.1:%d/  (this machine only)" % ns.port)
    else:
        urls.append("http://%s:%d/" % (ns.host, ns.port))

    print("Fengrid webshare")
    print("  serving: %s" % app_dir)
    for u in urls:
        print("  open:    %s" % u)
    print("  connect: %s_connect   <- open this on a desktop; scan the QR with a phone" % server.lan_url)
    if ns.host == "0.0.0.0":
        print("  note:    bound to all interfaces — only share on networks you trust")
    print("  Ctrl-C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()
        _cleanup()


if __name__ == "__main__":
    main()