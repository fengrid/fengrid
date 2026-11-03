"""Fengrid REST API v1.

A lightweight, dependency-free (stdlib-only) HTTP API over the same core
modules the desktop app uses: assets, collections, libraries, projects,
import/ingest, export, backups, DB admin, and watch folders.

Run it against a library database:

    python -m api.v1 --db ~/.local/share/fengrid/library.db --port 8642

Auth: every request needs `Authorization: Bearer <token>` except /health.
The token comes from --token or FENGRID_API_TOKEN; if neither is set the
server generates one and prints it on startup.
"""

API_VERSION = "1.0.0"
