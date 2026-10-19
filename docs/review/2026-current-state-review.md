# Fengrid — current-state review (pre-Qt rewrite)

- **Date:** 2026-10-18
- **Base reviewed:** `dev` @ `ccb4f1e` (branch `dev-qt` created from here)
- **Method:** static source read on this branch. Nothing was executed in this pass; where evidence comes from the earlier sandbox install (`/tmp/ib-sp/fengrid`) or the social-preview capture session, it is marked as such. Anything inferred rather than read is marked *inferred*.
- **Line numbers** refer to files at `ccb4f1e`.

---

## 1. Verified inventory

### 1.1 Scale snapshot

| File | Lines | Role |
|---|---:|---|
| `index.html` | 2,404 | Icons pane — original single-file app |
| `fonts.html` | 1,045 | Fonts pane — family-grouped browser |
| `code.html` | 962 | Code pane — HTML/CSS/JS playground |
| `projects.html` | 858 | Projects pane — coordinator + export |
| `colors.html` | 659 | Colors pane — palette generator |
| `server/serve.py` | 1,467 | Optional LAN server + REST API |
| **Total frontend** | **5,928** | five single-file frontends sharing a hand-copied design system |

### 1.2 Icons pane (`index.html`)

- Title/meta: `fengrid — the UI asset explorer`; description covers "icons, fonts, code snippets, and color palettes" (`index.html:6-7`).
- Favicon is the glint-quad brand mark as an inline SVG data URI (`index.html:8`).
- Dark theme default: `data-theme="dark"` (`index.html:2`), toggle button swaps to light.
- Fonts are **self-hosted** — `@font-face` for Inter + Iosevka subset to Latin WOFF2, explicitly "no CDN required" (`index.html:10-12`). Verified: **zero** `googleapis`/`gstatic` matches across all five panes on this tip. (A Google Fonts preconnect was observed on an older branch state earlier this session — resolved since.)
- Persistence: `localStorage` under `gib-*` — verified keys: `gib-sort`, `gib-context`, `gib-ext`, `gib-tone`, `gib-tag`, `gib-coll`, `gib-panel`, `gib-size`, `gib-exp-size` (`index.html:1340-1422`, `:1913`, `:2090-2091`). Tags/collections live here — per-browser, lost on cache clear.
- Version: `var APP_VERSION = 'v0.3.1'; // keep in sync with the latest git tag` (`index.html:883`) — synced by hand against the landing-page pill.

### 1.3 Panes (scope-expanded frontends)

- **Fonts** — family-grouped grid with regular-face previews, alphabetical Families navigator with scrollIntoView + flash, family-based selection/export; metadata via `fc-scan`; materializes `fonts/<Family>/<file>` next to the page (copy, or `--link` symlink mode added at `e520554`); `font-meta.js` loaded over http with no-cache (merge `2b34a49`, commit `0c1e24b`).
- **Code** — JSFiddle-style playground: tabbed HTML/CSS/JS editors, live Result iframe (Run ▸ / Ctrl+Enter), persistence to SQLite (`snippets.db`), taxonomy sidebar with search/sort/tag cloud, Export HTML standalone; endpoints `GET/POST /api/snippets`, `GET/PUT/DELETE /api/snippets/<id>`, `GET /api/tags` (`CHANGELOG.md:43-49`); IDE-grade editor bindings (`CHANGELOG.md:50+`).
- **Colors** — palette generator in the coolors mold: five swatches, harmony rules (pleasing mix, analogous, complementary, triadic, monochrome), spacebar reroll of unlocked swatches, per-swatch lock/remove/reorder, HSL/hex editor, WCAG contrast readouts vs white and black; palettes saved to SQLite with tags; exports: CSS custom properties, JSON, palette-board images (SVG + 2× PNG) (`CHANGELOG.md:33-42`).
- **Projects** — coordinator: collect icons/fonts/snippets/palettes into named projects (SQLite-backed; assets belong to any number of projects); spec panel (CSS class prefix, icon size, background/ink/accent colors) with live preview; export `.zip`/`.tar.gz` producing `assets/`, `css/colors.css`, `css/fonts.css`, `css/icons.css`, `js/icons.js`, demo `index.html`, `palettes.json`, `manifest.json`, README; `POST /api/projects/<id>/export` (`CHANGELOG.md:23-32`).
- **Snippet import** — VSCode `.code-snippets` / per-language `.json` (JSONC-tolerant) and massCode `db.sqlite`, mapped onto fengrid's HTML/CSS/JS fields; unmapped languages land in the JS pane with a `lang:<name>` tag; dedupe on title+body; `GET/POST /api/snippets/import?kind=vscode|masscode` (`CHANGELOG.md:11-22`).

### 1.4 Server (optional LAN share + REST API)

`server/serve.py` — 1,467 lines. It is no longer a static file server; it has become the app's de-facto service layer:

- Endpoints (verified in source): `/convert`, `/refresh`, `/import`, `/fonts-export`, `/api/*`, `/server-state.js` (no-store), `/_connect` (QR page); `/vendor/*` from the server dir for the connect page (`serve.py:104-153`).
- `/convert` security posture is careful: `src` regex-validated relative to `icons/` with traversal rejection, extension whitelist, format whitelist, size clamped 8–1024, and ImageMagick invoked via argv — never through a shell (`serve.py:169-220`).
- Cache discipline: `NO_CACHE_FILES = {list.txt, list.js, fonts-list.txt, font-meta.js, meta.js}` get `Cache-Control: no-cache`; everything else revalidates (`serve.py:93-102`).
- Network: binds `0.0.0.0` by default for LAN reach; the launcher path passes `--host 127.0.0.1` (`serve.py:15-17`). No CORS headers by design.
- Sibling service modules: `server/import_engine.py`, `server/snippet_import.py`; `sqlite3` is already imported (`serve.py:36`) — the SQLite migration has started inside the server.

### 1.5 Shell plumbing

- `refresh-icons.sh` (178 lines): reconciles `icons/` with the list — relocates loose files into `icons/Manual/`, converts `.icns`→png (macOS `sips`) and `.xpm`→png (ImageMagick), merges/prunes `list.txt`, regenerates `list.js`; `--merge-list` is the weekly-updater re-scan path (`refresh-icons.sh:19-22`); install dir default `~/fengrid` via `FENGRID_DIR` (`:33`).
- `icon-meta.sh` (226 lines): incremental metadata — fingerprint = size+mtime; emits `meta.js` (`window.ICON_META`: size, true pixel dims, colorspace, color count, mono flag) from the `meta-state.tsv` ledger; SVGs deliberately skipped; ImageMagick `identify`; atomic temp-file replace; INT/TERM-safe; GNU/BSD `stat` portability (`:90-93`).
- `scan-icons.sh` (180 lines): platform candidate roots — Linux: `/usr/share/icons`, `/usr/local/share/icons`, `~/.icons`, `~/.local/share/icons`, `/usr/share/pixmaps`, snap + flatpak mounts; macOS: CoreTypes bundle, `~/Library/Icons`, etc. (`scan-icons.sh:59-77`); `--list`/`--pick` flows; nested candidates folded into parents; timeout guard for slow mounts.
- `scan-fonts.sh` (255 lines): folder list persisted in `~/.local/state/fengrid/font-dirs.conf`; metadata via `fc-scan` with filename fallback; materializes into `fonts/<Family>/<file>` (copy, or `--link` symlink); `FONT_EXTS`: ttf/otf/woff/woff2/ttc/eot (`scan-fonts.sh:43`).
- `update.sh` (200 lines): cron-driven weekly updater — reads `APP_VERSION` from the installed `index.html` (`:72`), checks the newest tag via `git ls-remote` (no API, no credentials, no rate limits — `:10-12`), downloads the release tarball, replaces `index.html`/`fonts/`/`server/`, preserves user state in `~/.local/state/fengrid/update.conf` (legacy icon-browser config migrated, `:40-42`); `REPO_BASE = https://github.com/fengrid/fengrid` (`:36`); tracks release tags on `main` only.
- `install.sh` / `install.ps1`: three-OS installers; the Windows script runs under `-ExecutionPolicy Bypass` (documented as installer-process-only). NSIS installer work is parked on the `build-win-x64` branch (`c464dc3`: "fix(windows): NSIS config page missing the icon-folder listbox").
- `IDEA.md`: the original brief. Notable constraints worth remembering: launcher must not symlink the HTML directly (browsers keep the symlink's own URL and break page-relative assets, `IDEA.md:27`); install location must NOT be hidden because snap/flatpak browsers are sandboxed away from `~/.local` (`IDEA.md:24`); original heading font was Bebas Neue (`IDEA.md:6`) — superseded by the Inter-based brand identity.

### 1.6 Data plane (the generated-data plumbing)

`list.txt` → `list.js` (the `file://` fallback payload), `meta.js` + `meta-state.tsv` ledger, `fonts-list.txt` + `font-meta.js`, and the `icons/` copy itself. In the sandbox install used for the social-preview session, `icons/` held **914 files / ~5.7 MB** copied next to `index.html` — existing solely so previews work over `file://` (Firefox blocks cross-directory file loads).

### 1.7 Branding (complete)

`branding/` — glint-quad mark (dark/light/mono SVGs), favicon glyph set (7 PNG sizes + SVG), wordmark lockups (Inter + Noto Sans Mono), OG banner (1200×630), GitHub social preview (1280×640, built from real app screenshots), palette reference sheet, AI hero illustration (decorative), three finalist name packages + decision README. Identity: dark `#101418` base, teal `#39B8C4`, amber `#F5C25C`; Inter UI + Noto Sans Mono accents.

### 1.8 Engineering hygiene

- **No dependency manifest** anywhere (no `package.json`, `pyproject.toml`, `requirements.txt`) — the 0.x app is intentionally zero-dependency; this becomes a gap the moment Python enters the picture.
- **No test framework** — verification is the manual sandbox-install pattern (`printf '\n\nn\n' | bash install.sh --no-shell`) plus browser-harness checks, documented in the project skill. The skill's `references/shell-pitfalls.md` exists specifically because of real quoting/trap bugs hit while writing the shell plumbing.
- Branch topology is disciplined (`main` releases, `dev` feature work, `dev-gh-pages` → `gh-pages` landing) but everything above `gh-pages` is manual.

---

## 2. Improvement notes (evidence → disposition)

Each item: finding, evidence, and disposition — **quick-win** (worth fixing in 0.x regardless of the rewrite) vs **rewrite-scope** (resolved by the Qt plan; don't invest in 0.x).

1. **`icons/` duplication is a `file://` workaround.** ~914 files / ~5.7 MB copied per install purely because browsers block cross-directory `file://` loads. **rewrite-scope** — a `fengrid-asset://` URL scheme serving the original system paths eliminates the copy entirely.
2. **Two persistence stories.** The icons pane keeps tags/collections in `localStorage` (per-browser, lost on cache clear, no backup), while colors/code/projects already persist in SQLite through the server. Two sources of truth, no unified export. **rewrite-scope** — one SQLite core; **quick-win** companion: a JSON export/import for `gib-*` keys so 0.x users can migrate their tags.
3. **The data plane is shell-generated.** `list.txt`→`list.js` via `find`, `meta.js` via `icon-meta.sh` ledger, `fonts-list.txt`/`font-meta.js` via `scan-fonts.sh`. No error surfacing, fragile quoting (the skill's own `references/shell-pitfalls.md` exists because of real bugs here), full re-scan cost on some paths. **rewrite-scope** — watchdog-driven indexer writing SQLite.
4. **Export requires the optional LAN server + ImageMagick.** A desktop tool whose export pipeline only works while `serve.py` is running is architecturally inverted. **rewrite-scope** — native export in the core (Pillow for rasters; SVG→raster via resvg/cairo). Note the `.xpm` gap: Pillow has no XPM path, so keep ImageMagick as an optional fallback if XPM parity matters (open question for the user).
5. **Monolith frontends.** 5,928 lines across five single-file pages sharing a hand-copied design system; no modules, no build step, no tests. **rewrite-scope** (this plan exists because of this item).
6. **Version duplication.** `APP_VERSION = 'v0.3.1'` in the app JS (`index.html:883`) with a "keep in sync" comment, the landing pill synced by hand (skill release step 5), and tags. **quick-win** — single `VERSION` file consumed by build + docs.
7. **Updater is cron + shell.** Works, but it's three moving parts (cron entry, `update.sh`, state conf). **rewrite-scope** — in-app release check. Keep the `git ls-remote` tag probe (`update.sh:10-12`): no API, no credentials, no rate limits — that idea is worth porting.
8. **No tests, lint, or CI for the 0.x app.** **quick-win** — pytest smoke tests + `ruff` (the drafted dev build variant already ships both in `build/requirements-dev.txt`) + `node --check` on extracted inline JS.
9. **No persistent thumbnail cache.** Metadata is re-derived per install; large sets re-pay rendering cost. **rewrite-scope** — disk thumbnail cache keyed by content hash (the size+mtime fingerprint in `icon-meta.sh` is a cheap stand-in for a real content hash — **quick-win** to upgrade the fingerprint to xxhash even in 0.x).
10. **Accessibility gaps.** Keyboard navigation beyond `/`, focus visibility, and dark-mode monochrome contrast (flagged during the social-preview QA). **quick-win** partial in 0.x; **rewrite-scope** for a full pass.
11. **Windows distribution.** `-ExecutionPolicy Bypass` + unsigned artifacts; NSIS work parked on a side branch. **quick-win** — fold the NSIS work into the pipeline; **rewrite-scope** — code signing/notarization.
12. **`serve.py` is becoming a second application.** 1,467 lines with import engine, snippet import, and projects-export APIs. The service boundary the Qt rewrite needs already exists — inside an HTTP server. **rewrite-scope** — lift these into core services consumed directly by the Qt app; the HTTP share shrinks back to read-only webshare.

**Checked and clean:** fonts are fully self-hosted on this tip (zero CDN references across all five panes — verified by grep, `index.html:10-12`); no Electron/web-framework references anywhere; the server's `/convert` validation is solid enough to port almost as-is.

---

## 3. Feature parity baseline (carries into `0001-qt6-rewrite.md`)

| # | Feature | Where today | Parity priority |
|---|---|---|---|
| 1 | Multi-source icon scanning (platform roots incl. snap/flatpak/CoreTypes) | `scan-icons.sh` | P1 |
| 2 | Icon grid, 16–256 size slider snapping to standard sizes | `index.html` | P1 |
| 3 | Search + filters (name, tags, source, context, file type, color-vs-mono) | `index.html` | P1 |
| 4 | Tags & collections (user-defined, per-browser) | `index.html` localStorage | P1 |
| 5 | Inspector (name, theme, context, dims, size variants, file size, colorspace, color count, path) | `index.html` | P1 |
| 6 | One-click name copy | `index.html` | P1 |
| 7 | Export PNG/JPEG/WebP/ICO/PDF/GIF/TIFF/BMP at any size | `/convert` + ImageMagick | P2 |
| 8 | `.icns`/`.xpm` conversion | `sips` / ImageMagick | P2 |
| 9 | Fonts: family grouping, navigator, family selection/export, `--link` mode | `fonts.html` + `scan-fonts.sh` | P2 |
| 10 | Colors: harmony generator, WCAG readouts, CSS/JSON/board exports | `colors.html` | P3 |
| 11 | Code playground: editors + live preview + snippet library | `code.html` | P3 |
| 12 | Snippet import (VSCode, massCode) | `server/snippet_import.py` | P3 |
| 13 | Projects: coordinator, spec panel, token-based archive export | `projects.html` + import engine | P4 |
| 14 | QR LAN webshare (phone browsing) | `serve.py` + `/_connect` | P5 |
| 15 | Offline / zero-cloud operation | everywhere | P0 (design constraint) |
| 16 | Light/dark themes | `data-theme` toggle | P0 |
| 17 | Weekly update check | `update.sh` + cron | P5 |
| 18 | Three-OS install | `install.sh` / `install.ps1` | P6 |
| 19 | Mobile-friendly layout | webshare UI | P5+ |
| 20 | Help guides per pane | merge `2b34a49` | per-pane phase |

---

## 4. Open questions for the user

1. **QR LAN webshare in the Qt app** — build it into v1 (milestone M5) or keep the 0.x server as the phone path indefinitely?
2. **`.xpm` support** — keep via an optional ImageMagick fallback, or drop XPM from the Qt app?
3. **IDE bindings** (Code pane, `CHANGELOG.md:50+`) — full parity in the Qt editor, or read-only highlight first?
4. **Windows ARM64** — acceptable to defer if PySide6 wheels remain unavailable (the drafted pipeline fails fast with an explanation)?
5. **Heading font** — `IDEA.md` specified Bebas Neue; the brand identity uses Inter. Confirm Inter for QML headings so the original brief is formally superseded.
