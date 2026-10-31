"""Request middleware: bearer-token auth, JSON envelope, CORS, body cap.

Kept deliberately small — each piece is a function the request handler
calls inline (no decorator framework to learn), so the HTTP layer stays
auditable in one file.
"""

from __future__ import annotations

import json
import logging
import secrets
import time

MAX_BODY = 10 * 1024 * 1024          # 10 MB request cap
log = logging.getLogger("fengrid.api")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def error_body(status: int, code: str, message: str) -> dict:
    return {"ok": False, "error": {"code": code, "message": message,
                                   "status": status}}


def ok_body(data, status: int = 200) -> tuple[int, dict]:
    return (status, {"ok": True, "data": data})


def generate_token() -> str:
    return secrets.token_urlsafe(24)


class RequestLog:
    """One line per request: method, path, status, duration."""

    def __init__(self):
        self._t0 = 0.0

    def start(self, method: str, path: str) -> None:
        self._t0 = time.time()

    def finish(self, method: str, path: str, status: int) -> None:
        log.info("%s %s -> %s (%.1fms)", method, path, status,
                 (time.time() - self._t0) * 1000)


def check_auth(headers, token: str | None) -> None:
    """Raise 401 unless the bearer token matches. token=None = open
    (explicit --insecure mode, localhost use only)."""
    if token is None:
        return
    auth = headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or \
            not secrets.compare_digest(auth[7:].strip(), token):
        raise ApiError(401, "unauthorized",
                       "missing or invalid bearer token")


def read_json(body: bytes) -> dict:
    """Parse the request body; reject oversize and malformed payloads."""
    if len(body) > MAX_BODY:
        raise ApiError(413, "body_too_large",
                       f"body exceeds {MAX_BODY} bytes")
    if not body:
        return {}
    try:
        data = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise ApiError(400, "bad_json", f"invalid JSON body: {e}")
    if not isinstance(data, dict):
        raise ApiError(400, "bad_json", "JSON body must be an object")
    return data


CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, PATCH, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "Authorization, Content-Type",
}
