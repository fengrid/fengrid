# Development

Everything you need to understand and work on the Fengrid.

> **Project status:** this is a casual side project. It exists to scratch an
> itch — "what icons do I actually have, and what are they called?" — and
> there is no roadmap, no plan to grow it into a framework, and no ambition
> beyond being a good single-purpose tool. If it works for you, great. If
> you want to improve it, contributions are genuinely welcome: keep changes
> focused, match the existing code style, and test with both a real icon
> theme set and an empty one.

## Structure

```
fengrid/                 # repo name; originally gtk4-icon-browser
├── index.html                # the entire application (HTML + CSS + JS, inline)
├── install.sh                # installer / uninstaller / launcher (Linux + macOS)
├── install.ps1               # installer / uninstaller / launcher (Windows)
├── server/                   # optional LAN webshare
│   ├── serve.py              # small http server (python3, stdlib only)
│   ├── connect.html          # QR connect page (vendored QR lib)
│   └── vendor/qrcode.min.js  # qrcode-generator 1.4.4 (MIT)
├── list.txt                  # generated: one path per icon file (gitignored)
├── list.js                   # generated: list.txt mirrored as JS array (gitignored)
├── fonts/                    # subset WOFF2 faces + their licenses (committed)
├── docs/                     # GitHub Pages landing page (NOT the showcase itself)
├── README.md / QUICKSTART.md / DEVELOPMENT.md / LICENSE.md
└── icons -> /usr/share/icons # dev-only symlink (gitignored)
```

## Branches

- `main` — stable, released versions (tagged, semver)
- `dev` — active development; features land here first and are merged to
  `main` at release time
- `gh-pages` — the static project landing page served by GitHub Pages
- `dev-gh-pages` — the landing page preview matching `dev` ( branched off
  `gh-pages`, updated independently until merged)

## How it works

### Data flow

1. The installer scans one or more **icon roots** with
   `find <root> -type f \( -name '*.png' -o -name '*.svg' -o -name '*.icns|xpm' \)`
   (parenthesized — the unparenthesized form mis-parses due to `-o`
   precedence) plus any user-supplied folders, into `list.txt`
   (one absolute path per line, forward slashes everywhere).
2. The list is mirrored into `list.js` as `window.ICON_LIST = [...]`.
   The page tries `fetch('list.txt')` first (works over http), then falls
   back to the `<script src="list.js">` payload — browsers block `fetch()`
   on `file://` pages, but not script tags.
3. The installer copies every listed icon into `<install>/icons/<theme>/...`
   and **rewrites converted entries** (.icns/.xpm → .png) so the page's
   relative paths always resolve. The page references icons as
   `icons/<theme>/...` in every mode, because Firefox forbids a `file://`
   page from reading files outside its own directory tree (Chromium
   allows it). A one-time error retry tries the absolute system path.

### Format handling per platform

| Platform | Native browser formats | Converted at install | Converter |
|----------|------------------------|----------------------|-----------|
| Linux    | svg, png               | xpm → png            | ImageMagick (`magick`/`convert`); without it, .xpm entries are dropped with a warning |
| macOS    | svg, png               | icns → png           | built-in `sips` |
| Windows  | png, svg, ico          | — (none needed)      | — |

### Parsing (`parseLine` in index.html)

Each line is decomposed into theme, context, size, and name:

- if the path contains `/icons/`, theme = the segment after it (theme-style
  layouts like `/usr/share/icons/<theme>/<size>/<context>/file`)
- otherwise theme = the parent directory name (arbitrary folders)
- size = `16x16`-style directory (hiDPI `@2` honored) or `scalable`
- context = the directory inside the size dir; flat icons are tagged
  `uncategorized`
- icons are grouped by `theme | context | name` so `foo.png`, `foo.svg`,
  and `foo-symbolic.svg` appear as separate entries, while `foo/16x16`,
  `foo/32x32`, … collapse into one card with its size variants

### Variant selection

For a target preview size, the variant whose pixel size is closest wins;
at exact-size matches a raster is preferred over SVG (+1.5 penalty on SVG
score) since a 16px SVG stretched into a 32px box looks worse than the
native 32px raster. `object-fit: contain` scales whatever is chosen to the
slider's size.

### Rendering & mobile

Plain ES5-flavored DOM building — no framework. The grid renders in chunks
of 240 cards behind an `IntersectionObserver` sentinel so a 1,000+ icon
theme stays responsive. Everything user-visible escapes through `esc()`
before any `innerHTML` use.

Mobile support: below 720px the controls stack full-width with 44px touch
targets, the theme chips become a horizontal swipe rail, the inspector
loses the path column, and on `hover: none` devices the copy buttons are
always visible and a tap selects a card (highlights it and populates the
inspector) until you tap elsewhere.

### Styling

Design tokens are CSS custom properties under `[data-theme="dark"]` and
`[data-theme="light"]`. Fonts are subset WOFF2 files loaded via
`@font-face` from `fonts/` — no CDN, so the page works fully offline:

- Inter — headings and UI (geometric-grotesque per brand)
- Iosevka (Mono) — all icon text, labels, buttons
- Inter — body text

User preferences (theme, size, sort, filter) persist in `localStorage`
under `gib-*` keys.

## The installers

Both are deliberately conservative:

- **Never privileged**; the only `sudo` use is the optional icon-theme
  package install on Linux, behind explicit consent
- Installs to `~/fengrid` by default (visible — sandboxed browsers
  are kept away from hidden dirs); custom locations allowed,
  hidden/root-owned paths require a second confirmation
- The launcher (`~/.local/bin/fengrid` on Linux/macOS, `fengrid.cmd`
  on Windows) is a tiny **script** that opens the *real* install path —
  not a symlink to the HTML: browsers keep the symlink's own URL, which
  would resolve page-relative assets under the launcher folder and break
- `--uninstall` / `-Uninstall` asks per location, knows all historical
  install locations, removes only launchers it created, refuses dirs that
  don't look like an install, and protects the running repository

Two bash traps worth knowing if you touch `install.sh` (both were hit and
fixed here): a `~` inside a parameter-expansion pattern (as in `${s#~/}`)
undergoes tilde expansion itself, and `> symlink` writes *through* the
link into its target.

## LAN webshare (`server/`)

`serve.py` is ~150 lines of Python stdlib (no pip installs):

- serves the install directory; `/_connect` renders `connect.html` with the
  LAN URL injected, which the vendored `qrcode-generator` library turns
  into a QR code (SVG, in-browser — no server-side image deps)
- **CORS / security posture**: the showcase never makes cross-origin
  requests — the page, `icons/`, and data files are all same-origin — so no
  CORS headers are needed and none are added. Directory listings are
  disabled. Security headers: `X-Content-Type-Options: nosniff`, and
  `Cache-Control: no-store` on the connect page. The listener binds
  `0.0.0.0` so other devices can connect (use `--host 127.0.0.1` for
  local-only); only share on networks you trust
- `connect.html` prefers the address-bar origin (reachable by definition)
  and only falls back to the server-injected LAN URL when opened from a
  loopback address — so the QR always encodes something a phone can open

On Windows the same goal is reached with `python serve.py` if Python is
installed; no PowerShell-native server is provided in this release.

## Versioning & releases

Standard [semantic versioning](https://semver.org/) — `MAJOR.MINOR.PATCH`:

| Bump | When |
|------|------|
| MAJOR | breaking changes: data format, launcher behavior, or anything that breaks an existing install/upgrade path |
| MINOR | new features that stay backward-compatible (new filters, new display modes) |
| PATCH | bug fixes, styling corrections, doc-only changes |

Release procedure:

```bash
# 1. update APP_VERSION in index.html (and the README/docs badges if desired)
# 2. commit
git commit -m "Release v0.1.0"
# 3. tag and push
git tag -a v0.1.0 -m "v0.1.0: short summary"
git push origin main --follow-tags
# 4. create the GitHub release from the tag, summarizing changes
```

Tags are always `v`-prefixed (`v0.0.1`). The version constant lives in
`index.html` as `APP_VERSION` and is displayed in the header, linked to the
[releases page](https://github.com/fengrid/fengrid/releases).
While on `dev`, the constant carries a `-dev` suffix.

## Automatic updates

`update.sh` (also installed as `~/.local/bin/fengrid-update`) checks the
latest release tag on GitHub and applies it in place — it never needs
credentials (uses `git ls-remote`, no API), never downgrades a dev build, and
refreshes your icon list from the scan paths recorded at install time
(`~/.local/state/fengrid/update.conf`). Run it manually with `--check`
to just report. The installer can register a **weekly cron job**
(Mondays 04:17, logged to `~/.local/state/fengrid/update.log`) via the
interactive prompt or `bash install.sh --automatic-updates`; `--uninstall`
removes both.

## Manual icon additions

`refresh-icons.sh` (installed both inside the install directory and as
`~/.local/bin/fengrid-refresh`) reconciles `list.txt`/`list.js` with the
install's `icons/` folder: it re-locates loose files into `icons/Manual/`,
converts `.icns`/`.xpm` when `sips`/ImageMagick is available, appends files
whose relative path is not already covered by a scanned entry (theme icons
are listed via their system paths and rendered from the local copy, so
re-listing the copies would duplicate them), prunes entries for deleted
files, regenerates `list.js`, and rebuilds `meta.js`. `update.sh` calls it
with `--merge-list` after its own re-scan so manual additions survive
updates.

## Image metadata (meta.js)

`icon-meta.sh` runs ImageMagick `identify` across the install's raster icons
and writes `meta.js` (`window.ICON_META`) — true pixel dimensions, file size,
colorspace, unique-color count and a monochrome flag per file. The page uses
it for the hover-details specs (dims/file/space/colors), the color/mono
**TONE** filter, and the richer variant display.

The scan is **incremental and fingerprint-tracked**: every file's size and
mtime (a cheap stand-in for a content hash) is kept in
`<install>/meta-state.tsv` along with the JSON fragment it produced, so
unchanged files are never re-identified. Each run compares fingerprints,
identifies only new/changed files, reuses stored fragments for the rest,
drops entries for deleted files, and rewrites `meta.js` and the ledger
atomically (temp files, swapped in at the end — Ctrl-C leaves the previous
state intact). SVG files are skipped by design (identify rasterizes them
through slow delegates; the page already knows a vector source from the
filename).

All entry-point scripts accept `--update-metadata enabled|disabled|force`:

- `enabled` (default) — compare fingerprints, identify only new/changed files
- `disabled` — skip metadata work entirely; `meta.js` left untouched
- `force` — ignore fingerprints, re-identify every icon

`install.sh` runs metadata enabled by default and records the chosen mode as
`UPDATE_META_MODE` in `update.conf` (the weekly updater and `update.sh
--update-metadata` override it). `scan-icons.sh` takes the option with
`--dir`. Large runs print a warning before starting. Without ImageMagick the
page falls back to filename-derived specs and the tone filter shows nothing
additional.

## Export endpoint (server/serve.py)

Every icon preview carries an export button (top-left, opposite the copy
button) that opens a compact format/size sub-menu; "more formats &
options…" opens the full export dialog. Over http, exports convert icons
through `GET /convert?src=&fmt=&size=` — a strictly validated whitelisted
endpoint that shells out to ImageMagick (PNG/JPEG/WebP/ICO/PDF/GIF/TIFF/BMP;
`ico` bundles 16–64 px frames; `size` resizes, `orig` passes the file
through; `src` must be the `icons/`-prefixed relative path). On `file://`
pages the browser rebuilds PNG/JPEG/WebP via canvas and falls back to
saving the original file for other formats.

## Refresh endpoint (server/serve.py)

`GET /refresh?mode=enabled|force` runs the install's `refresh-icons.sh` and
`icon-meta.sh` — the server-side engine behind the UI's refresh button
(plain click sends `enabled`, Shift-click sends `force`). One refresh runs
at a time (HTTP 409 when busy); the JSON reply carries a summary the page
toasts before reloading. On `file://` pages there is no server: the CLI
(`fengrid-refresh`) is the way to refresh. The `fengrid` launcher makes
this rare — it starts `serve.py --host 127.0.0.1 --kill-existing` in the
background (log: `~/.local/state/fengrid/server.log`) and opens the page
over `http://127.0.0.1:8642/`; `fengrid --file` opts out. The loopback
bind keeps the launcher's server invisible to the LAN (unlike the QR
webshare, which binds `0.0.0.0` on request). CORS stays refused by
design, so a `file://`-opened page still cannot drive the server.

## Testing

No test framework — verification is manual, and the minimum bar is:

1. `bash -n install.sh` passes
2. Full install run completes; `index.html` renders 0 console errors,
   0 broken images (check in both a Chromium-family and a Firefox browser —
   their `file://` policies differ, and that difference drove several
   design decisions)
3. Search, size slider, theme chips, sort, hover/tap inspector, copy
   button, and light/dark toggle all work
4. `serve.py` starts, `/_connect` renders the QR, and the URL it encodes
   opens the showcase
5. `--uninstall` removes what it created and refuses what it didn't

Serve locally for testing with
`python3 -m http.server 8642` (needs the generated `list.txt`/`list.js`
and either the copied `icons/` tree or the `icons` symlink to
`/usr/share/icons`).

## Docs site

`docs/index.html` is the GitHub Pages **project landing page** — a static
introduction with links to the repo, docs, and releases. It is not the
showcase itself; the showcase only makes sense with your local icons, so
it lives behind the installer. The landing page reuses the same fonts and
palette for a consistent look. The `dev-gh-pages` branch previews the
landing page matching `dev`.