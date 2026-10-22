"""HTTP server for the Fengrid REST API v1.

ThreadingHTTPServer + a single handler that:
1. runs middleware (auth, logging),
2. matches the route table in resources.py,
3. wraps results in the {ok, data} / {ok: false, error} envelope,
4. dispatches OPTIONS preflight and 404/405 cleanly.

Runnable headless:  python -m api.v1 --db <library.db> --port 8642
"""

from __future__ import annotations

import argparse
import inspect
import json
import logging
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .middleware import (CORS_HEADERS, ApiError, RequestLog, check_auth,
                         error_body, generate_token, ok_body, read_json)
from .scheduler import TaskScheduler
from . import resources
from .resources import Api


def _version() -> str:
    try:
        from fengrid import __version__
        return __version__
    except ImportError:                    # plain checkout: resources fixed
        return resources.version_fallback()  # sys.path on first import

log = logging.getLogger("fengrid.api")

# ─────────────────────────────────────────────────────────── route table
# (method, pattern) → handler; patterns are compiled once at import.
ROUTES: list[tuple[str, re.Pattern, str]] = [
    ("GET",  re.compile(r"^/api/v1/health$"), "health"),
    ("GET",  re.compile(r"^/api/v1/version$"), "health"),
    ("GET",  re.compile(r"^/api/v1/inventory$"), "inventory"),
    ("GET",  re.compile(r"^/api/v1/assets$"), "assets_list"),
    ("POST", re.compile(r"^/api/v1/assets/ingest$"), "assets_ingest"),
    ("POST", re.compile(r"^/api/v1/assets/export$"), "assets_export"),
    ("GET",  re.compile(r"^/api/v1/assets/(?P<kind>[a-z]+)/(?P<item_id>\d+)$"),
     "assets_describe"),
    ("PATCH", re.compile(r"^/api/v1/assets/(?P<kind>[a-z]+)/(?P<item_id>\d+)$"),
     "assets_patch"),
    ("POST", re.compile(r"^/api/v1/assets/(?P<kind>[a-z]+)/(?P<item_id>\d+)"
                        r"/star$"), "assets_star"),
    ("POST", re.compile(r"^/api/v1/assets/(?P<kind>[a-z]+)/(?P<item_id>\d+)"
                        r"/tags$"), "assets_tags"),
    ("GET",  re.compile(r"^/api/v1/assets/data/(?P<item_id>\d+)/points$"),
     "data_points_get"),
    ("POST", re.compile(r"^/api/v1/assets/data/(?P<item_id>\d+)/points$"),
     "data_points_append"),
    ("GET",  re.compile(r"^/api/v1/assets/data/(?P<item_id>\d+)/content$"),
     "data_content_get"),
    ("PUT",  re.compile(r"^/api/v1/assets/data/(?P<item_id>\d+)/content$"),
     "data_content_put"),
    ("PATCH", re.compile(r"^/api/v1/assets/data/(?P<item_id>\d+)/content$"),
     "data_content_patch"),
    ("DELETE", re.compile(r"^/api/v1/assets/data/(?P<item_id>\d+)/content$"),
     "data_content_delete"),
    ("GET",  re.compile(r"^/api/v1/links/resolve$"), "links_resolve"),
    ("POST", re.compile(r"^/api/v1/links/expand$"), "links_expand"),
    ("GET",  re.compile(r"^/api/v1/lookup$"), "assets_lookup"),
    ("POST", re.compile(r"^/api/v1/assets/(?P<kind>[a-z]+)/(?P<item_id>\d+)"
                        r"/collect$"), "assets_collect"),
    ("DELETE", re.compile(r"^/api/v1/assets/(?P<kind>[a-z]+)/(?P<item_id>\d+)"
                          r"/collect/(?P<ref_id>\d+)$"), "assets_uncollect"),
    ("POST", re.compile(r"^/api/v1/assets/(?P<kind>[a-z]+)/(?P<item_id>\d+)"
                        r"/copy$"), "assets_copy"),
    ("GET",  re.compile(r"^/api/v1/collections$"), "collections_list"),
    ("POST", re.compile(r"^/api/v1/collections$"), "collections_create"),
    ("GET",  re.compile(r"^/api/v1/collections/(?P<cid>\d+)$"),
     "collections_describe"),
    ("DELETE", re.compile(r"^/api/v1/collections/(?P<cid>\d+)$"),
     "collections_delete"),
    ("GET",  re.compile(r"^/api/v1/collections/(?P<cid>\d+)/refs$"),
     "collections_refs"),
    ("POST", re.compile(r"^/api/v1/collections/(?P<cid>\d+)/refs$"),
     "collections_add_ref"),
    ("GET",  re.compile(r"^/api/v1/libraries$"), "libraries_list"),
    ("POST", re.compile(r"^/api/v1/libraries$"), "libraries_create"),
    ("GET",  re.compile(r"^/api/v1/tags$"), "tags_list"),
    ("PATCH", re.compile(r"^/api/v1/tags/(?P<name>[^/]+)$"), "tags_rename"),
    ("DELETE", re.compile(r"^/api/v1/tags/(?P<name>[^/]+)$"), "tags_delete"),
    ("GET",  re.compile(r"^/api/v1/fields$"), "fields_list"),
    ("POST", re.compile(r"^/api/v1/fields$"), "fields_create"),
    ("DELETE", re.compile(r"^/api/v1/fields/(?P<fid>\d+)$"), "fields_delete"),
    ("GET",  re.compile(r"^/api/v1/projects$"), "projects_list"),
    ("GET",  re.compile(r"^/api/v1/projects/(?P<pid>\d+)$"),
     "projects_describe"),
    ("GET",  re.compile(r"^/api/v1/backups$"), "backups_list"),
    ("POST", re.compile(r"^/api/v1/backups$"), "backup_create"),
    ("POST", re.compile(r"^/api/v1/backup/restore$"), "backup_restore"),
    ("POST", re.compile(r"^/api/v1/db/(?P<op>[a-z_]+)$"), "db_admin"),
    ("GET",  re.compile(r"^/api/v1/watch$"), "watch_list"),
    ("POST", re.compile(r"^/api/v1/watch$"), "watch_create"),
    ("DELETE", re.compile(r"^/api/v1/watch/(?P<wid>\d+)$"), "watch_delete"),
    ("POST", re.compile(r"^/api/v1/watch/(?P<wid>\d+)/run$"), "watch_run"),
    ("GET",  re.compile(r"^/api/v1/jobs$"), "jobs_list"),
    ("GET",  re.compile(r"^/api/v1/jobs/(?P<jid>[0-9a-f]+)$"), "jobs_get"),
    ("DELETE", re.compile(r"^/api/v1/jobs/(?P<jid>[0-9a-f]+)$"), "jobs_cancel"),
]

_ACTIVE_ONLY = object()


def make_api(db_path: str, data_dir: str | None = None,
             workers: int = 3) -> Api:
    return Api(db_path, data_dir=data_dir,
               scheduler=TaskScheduler(workers=workers))


def make_handler(api: Api, token: str | None):
    """Build a handler class bound to one Api context + auth token."""

    class Handler(BaseHTTPRequestHandler):
        server_version = f"FengridAPI/{_version()}"
        protocol_version = "HTTP/1.1"
        _rlog = RequestLog()

        # ------------------------------------------------------ plumbing
        def log_message(self, format, *args):    # noqa: A002 - stdlib name
            pass                                 # silence default stderr

        def _cors(self) -> None:
            for k, v in CORS_HEADERS.items():
                self.send_header(k, v)

        def _send(self, status: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self._cors()
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> bytes:
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                return self.rfile.read(length)
            return b""

        # dispatch for every verb
        def _dispatch(self, method: str) -> None:
            path = self.path.split("?", 1)[0]
            query = self.path.split("?", 1)[1] if "?" in self.path else ""
            params = dict(pair.split("=", 1) for pair in
                          (kv for kv in query.split("&") if "=" in kv)) \
                if query else {}
            params = {k: v.replace("%20", " ") for k, v in params.items()}
            self._rlog.start(method, path)
            try:
                if method == "OPTIONS":
                    self.send_response(204)
                    self._cors()
                    self.end_headers()
                    return
                check_auth(self.headers, token)
                status, payload = self._route(method, path, params)
            except ApiError as e:
                status, payload = e.status, error_body(e.status, e.code,
                                                       e.message)
            except Exception as e:                    # noqa: BLE001
                log.exception("unhandled error for %s %s", method, path)
                status, payload = 500, error_body(
                    500, "internal_error", f"{type(e).__name__}: {e}")
            self._rlog.finish(method, path, status)
            self._send(status, payload)

        def _route(self, method: str, path: str, params: dict):
            body = read_json(self._body()) \
                if method in ("POST", "PATCH", "PUT") else {}
            matched_path = False
            for m, pattern, fname in ROUTES:
                match = pattern.match(path)
                if not match:
                    continue
                matched_path = True
                if m != method:
                    continue
                handler = getattr(resources, fname)
                kwargs = match.groupdict()
                sig = inspect.signature(handler)
                args = [api, body]
                if "params" in sig.parameters:
                    args.append(params)
                for k, v in kwargs.items():
                    if k in sig.parameters:
                        args.append(int(v) if v.isdigit() else v)
                out = handler(*args)
                # job submissions answer 202 Accepted with the job handle
                if fname.startswith("jobs"):
                    done = isinstance(out, dict) and out.get("state") in (
                        "done", "failed")
                    return (200 if done else 202), \
                        {"ok": True, "data": out}
                return ok_body(out)
            if matched_path:
                raise ApiError(405, "method_not_allowed",
                               f"{method} not allowed on {path}")
            raise ApiError(404, "not_found", f"no route: {path}")

        # --------------------------------------------------- verbs
        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

        def do_PATCH(self):
            self._dispatch("PATCH")

        def do_DELETE(self):
            self._dispatch("DELETE")

        def do_OPTIONS(self):
            self._dispatch("OPTIONS")

    return Handler


def serve(db_path: str, host: str = "127.0.0.1", port: int = 8642,
          token: str | None = "__generate__", data_dir: str | None = None,
          workers: int = 3) -> tuple[ThreadingHTTPServer, str]:
    """Create (and return, not run) the server. token semantics:
    "__generate__" → mint one and print it; None → open (insecure);
    any other string → used as-is."""
    api = make_api(db_path, data_dir=data_dir, workers=workers)
    if token == "__generate__":
        token = generate_token()
    elif token == "":
        token = None            # open mode (--insecure)
    httpd = ThreadingHTTPServer((host, port),
                                make_handler(api, token))
    return httpd, token or ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fengrid-api", description="Fengrid REST API v1 server")
    parser.add_argument("--db", required=True,
                        help="path to the fengrid library.db")
    parser.add_argument("--data-dir", default=None,
                        help="asset data dir (default: db's parent)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8642)
    parser.add_argument("--token", default="",
                        help="bearer token ('' → FENGRID_API_TOKEN,"
                             " unset → generated and printed)")
    parser.add_argument("--insecure", action="store_true",
                        help="disable auth (localhost use only)")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    if args.insecure:
        token = None
    elif args.token:
        token = args.token
    elif os.environ.get("FENGRID_API_TOKEN"):
        token = os.environ["FENGRID_API_TOKEN"]
    else:
        token = generate_token()

    httpd, _ = serve(args.db, host=args.host, port=args.port,
                     token=token if token else "", data_dir=args.data_dir,
                     workers=args.workers)
    # serve() with token "" means open — pass None instead
    if token is None:
        httpd, _ = serve(args.db, host=args.host, port=args.port,
                         token=None, data_dir=args.data_dir,
                         workers=args.workers)
    print(f"Fengrid API v1 ({_version()}) on http://{args.host}:{args.port}"
          f"/api/v1 — db: {args.db}", file=sys.stderr)
    if token:
        print(f"  token: {token}", file=sys.stderr)
    else:
        print("  auth: DISABLED (--insecure)", file=sys.stderr)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
