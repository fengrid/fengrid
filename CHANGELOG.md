# Changelog

All notable changes to this project are documented in this file. Format is
based on [Keep a Changelog](https://keepachangelog.com/), and this project
adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- **Code playground (`code.html`)** — a JSFiddle-style pane for writing,
  previewing, and organizing HTML/CSS/JS snippets. Tabbed editors with
  lightweight syntax highlighting (no external dependencies — a
  regex tokenizer with private-use-area placeholders), a live Result
  iframe (Ctrl+Enter or Run ▸), and Save to a local SQLite database
  (`snippets.db`, created on first save). The taxonomy sidebar lists
  snippets with search, language filter, recent/title/created sorting,
  and a clickable tag cloud (tags with counts); Ctrl+S saves, and
  **Export HTML** downloads a standalone file. Served endpoints:
  `GET/POST /api/snippets`, `GET/PUT/DELETE /api/snippets/<id>`,
  `GET /api/tags`. Snippets persist across reinstalls only if
  `snippets.db` is kept — the uninstaller treats it as data and asks
  before deleting.
- **Color-coded modes** — each pane of the app now has its own accent
  derived from the brand palette: **Icons** stay teal (`#39B8C4` /
  `#0E7C86`), **Fonts** turn violet (`#A78BFA` / `#6D4FC4`), and
  **Code** is coral (`#F0885C` / `#C44A1E`). The wordmark, mode switch,
  buttons, chips, and focus rings all follow the pane's accent; the
  lit-pane amber remains the shared interaction accent everywhere.

### Fixed

- **Windows paths were dropped by the page's list parser** — `parseLine`
  rejected any `list.txt` line not starting with `/`, so Windows drive
  paths (`D:/Library/.../icon.png`) yielded zero icons. It now accepts
  drive paths, derives the relative path from the last two segments (a
  theme name recurring earlier in the path no longer corrupts it), and
  finds the size directory (`16x16`, `32x32@2`, `scalable`, …) anywhere
  in the path — previously the size dir was only detected when it
  directly followed `/icons/`, so theme-style layouts never got sizes
  and their context fell back to the theme name (contrary to the
  documented layout).
- **Windows launcher (`fengrid.cmd`) set an empty `APP_DIR`** — inside a
  PowerShell array literal the comma operator binds tighter than `+`, so
  the unparenthesized `'set "APP_DIR=' + $InstallDir + '"'` in
  `install.ps1` was parsed as three separate array elements and the
  generated launcher had `APP_DIR` split across three lines; the
  server-launch path could never work. The expression is now
  parenthesized.

- **Windows installer (`install.ps1`) rejects pasted paths** — entering
  `"D:\Library\Design Library\Icons"` (as produced by Explorer's *Copy as
  path* or PowerShell tab completion) failed the directory check even when
  the folder existed. Typed paths are now normalized: surrounding quotes
  and whitespace stripped, `~` expanded, and all user-supplied paths are
  checked with `-LiteralPath` so `[`/`]` in folder names no longer act as
  wildcards. The skip message now distinguishes "it is a file" from
  "directory not found".

### Added

- **Font showcase install step** — the installer now asks to scan font
  folders (default yes; `--fonts`/`--no-fonts` to control it
  non-interactively). Scanned fonts generate `fonts-list.txt` +
  `font-meta.js` for the font showcase. Custom font folders can be added
  at the prompt.
- **Font showcase** — the header's Icons / Fonts switch opens `fonts.html`,
  a sibling page with the same design system but wider grid cells and
  live typeface previews. Each card renders the preview text in its own
  font via a dynamically injected `@font-face` rule. Sort by name, weight,
  or style; filter by style (Regular/Bold/Italic/Other) and format
  (TTF/OTF/WOFF/WOFF2/TTC/EOT); customize the preview text and size.
  Select fonts via checkboxes, Shift-click range, or Ctrl-click toggle;
  export as CSS (`@font-face` rules) or ZIP (font files + fonts.css +
  README) via the new `POST /fonts-export` endpoint. Clicking a font name
  opens a detail modal with the typeface at six sizes, all installed
  variants of the same family, a full glyph specimen, and metadata.
  Font scanning via `scan-fonts.sh` (fc-scan for family/style/weight/
  slant; configurable folders persisted to `~/.local/state/fengrid/
  font-dirs.conf`). Metadata from fc-scan covers TTF/OTF/TTC; WOFF/WOFF2
  fall back to filename-derived family names.
- **Import icon sets** — a new folder-plus button in the title row opens an
  import modal with four sources: a local folder (browser picker or
  server-local path), a `.zip` archive, a git repository or archive URL
  (`.tar.gz`, `.7z`, …), and a live catalog of 200+ open-source icon sets
  from [fengrid/icon-sets](https://github.com/fengrid/icon-sets) with
  license and author shown per set. Every import lands in its own theme
  folder under `icons/` and is scanned for metadata automatically
  (`server/import_engine.py`; `GET/POST /import` in serve.py). Theme names
  are sanitised and de-duplicated; archive extraction is path-traversal
  safe; SVGs missing the `xmlns` namespace are patched on import so they
  render in `<img>` tags instead of showing as MISSING cards.
- **Icon storage modes (`--icons copy|link|hardlink`)** — copying all icons
  into `icons/` is still the default (fully self-contained), but the
  installer can now **symlink** each icon file to its original (no
  duplicated disk; edits to the originals appear immediately;
  `rm -rf` on uninstall removes only the links, never the system themes)
  or **hardlink** them (no extra disk on the same filesystem, silently
  falls back to a copy across devices). `fengrid-refresh` and
  `icon-meta.sh` are symlink-aware: linked files are enumerated, scanned,
  and fingerprinted exactly like real ones, and dangling links are
  dropped rather than breaking the scan. Windows: `install.ps1
  -IconMode hardlink` (per-file hardlinks, copy fallback on refusal).

### Fixed

- **Light-theme hover details were nearly invisible** — the details bar,
  DETAILS badge, and icon name used the lit-pane amber (`#F5B841`) as text
  on white (~1.8:1 contrast). Text now uses a daylight-darkened honey amber
  (`#A16207`, ~4.9:1, AA); bright amber is reserved for borders, outlines,
  underlines, and hovers. Text on amber fills (active format buttons, tag
  pills) uses dark ink in both themes. Dark theme is unchanged.
- **Loopback servers advertised a LAN URL** — a server started by the
  launcher (`--host 127.0.0.1`) reported the machine's LAN IP in
  `server-state.js`, so the QR button offered an unreachable address.
  Loopback servers now advertise `http://127.0.0.1:<port>/` and no LAN
  alternates.

### Changed

- **The LAN webshare is on by default** — the install prompt now reads
  `[Y/n]`, so a plain Enter (or a non-interactive install) exposes the
  showcase to the local network for QR sharing. `--no-webshare` keeps the
  server local-only; `--webshare` accepts without prompting. The server
  itself still only binds `0.0.0.0` when this option is taken — the
  launcher's everyday server remains loopback-only.
- **The local web server is the default, not an option** — both launchers
  (`fengrid` on Linux/macOS, `fengrid.cmd` on Windows) start `serve.py`
  bound to the loopback interface and open `http://127.0.0.1:8642/`,
  reusing a server already up on the port and falling back to the plain
  file when Python is unavailable (`fengrid --file` forces that). The
  install-time prompt now only opts into *exposing* the server to the
  local network (QR webshare).
- Windows installer robustness: `list.txt`/`list.js`/`fengrid.cmd` are
  written as UTF-8 (ASCII corrupted non-ASCII icon file names), `list.txt`
  is written next to the script instead of the caller's current directory
  (running `install.ps1 -File` from another directory used to break the
  install copy step), same-named icons from different scan roots are
  suffixed instead of silently overwriting each other, the system-owned
  location check compares SIDs instead of the localized
  `NT AUTHORITY\SYSTEM` name, a bare drive root (`D:\`) survives path
  normalization, and a failed auto-launch no longer aborts the install.

## [v0.3.1] — 2026-10-18

The project formerly known as GTK4 Icon Browser / Icon Browser is now
**fengrid** — *frontend grid*, with a hidden second reading: *fen* (window)
+ *grid*, a grid of windows onto your machine. New home:
[github.com/fengrid/fengrid](https://github.com/fengrid/fengrid).

### Added

- New split-screen **light/dark brand screenshot** (thin pane-teal divider,
  lit-pane mark in the corner strip) on the README and the landing page.

### Changed

- **New brand identity** — glass-and-daylight palette (pane teal accent,
  single warm "lit pane" highlight), Inter replaces Bebas Neue for the
  wordmark and headings, lowercase `fengrid` wordmark with `grid` set in
  mono, and a lit-pane favicon. The lit-pane accent now drives
  selection/hover/inspector-open states, so brand and interaction share one
  device.
- **New names for everything users touch** — install directory `~/fengrid`,
  commands `fengrid`, `fengrid-update`, `fengrid-refresh`, state directory
  `~/.local/state/fengrid`, PATH marker `# Fengrid`, cron marker
  `# fengrid weekly update`, and `FENGRID_DIR` as the environment override.
- **Repo moved** to `github.com/fengrid/fengrid`; the weekly updater now
  checks releases there.

### Compatibility

- **Pre-rebrand installs keep working.** The uninstaller recognizes and
  removes both generations (install dirs, launchers, PATH markers, cron
  entries, and helpers named `icon-browser*` and `fengrid*`). The updater
  prefers `fengrid-refresh` but falls back to `icon-browser-refresh`, and
  reads the legacy `~/.local/state/icon-browser/update.conf` when the new
  one is absent. `ICON_BROWSER_DIR` remains honored as a fallback for
  `FENGRID_DIR`.
- **Bebas Neue retired** — the font file was removed from `fonts/` (Inter,
  already bundled, takes over per the brand's typographic direction).

## [v0.2.3] — 2026-10-18

### Added

- **Phones start with the filter panel collapsed** — on mobile widths
  (≤ 720 px) the search/filter panel now begins minimized for a full-page
  icon grid on first visit. Expanding it with the sliders button saves the
  choice, so a visitor who prefers the panel open keeps it open across
  visits; clearing the preference returns to the collapsed default.
  Desktop layout is unchanged (the panel is always visible and the toggle
  button remains a mobile-only control).

### Changed

- **Documentation updated** — README, QUICKSTART and the in-app help modal
  now describe the collapsed-by-default mobile behavior and the remembered
  choice.

## [v0.2.2] — 2026-10-18

### Added

- **Export button on every icon preview** — a download button at each
  card's top-left corner (opposite the copy-name button) opens a compact
  sub-menu: pick a format (PNG, JPEG, WebP, ICO) and a size (16–256 px or
  original) and the export starts immediately. The size choice is shared
  with and remembered alongside the full export dialog. Because the button
  lives on the card itself, exporting no longer requires catching the
  hover-details bar before it disappears.
- **"More formats & options…"** in the same sub-menu opens the full export
  dialog pre-targeted at that icon, keeping PDF, GIF, TIFF, BMP and the
  original file reachable.

### Changed

- **Hover details trimmed** — the EXPORT button was removed from the
  details bar (it vanished whenever the mouse left the icon); TAG remains
  there. All exports now start from the per-card button.
- **In-app help & QUICKSTART updated** to walk through the new corner
  button, the sub-menu, and where the remaining formats live.

### Fixed

- **HTTP export was broken (400)** — the export request sent the bare
  relative path (`src=Adwaita/…`) while the `/convert` endpoint requires
  the `icons/`-prefixed path, so every http export failed regardless of
  entry point. The request now sends `src=icons/…`; verified end-to-end
  (menu export → `/convert` → 200).

## [v0.2.1] — 2026-10-18

### Added

- **Icon list refresh script** (`refresh-icons.sh`, also installed as
  `icon-browser-refresh`) — reconciles `list.txt`/`list.js` with the
  install's `icons/` folder after manual drops: re-locates loose files into
  a `Manual` theme, converts `.icns`/`.xpm` when `sips`/ImageMagick is
  available, adds only files not already covered by the scan, prunes deleted
  entries, and regenerates `list.js`. The weekly updater calls it after its
  own re-scan, so manual additions survive updates.
- **Rich hover details** — the details bar now shows true pixel dimensions,
  every available size variant (vector sources marked), file size,
  colorspace, unique-color count, and a monochrome chip, backed by
  `meta.js` (`window.ICON_META`) generated by the new `icon-meta.sh`
  (ImageMagick `identify`). The bar gains a complementary highlight accent
  (underlined icon name, accented border/label) and per-icon TAG and EXPORT
  buttons.
- **Export** — download any icon as PNG/JPEG/WebP/ICO/PDF/GIF/TIFF/BMP at
  16–512 px or original size. Served over http, conversions run through a
  new strictly-validated `/convert` endpoint in `serve.py` that shells out
  to ImageMagick (ICO exports bundle 16/24/32/48/64 px frames); on `file://`
  pages PNG/JPEG/WebP are rebuilt in the browser and other formats fall
  back to saving the original file.
- **Type & tone filters** — new TYPE dropdown (file extensions present in
  the grid) and TONE dropdown (color vs. monochrome, from the generated
  metadata).
- **Tags & collections** — tag icons with free-form tags, organize them
  into named collections, and filter/search by either (search matches tag
  names too). Stored per-browser in `localStorage`; managed from the TAG
  button in the details bar or the tag button in the title row.
- **Mobile filter collapse** — a sliders button in the title row (phone
  widths only) hides the whole search/filter section for a full-page grid;
  the choice persists.
- **UI refresh button** — re-scans `icons/` and refreshes metadata through
  a new `/refresh` endpoint in `serve.py` (Shift-click forces a full
  re-scan); the JSON reply is toasted and the page reloads. On `file://`
  pages it points at the CLI instead.
- **`--update-metadata` on all scripts** — `install.sh`, `scan-icons.sh`
  (with `--dir`), and `update.sh` accept `--update-metadata
  enabled|disabled|force`; installs run it enabled by default and record
  the choice for the weekly updater.

### Changed

- **Incremental metadata** — `icon-meta.sh` fingerprints every raster icon
  (size + mtime) in a `meta-state.tsv` ledger, so re-scans re-identify only
  new or changed files, reuse stored fragments for the rest, prune deleted
  files, and swap `meta.js` in atomically. Large runs warn before starting
  and Ctrl-C cancels safely. SVG files are skipped by design (the page
  knows a vector source from the filename).
- **Installer copy semantics** — `install.sh` now copies directory
  *contents* (`cp -r dir/. dest/`); the previous form nested a fresh copy
  under an existing `dest/server` / `dest/fonts` on re-install, silently
  leaving old files (like a stale `serve.py`) in place.
- **Landing page quickstart** — the install command is now a tabbed panel
  for Linux / macOS / Windows with non-invasive platform auto-detection
  and per-platform notes. Also fixes the previously broken one-liner
  (missing `cd gtk4-icon-browser`).
- **Uninstaller completion report** — ends with a summary of everything
  removed, kept, or skipped (installs, launcher, PATH entries, cron job,
  helpers, stopped servers) plus an explicit success line; if a web server
  was stopped, a note explains that any `Terminated` line from the shell
  refers to the server, not the script.

### Fixed

- **Uninstaller kill safety** — only actual python server processes are
  stopped; processes whose command line merely mentions `serve.py` and an
  install path (e.g. the shell running a compound command) are no longer
  matched.
- **Uninstaller server-stop confirmation** — after SIGTERM the script
  polls for the process to exit before reporting, so the summary is the
  script's last word.

## [v0.1.2] — 2026-10-17

### Added

- **Icon folder scanner** (`scan-icons.sh`) — discovers icon folders in
  common system locations (system theme dirs, `~/.icons`, `pixmaps`, snap
  and flatpak mounts; CoreTypes on macOS), filters empty and nested
  candidates, and offers an interactive selection menu. The installer's
  "Add more icon folders" step now uses it by default (manual entry still
  available), and generated icon lists are deduplicated so overlapping
  scan roots can't create double entries.
- **In-app help** — new header button opens a guide modal covering
  browsing, search/filter, details & copy, QR webshare, themes, keyboard
  shortcuts, and troubleshooting (port conflicts, Firefox `file://`
  policy, missing icons, updates). `Esc`/backdrop/✕ close it, and grid
  shortcuts no longer fire while a dialog is open.
- **Port-conflict handling** — `serve.py --kill-existing` stops stale
  server instances automatically; without it, a busy port now produces a
  clear error with recovery instructions instead of a raw
  `Address already in use` traceback.

### Fixed

- **Uninstaller now stops running web servers** — removing an install
  terminates its `serve.py` instance (matched by command line or working
  directory, including the kernel's ` (deleted)` cwd suffix for
  already-removed directories). Unrelated servers on other installs are
  left running.

## [v0.1.1] — 2026-10-17

### Added

- **Cross-platform support** — generalized from GTK-specific to any/all icon
  sets and common themes; works with any folder of icons. Added
  `install.ps1` for Windows and macOS support in `install.sh` (`.icns`
  conversion via `sips`, `.xpm` via ImageMagick).
- **Mobile-friendly layout** — responsive stacked controls, swipeable
  filter chips, 44px touch targets, tap-to-select inspector on touch
  devices.
- **QR webshare button** — new header button opens a modal showing a
  scannable QR code for the optional local web server, so the showcase can
  be opened on phones over the LAN.
- **Automatic weekly updates** — `update.sh` (also installed as
  `~/.local/bin/icon-browser-update`) checks GitHub release tags via
  `git ls-remote` (no API/credentials), downloads and installs newer
  releases in place, and refreshes the icon list from the scan paths
  recorded at install time. Enable via `bash install.sh
  --automatic-updates` or the interactive install step. `--uninstall`
  removes the crontab entry, updater, and config.
- **Robust hover inspector** — grid-level hover delegation (survives
  re-renders, covers every chunk), click/tap pins details on any device,
  and an explicit format/source-size field.
- **Server improvements** — `serve.py` now serves the web root correctly,
  persists `server-state.js` (LAN URL + alternate IPs) for file:// pages,
  and serves it fresh with no-store caching on an in-app-usable route.
- **Licensing** — `LICENSE.md` updated with third-party components:
  qrcode-generator v1.4.4 (MIT), Python standard library (PSF), and notes
  on optional runtime converters (sips, ImageMagick).

### Changed

- **Checkerboard previews** — transparency pattern behind icon previews is
  now barely visible (dark 0.045→0.02, light 0.04→0.018 opacity).
- Product references generalized from "GTK4 Icon Browser" to "Icon
  Browser" (the repository slug is unchanged).
- Security guidance resolved: documented the innerHTML usage as safe
  (library-generated markup + static strings only).
- Housekeeping: removed committed `__pycache__` from the repo, and ignored
  runtime-generated `server-state.js` (written at server startup, removed
  at shutdown).

## [v0.0.1] — 2026-10-17

Initial public release: single-file icon grid with search/filter/sort,
size slider, hover inspector, copy button, light/dark themes, and a
self-contained installer.