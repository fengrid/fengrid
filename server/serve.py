#!/usr/bin/env python3
"""
serve.py — optional local webshare for the Icon Browser.

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
  reach it). Use --host 127.0.0.1 to keep it local-only.
- The /_connect page renders a QR code of the URL reachable from other
  devices; it is served with no-store caching.
"""

import argparse
import atexit
import functools
import http.server
import os
import socket
import socketserver
import sys
import time
from urllib.parse import urlparse

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


class HTTPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    # set in main(); declared here so static analysis sees them
    lan_url = ""
    lan_host = ""
    port = 0
    app_dir = ""

    def state_js(self):
        ips = ", ".join('"%s"' % i for i in all_ips())
        return ('window.LAN_WEBSHARE={url:"%s",port:%d,ips:[%s],started:"%s"};\n'
                % (self.lan_url, self.port, ips,
                   time.strftime("%Y-%m-%d %H:%M:%S"))).encode("utf-8")


def main():
    ap = argparse.ArgumentParser(description="Serve the Icon Browser on the local network")
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

    print("Icon Browser webshare")
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