# Fengrid

[![License: MIT](https://img.shields.io/badge/license-MIT-2a313b)](LICENSE.md)

A local-first **UI asset workbench** for Linux, macOS and Windows — a
native Qt 6 (PySide6) desktop application that brings every asset in your
design workflow into one searchable, inspectable, exportable workspace:
icon sets, font families, color schemes, code snippets, and complete
front-end projects.

## Why

Design assets are scattered: icons live in system theme directories, fonts
in a dozen folders, palettes in image files, snippets in editor storage.
Fengrid scans, characterizes, and indexes all of it into one local library
(SQLite, no cloud, no account), then gives every asset type a dedicated
workspace with live previews, real export tooling, and revision control —
so you stop wrestling file managers and image-conversion websites.

## The five panes

- **Icons** — filterable, searchable grid of every icon on your machine
  (system themes + your folders); hover inspector with pixel dimensions,
  color count and variants; export to PNG/WebP/ICO/PDF and more; batch
  tint and resize on export.
- **Fonts** — installed families with live specimens; CSS/`@font-face`
  and zip export with weight/style filtering; woff2/woff packaging.
- **Colors** — palette generator (WCAG readouts), terminal color themes,
  5–7 color schemes, export as HEX/HSL/RGB/CMYK lists or board images.
- **Code** — snippet library with a real syntax-highlighted editor
  (HTML/CSS/JS/Markdown), live preview, import/export in bundle,
  VS Code and massCode formats.
- **Projects** — a multi-screen studio: a block-canvas **Design** screen
  whose blocks bind Fengrid assets via `[[ slug ]]` references, the token
  **Theme** configurator, **Templates** for tenant/multi-instance
  variants, **Docker** packaging (build/run/inspect containers, browse
  container storage), **Docs** auto-characterization, and git-backed
  revisions (one repo per project, default branch `fengrid-main`,
  batch operations on their own branches).

Every tracked asset — including images, video, audio, documents,
structured data, spatial and timeseries files — carries a generated
GUID and an optional unique slug, linkable from snippets and project
code as `[[ slug ]]`, `[[ GUID ]]` or `[[ kind/library/collection/name ]]`.

## Also on board

- **Import/ingest** — folders, zips, watch folders (local, rsync, scp,
  sftp, ftp, http; S3 planned), copy-or-link semantics, automated format
  conversion, regex/enumeration/GUID/CSV renaming.
- **Export** — multi-format batches, per-type extended options
  (icon tinting/resizing, webfont packaging, color-code lists), script
  hooks, full round-trip bundles.
- **Backup & restore** — one `*.tar.gz` per backup: manifest (version,
  settings, environment, logs), full SQLite copies, and per-OS restore
  scripts that refuse to run where Fengrid is installed or running.
- **REST API** — `api/v1`: bearer-token HTTP API for ingest, inventory,
  export, collections, projects, backups, watch folders and data-asset
  CRUD (OpenAPI spec + Postman collection included).
- **Undo/redo** with strict memory caps, disabled for bulk operations.
- **Source control** — git (with LFS) per project/library, stash,
  branches, batch ops with commit-or-discard review.

## Install

**From a release bundle** (recommended): download
`fengrid-prod-linux-x64.tar.gz` (or arm64 / macOS / Windows artifacts)
from the releases page, unpack, and run the `fengrid` binary.

**From source:**

```bash
git clone https://github.com/fengrid/fengrid.git
cd fengrid/qt
uv sync --no-dev              # frozen env from the committed uv.lock
uv run python -m fengrid
```

(uv first: `curl -LsSf https://astral.sh/uv/install.sh | sh` on Linux/macOS
or the installer at https://docs.astral.sh/uv/getting-started/installation/;
plain `uv sync` without `--no-dev` adds the QA toolchain for development.)

**Build a distributable bundle:**

```bash
bash build/scripts/build-linux.sh linux-x64     # or linux-arm64
# artifacts land in qt/dist/ — see build/scripts/ for macOS/Windows
```

Requires Python ≥ 3.11. On Linux the bundles carry their own Qt; a source
run gets its dependencies from the committed `qt/uv.lock` (uv) and works on
both X11 and Wayland.

## Documentation

| Doc | Contents |
|-----|----------|
| [QUICKSTART.md](QUICKSTART.md) | run it, first scan, the API, the five panes — the short path |
| [DEVELOPMENT.md](DEVELOPMENT.md) | architecture, structure, testing, packaging, versioning |
| [docs/architecture/](docs/architecture/) | decision records (Qt6 rewrite, editor bindings) |
| [LICENSE.md](LICENSE.md) | MIT license + bundled font licenses |

## License

[MIT](LICENSE.md) — Native IT © 2026. Bundled fonts are licensed separately
(SIL OFL 1.1 / MIT) — see [LICENSE.md](LICENSE.md).
