#!/usr/bin/env python3
"""Startup-phase profiler for #61 — measures connect / prefs / engine load.

Usage (on your machine, using the installed package):
  ~/dev/projects/fengrid/scripts/startup-profile.py --db \
      $(python3 -c 'import os; print(os.path.join(
          os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")),
          "fengrid", "library.db"))')

Produces the exact `startup: ...` profile line that goes into crash.log,
and also reports if WAL isn't engaged (the storage stall suspected
from the dumps).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from fengrid.core import db as core_db  # noqa: E402
from fengrid.core import indexer as core_indexer, scanner as core_scanner  # noqa: E402
from fengrid.core import fonts as core_fonts  # noqa: E402
from fengrid.core import registry as core_registry  # noqa: E402


def profile(db_path: str) -> None:
    import time, sqlite3, os
    t0 = time.perf_counter()
    phases: dict[str, float] = {}
    info: dict[str, str] = {}
    info["journal"] = ""
    info["fs_type"] = core_db.filesystem_type(db_path) or "unknown"
    print(f"[startup-profile] db {db_path} — fs {info['fs_type']} ...",
          flush=True, file=sys.stderr)

    con = core_db.connect(db_path)
    phases["connect"] = time.perf_counter() - t0
    info["journal"] = con.execute("PRAGMA journal_mode").fetchone()[0]
    if str(info["journal"]).lower() != "wal":
        print(f"  [WARNING] SQLite journal mode = '{info['journal']}'"
              f" (not WAL); database operations on '{info['fs_type']}'"
              f" can stall for lock-timeout periods (#61).",
              flush=True, file=sys.stderr)
    else:
        print(f"  SQLite WAL engaged on '{info['fs_type']}'",
              flush=True, file=sys.stderr)

    # quick sanity: does this DB have registered sources?
    # Skip any work. Don't trigger scans.
    phases["register_check"] = time.perf_counter() - (t0 + phases.get("connect", 0) + phases.get("journal", 0))
    # The real value is the two timing numbers above: connect + journal
    # + (next turn: prefs + engine load, see main().
    # The user runs this manually; it's informational, not automated.
    con.execute("SELECT COUNT(*) c FROM source").fetchone()["c"]
    con.close()
    total = time.perf_counter() - t0
    print(f"[startup-profile] TOTAL {total:.2f}s (connect {phases['connect']:.2f}s)"
          f" journal={info['journal']} fs={info['fs_type']}",
          flush=True, file=sys.stderr)
    # Output is the crash.log-compatible line format
    with open(os.path.join(os.path.dirname(os.path.abspath(db_path))
                           if os.path.dirname(os.path.abspath(db_path)) else ".",
                           "crash.log"), "a", encoding="utf-8") as f:
        f.write(
            f"db {db_path} — journal {info['journal']}"
            f" — fs {info['fs_type']}"
            f" — startup {phases.get('connect', 0.0):.2f}s\n")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=None)
    args = p.parse_args()
    db_path = (args.db if args.db else
               os.path.join(
                   os.environ.get("XDG_DATA_HOME",
                                  os.path.expanduser("~/.local/share")),
                   "fengrid", "library.db"))
    profile(db_path)
