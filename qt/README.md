# Fengrid — Qt 6 workbench (skeleton)

Status: **skeleton**. This is the bottom-up starting point described in
`docs/architecture/0001-qt6-rewrite.md` — it launches a QML shell carrying the
brand (glint-quad mark, dark tokens) and exits cleanly. No library features
yet; those land in M0/M1 (SQLite core, providers, workbench layout).

The 0.x app (the five single-file panes at the repo root) is untouched and
frozen as the parity reference — see `docs/review/2026-current-state-review.md`.

## Run locally

```sh
cd qt
python3 -m venv .venv && . .venv/bin/activate
pip install -e .
fengrid
```

Requires a display (this is a GUI; headless boxes need a virtual display).

## Build

The 12-target build pipelines live in `docker/` and `build/scripts/`
(DRAFT status — see `docker/README.md`). They package this skeleton via
PyInstaller; the entry point is `src/fengrid/__main__.py`.

## Tests

`tests/` is the M0 slot (pytest + pytest-qt smoke). None yet — the pipelines
are drafted, not executed, per the 2026-10-18 task.
