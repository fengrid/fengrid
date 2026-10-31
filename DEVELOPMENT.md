# Development

Everything you need to understand and work on Fengrid.

> **Project status:** Fengrid is the Qt 6 desktop app for managing UI
> design assets locally. It grew out of the original single-file HTML
> showcase (the "0.x" web UI, retired — see
> `docs/architecture/0001-qt6-rewrite.md` for the decision record).

## Structure

```
fengrid/                     # repo root
├── qt/                      # THE application (Qt 6 / PySide6)
│   ├── src/fengrid/
│   │   ├── __main__.py      # entry point: bridges, engine, QA harness
│   │   ├── app.py           # brand tokens (DARK/LIGHT), app constants
│   │   ├── core/            # pure-Python domain logic (no Qt imports)
│   │   │   ├── db.py        # SQLite schema + migrations (library.db)
│   │   │   ├── scanner.py   # icon source discovery + classification
│   │   │   ├── indexer.py   # scan → asset rows, metadata identification
│   │   │   ├── ingest.py    # folders/zips/imports, copy-or-link
│   │   │   ├── patterns.py  # renaming rules (regex/enum/GUID/CSV)
│   │   │   ├── export.py / exportplus.py   # multi-format export
│   │   │   ├── watch.py     # watch folders (rsync/scp/sftp/ftp/http)
│   │   │   ├── backup.py    # tar.gz backup/restore + restore scripts
│   │   │   ├── projects.py / studio.py     # project model, block canvas
│   │   │   ├── projects_git.py / history.py # git repos, undo/redo stack
│   │   │   ├── docker.py    # docker CLI integration
│   │   │   ├── assetrefs.py # [[ slug ]] / [[ GUID ]] resolution
│   │   │   ├── kinds.py     # asset-kind registry (image/data/timeseries…)
│   │   │   └── …            # colors, fonts, snippets, settings, updater
│   │   ├── bridges/         # QObject facades exposed to QML (one per pane)
│   │   └── web/             # sandboxed local preview support
│   ├── qml/                 # the UI: Main.qml + components/ per pane
│   ├── tests/               # pytest suite (235 tests)
│   └── pyproject.toml       # package metadata (Python ≥ 3.11)
├── api/v1/                  # REST API server (stdlib http), openapi.yaml,
│                            # postman_collection.json
├── build/scripts/           # packaging: build-linux.sh, build-macos.sh,
│                            # build-windows.ps1, build-docker-linux.sh
├── docker/                  # per-arch Dockerfiles for the build runners
├── fonts/                   # brand fonts bundled with the app + licenses
├── docs/                    # landing page + architecture decision records
└── README.md / QUICKSTART.md / DEVELOPMENT.md / LICENSE.md
```

## Branches

- `main` — stable, released versions (tagged, semver)
- `dev` — active development; features land here first and merge to
  `main` at release time
- `dev-qt` — the Qt6 rewrite line
- `v1.0.0-rc1-testing` — release-candidate testing branch (its PR
  targets `dev`, the staging branch for v1.0.0)

## Architecture in one paragraph

Core logic lives in `qt/src/fengrid/core/` as pure Python with no Qt
imports, so it is fully unit-testable headlessly. Each UI pane gets a
QObject **bridge** (`bridges/`) that exposes `@Property`s, `@Slot`s and
signals over that core; QML (`qt/qml/`) binds to the bridges and contains
no business logic. The REST API (`api/v1/`) is a thin stdlib
`ThreadingHTTPServer` over the same core — one source of truth, two
frontends. Assets are indexed into SQLite (`library.db`) with FTS search;
files stay on disk and are referenced by path (copy-or-link is an ingest
choice), and previews load through the hardened `fengrid-asset://` scheme
with an explicit allowlist.

## How it works

### Scanning & metadata

`core/scanner.py` discovers icon roots (system theme directories plus
user folders) and classifies paths into theme/context/size/name —
in-process and fingerprint-tracked (size + mtime, so unchanged files are
never re-identified). `core/fonts.py` is the same story for font folders
(`fc-scan` metadata via fontconfig when available).

### Data model

`core/db.py` owns the schema and migrations. Every tracked object
(asset, snippet, palette, collection, library, project) carries a
generated `guid` and a user-settable unique `slug`; structured-data
assets get a revisioned JSON payload (`asset_data`) and timeseries
points. Migrations must stay idempotent and run before any bridge
touches the DB.

### Live preview & [[ refs ]]

Project/snippet previews render through a sandboxed WebEngine profile
that allowlists exactly the scan index via `fengrid-asset://` URLs.
`[[ slug ]]`, `[[ GUID ]]` and `[[ kind/library/collection/name ]]`
references resolve through `core/assetrefs.py` — unresolved refs render
as visible placeholders, never raw.

### Studio (Projects pane)

`core/studio.py` stores each page as a JSON block tree (`studio_page`);
rendering resolves asset refs and reuses the same token generator as the
exporter. Templates substitute `{{vars}}` at instance-creation time.
`core/docker.py` wraps the docker CLI (argv only, never a shell) for
build/run/browse; `core/projects_git.py` gives every project a git repo
(`fengrid-main` default branch, LFS tracking, batch operations on
`batch/*` branches with commit-or-discard review).

## Testing

```bash
cd qt
.venv/bin/python -m pytest tests/ -q     # 235 tests, ~50 s
```

The suite covers the core modules (scanner, ingest, export, backup,
studio, docker, git, history, API) and QML structure (keys, colors,
settings) headlessly. `tests/qa_render.sh` captures offscreen
screenshots of each pane for visual QA:

```bash
QT_QPA_PLATFORM=offscreen FENGRID_NO_RELAUNCH=1 \
  .venv/bin/python -m fengrid --screenshot /tmp/fg.png --pane 4 --no-scan \
  --db /tmp/test.db --qa-select "name"
```

Rules of thumb: new core logic ships with tests; anything that could
block the UI thread (subprocesses, network, long scans) belongs in a
worker thread — a sync subprocess call inside a QML binding froze the
Settings screen once already (fixed in `42dcf9d`); native dialogs are
instantiated lazily (portal hang safety, see `db4477b`).

## Packaging

```bash
bash build/scripts/build-linux.sh linux-x64      # PyInstaller onedir → qt/dist/
FENGRID_SMOKE=1 bash build/scripts/build-linux.sh linux-x64   # + offscreen smoke
```

- Bundles carry their own Qt; host X/GL libs are stripped on purpose
  (the app falls back to software rendering where needed).
- The build regenerates its PyInstaller spec every run — never commit
  host-absolute `.spec` files.
- Docker runners (per-arch, no QEMU) come from `docker/*.Dockerfile`;
  `.github/workflows/build.yml` assembles the release matrix.

## Versioning & releases

Standard [semantic versioning](https://semver.org/). The version constant
lives in `qt/src/fengrid/__init__.py` (`__version__`), shown in the
status bar and used by the release probe and backup manifests. While on
a dev branch it carries a `-dev` suffix.

```bash
# 1. bump __version__, update CHANGELOG.md
# 2. commit, tag, push
git tag -a v1.0.0 -m "v1.0.0: summary"
git push origin main --follow-tags
```

## Conventions

- Plain claims over adjectives; match the existing code style; keep
  changes focused.
- Assets stay in their own folders — no stray files in the repo root,
  no duplicated copies (hash-compare before deleting anything).
- Never commit secrets; forge tokens live only in git config local to
  each repo, never in the database.
