# Changelog

All notable changes to this project are documented in this file. Format is
based on [Keep a Changelog](https://keepachangelog.com/), and this project
adheres to [Semantic Versioning](https://semver.org/).

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