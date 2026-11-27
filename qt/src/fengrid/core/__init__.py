"""Fengrid core: Qt-free library logic (SQLite index, scanning, export).

Kept free of Qt imports so it is testable headless and reusable by any
front end (see docs/architecture/0001-qt6-rewrite.md §7 — the provider/core
split is what keeps the Qt layer thin).
"""
