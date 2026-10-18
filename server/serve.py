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
import functools
import http.server
import json
import os
import re
import shutil
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import urlparse, parse_qs

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
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