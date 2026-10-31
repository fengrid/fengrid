# Quickstart

Get Fengrid running in about two minutes — on Linux, macOS or Windows.

## 1. Get it

**From a release** (recommended): grab
`fengrid-prod-linux-x64.tar.gz` (or arm64 / macOS / Windows) from the
releases page, unpack, and run the `fengrid` binary inside.

**From source:**

```bash
git clone https://github.com/fengrid/fengrid.git
cd fengrid/qt
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

## 2. Run

```bash
python -m fengrid        # from the qt/ directory (source install)
./fengrid                # packaged bundle
```

The first launch shows the setup screen: pick the icon roots and font
folders to index (system theme directories are pre-detected on Linux and
macOS), and you're in. Everything is local — the library is a SQLite
database under your data directory
(`~/.local/share/fengrid/library.db` on Linux), no account, no cloud.

## 3. The five panes

The icon rail on the left switches panes (`Ctrl+1`…`Ctrl+5`):

- **Icons** — type `/` to search, hover a card for the full inspector
  (dimensions, size variants, color count), click the download button for
  format/size export (PNG/JPEG/WebP/ICO, plus PDF/GIF/TIFF/BMP), tag
  freely, and build collections.
- **Fonts** — families grouped with live specimens; tick families and
  **Export CSS** (`@font-face` rules) or **Export ZIP** (files + CSS).
  Click a family for the specimen modal at multiple sizes.
- **Colors** — the spacebar rolls new palettes (locked swatches stay
  put), click a swatch for HSL sliders or hex input, save palettes with
  tags, export CSS custom properties, JSON, color-code lists
  (HEX/HSL/RGB/CMYK) or palette board images.
- **Code** — three editors (HTML/CSS/JS) with syntax highlighting, live
  preview (**Run ▸** / Ctrl+Enter), snippets saved to the library,
  VS Code and massCode import, emacs bindings and a **VIM** mode
  (Ctrl+Alt+V).
- **Projects** — the studio. Open a project to get the screen rail:
  **Design** (block canvas + live preview), **Theme** (token
  configurator), **Assets**, **Templates**, **Docker**, **Docs**;
  revisions live in the bottom dock. Ctrl+S saves — and commits to the
  project's `fengrid-main` branch.

## Importing assets

The upload button in each pane's toolbar ingests folders, zip archives
and individual files, with copy-or-link semantics, optional format
conversion, and renaming rules (prefix/suffix, regex find/replace,
cardinal enumeration, random names, GUIDs, or a CSV mapping) — configure
the defaults in **Settings → Import**.

Watch folders (Settings → Import & Watch) keep directories — local or
remote via rsync/scp/sftp/ftp/http — continuously synced into the
library.

### Sandbox and system folders excluded from scans

Fengrid deliberately ignores Flatpak, Snap, and other sandbox payload
trees when scanning for or importing assets — every installed sandboxed
app bundles its own private copy of the theme icons (under
`…/files/share/icons`), so indexing them floods the library with
thousands of redundant, unreadable, or stale duplicates and can stall
startup on busy systems. Excluded by default:

- `/snap/…`, `/var/lib/flatpak/…`, `/var/lib/snapd/…`
- `~/.local/share/flatpak/…`, `~/snap/…`, `~/.var/app/…`
- any directory named `snap`, `flatpak`, `squashfs-root`, or `appdir`
  found while walking a folder you add yourself

Importing files or folders from one of these locations is refused with a
clear error rather than silently indexed. If you genuinely need one of
these trees (e.g. you develop snap packages and want their assets
indexed for a project), set the environment variable
`FENGRID_ALLOW_SANDBOX=1` before launching Fengrid to disable every
sandbox exclusion.

## REST API

```bash
python -m api.v1 --db ~/.local/share/fengrid/library.db --port 8642
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8642/api/v1/inventory
```

Every library operation is scriptable: ingest, inventory, export,
collections, tags, projects, backups, watch folders, data-asset CRUD.
See `api/v1/openapi.yaml` or import `api/v1/postman_collection.json`
into Postman. The token is shown once when the server starts (or set
`FENGRID_API_TOKEN`).

## Backup & restore

Settings → Backup creates a single `*.tar.gz`: a manifest (version,
settings, environment, logs) plus full copies of the SQLite databases
and per-OS restore scripts. Restore onto a fresh machine with
`restore.sh` / `restore.ps1` from the archive — it downloads the same
release, refuses to run where Fengrid is installed or running, and
reports a clear error code if anything is off.

## Shortcuts worth knowing

| Keys | Action |
|------|--------|
| `/` | search |
| `Ctrl+1`…`Ctrl+5` | switch pane |
| `Ctrl+Z` / `Ctrl+Shift+Z` | undo / redo (pane-aware) |
| `Ctrl+K` (or the configured shortcut) | command palette |
| `Ctrl+Enter` | run the snippet preview |
| `Ctrl+S` | save (snippet / project) |

## Uninstall

Delete the unpacked bundle and, if you want a clean slate, the data
directory (`~/.local/share/fengrid`). Nothing is written outside the
bundle and the data directory.
