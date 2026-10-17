# Development

Everything you need to understand and work on the GTK4 Icon Browser.

> **Project status:** this is a casual side project. It exists to scratch an
> itch — "what icons do I actually have, and what are they called?" — and
> there is no roadmap, no plan to grow it into a framework, and no ambition
> beyond being a good single-purpose tool. If it works for you, great. If
> you want to improve it, contributions are genuinely welcome: keep changes
> focused, match the existing code style, and test with both a real icon
> theme set and an empty one.

## Structure

```
gtk4-icon-browser/
├── index.html        # the entire application (HTML + CSS + JS, inline)
├── install.sh        # installer / uninstaller / launcher
├── list.txt          # generated: one absolute path per icon file (gitignored)
├── list.js           # generated: list.txt mirrored as a JS array (gitignored)
├── fonts/            # subset WOFF2 faces + their licenses (committed)
├── docs/             # GitHub Pages landing page (NOT the showcase itself)
│   ├── index.html
│   └── assets/screenshot.png
├── IDEA.md           # original design brief / spec
├── README.md
├── QUICKSTART.md
├── DEVELOPMENT.md    # this file
└── LICENSE.md        # MIT + bundled font licenses
```

## How it works

### Data flow

1. `install.sh` runs the canonical scan —
   `find /usr/share/icons -type f \( -name '*.png' -o -name '*.svg' -o -name '*.xpm' \)`
   (parenthesized; the unparenthesized form mis-parses due to `-o`
   precedence) — plus any user-supplied extra paths, into `list.txt`.
2. The same list is mirrored into `list.js` as
   `window.ICON_LIST = [...]`. The page tries `fetch('list.txt')` first
   (works over http), and falls back to the `<script src="list.js">`
   payload when `fetch` is unavailable — browsers block `fetch()` on
   `file://` pages, but not script tags.
3. `install.sh` also copies every listed icon file into
   `<install>/icons/<theme>/...`, mirroring the on-disk layout. The page
   then references icons with **relative** paths (`icons/Adwaita/...`) in
   every mode, because Firefox forbids a `file://` page from reading files
   outside its own directory tree (Chromium allows it). A one-time error
   retry falls back to the absolute system path for setups without the
   local copy.

### Parsing (`parseLine` in index.html)

Each line is decomposed into theme, context, size, and name:

- theme = path segment after the first `/icons/`
- size = `16x16`-style directory (hiDPI `@2` honored) or `scalable`
- context = the directory inside the size dir (actions, devices, …);
  flat icons are tagged `uncategorized`
- icons are grouped by `theme | context | name` so `foo.png`, `foo.svg`,
  and `foo-symbolic.svg` appear as separate entries, while `foo/16x16`,
  `foo/32x32`, … collapse into one card with its size variants

### Variant selection

For a target preview size, the variant whose pixel size is closest wins;
at exact-size matches a raster is preferred over SVG (+1.5 penalty on SVG
score) since a 16px SVG stretched into a 32px box looks worse than the
native 32px raster. `object-fit: contain` scales whatever is chosen to the
slider's size.

### Rendering

Plain ES5-flavored DOM building — no framework. The grid renders in chunks
of 240 cards behind an `IntersectionObserver` sentinel so a 1,000+ icon
theme stays responsive. Everything user-visible escapes through `esc()`
before any `innerHTML` use.

### Styling

Design tokens are CSS custom properties under `[data-theme="dark"]` and
`[data-theme="light"]`. Fonts are subset WOFF2 files loaded via
`@font-face` from `fonts/` — no CDN, so the page works fully offline:

- Bebas Neue — headings (all-caps)
- Iosevka (Mono) — all icon text, labels, buttons
- Inter — body text

User preferences (theme, size, sort, filter) persist in `localStorage`
under `gib-*` keys.

## The installer

`install.sh` is deliberately conservative:

- **Never privileged** for its own actions; the only `sudo` use is the
  optional icon-theme package install, behind explicit consent
- Installs to `~/gtk4-icon-browser` by default (visible — Snap/Flatpak
  browsers are sandboxed away from `~/.local`); custom locations allowed,
  hidden/root-owned paths require a second confirmation
- The launcher at `~/.local/bin/gtk4-icon-browser` is a tiny **script**
  (`exec xdg-open <real-path>/index.html`), not a symlink to the HTML:
  browsers keep the symlink's own URL, which would resolve page-relative
  assets under `~/.local/bin/` and break them
- `--uninstall` / `--remove` asks per location, removes only launchers it
  created, refuses dirs that don't look like an install, and protects the
  running repository

Two bash traps worth knowing if you touch it (both were hit and fixed
here): a `~` inside a parameter-expansion pattern (as in `${s#~/}`)
undergoes tilde expansion itself, and `> symlink` writes *through* the
link into its target.

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

## Testing

No test framework — verification is manual, and the minimum bar is:

1. `bash -n install.sh` passes
2. Full install run completes; `index.html` renders 0 console errors,
   0 broken images (check in both a Chromium-family and a Firefox browser —
   their `file://` policies differ, and that difference drove several
   design decisions)
3. Search, size slider, theme chips, sort, hover inspector, copy button,
   and light/dark toggle all work
4. `--uninstall` removes what it created and refuses what it didn't

Serve locally for testing with
`python3 -m http.server 8642` (needs the generated `list.txt`/`list.js`
and either the copied `icons/` tree or the `icons` symlink to
`/usr/share/icons`).

## Docs site

`docs/index.html` is the GitHub Pages **project landing page** — a static
introduction with links to the repo, docs, and releases. It is not the
showcase itself; the showcase only makes sense with your local icons, so
it lives behind the installer. The landing page reuses the same fonts and
palette for a consistent look.
