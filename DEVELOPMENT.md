# Development

Everything you need to understand and work on the Icon Browser.

> **Project status:** this is a casual side project. It exists to scratch an
> itch — "what icons do I actually have, and what are they called?" — and
> there is no roadmap, no plan to grow it into a framework, and no ambition
> beyond being a good single-purpose tool. If it works for you, great. If
> you want to improve it, contributions are genuinely welcome: keep changes
> focused, match the existing code style, and test with both a real icon
> theme set and an empty one.

## Structure

```
gtk4-icon-browser/            # repo name is historical; the tool is general
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

- Bebas Neue — headings (all-caps)
- Iosevka (Mono) — all icon text, labels, buttons
- Inter — body text

User preferences (theme, size, sort, filter) persist in `localStorage`
under `gib-*` keys.

## The installers

Both are deliberately conservative:

- **Never privileged**; the only `sudo` use is the optional icon-theme
  package install on Linux, behind explicit consent
- Installs to `~/icon-browser` by default (visible — sandboxed browsers
  are kept away from hidden dirs); custom locations allowed,
  hidden/root-owned paths require a second confirmation
- The launcher (`~/.local/bin/icon-browser` on Linux/macOS, `icon-browser.cmd`
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
[releases page](https://github.com/nativeit/gtk4-icon-browser/releases).
While on `dev`, the constant carries a `-dev` suffix.

## Automatic updates

`update.sh` (also installed as `~/.local/bin/icon-browser-update`) checks the
latest release tag on GitHub and applies it in place — it never needs
credentials (uses `git ls-remote`, no API), never downgrades a dev build, and
refreshes your icon list from the scan paths recorded at install time
(`~/.local/state/icon-browser/update.conf`). Run it manually with `--check`
to just report. The installer can register a **weekly cron job**
(Mondays 04:17, logged to `~/.local/state/icon-browser/update.log`) via the
interactive prompt or `bash install.sh --automatic-updates`; `--uninstall`
removes both.

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