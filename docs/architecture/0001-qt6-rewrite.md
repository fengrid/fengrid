# ADR-0001 — Qt 6 bottom-up rewrite of Fengrid

- **Status:** accepted — M0/M1 implemented and validated on `dev-qt`
  (2026-10-19; see §17 validation record)
- **Supersedes:** nothing (this is the first architecture ADR)
- **Companion review:** `docs/review/2026-current-state-review.md`
- **Branch:** `dev-qt`

## 1. Purpose

Plan the bottom-up rewrite of Fengrid from five single-file HTML frontends plus
shell plumbing into a single native desktop application, using the feature set
of the 0.x app as the parity baseline. The trigger is the Figma-pillar
clarification: Fengrid must let users **compose real frontend components**
(HTML/CSS/JS triplets built from indexed assets) and preview them live. That
makes an embedded browser engine a **core feature**, not incidental debt.

## 2. Stack decision (locked)

**Qt 6 — PySide6 bindings, Qt Quick/QML shell, Qt WebEngine embedded.**

- **PySide6, pinned to the Qt 6.8 LTS line** (`pyside6>=6.8,<6.10`): LTS
  support window, WebEngine shares the LTS clock.
- **Qt Quick / QML** for the native workbench shell (library browser,
  inspector, composer chrome): declarative, virtualization-friendly, and the
  only path that scales to a designer-grade UI without a widgets rewrite later.
- **Qt WebEngine (embedded Chromium) for every preview surface**: component
  preview, snippet Result iframe, code playground. Rationale:
  - **Engine consistency.** OS webviews (WebKitGTK / WKWebView / WebView2 —
    the Tauri path) render CSS differently per OS. An embedded Chromium
    renders the same everywhere, which matters when the preview is the
    product: a component that looks right in Fengrid must look right in the
    user's browser.
  - **The browser is a feature, not debt.** The Figma pillar is a live
    HTML/CSS/JS surface; any "pure native" stack still needs an embedded
    engine for it, so the engine cost is paid either way — Qt spends it where
    it produces value.
  - **No Electron.** Explicit user requirement, plus Qt gives a native shell,
    menus, file dialogs and packaging story around the engine.
- The user explicitly accepted embedded Chromium (2026-10-18: "I'd be OK with
  Qt WebEngine and embedded Chromium").

**Rejected for the client:** Electron (user exclusion); Tauri 2 (closest
same-UI alternative — recorded, not chosen, because OS webviews break preview
consistency and the WebEngine cost is already accepted); Django (server
framework; future hosted-library option only); Elixir (service-layer fit only;
future collaboration/sync server); pure native widget toolkits without an
embedded engine (Slint/iced/GTK — cannot deliver the preview pillar).

## 3. Goals and non-goals

**Goals**

- Full parity with the 0.x feature set (baseline table in the review doc, §3).
- Single SQLite-backed library with unified tags/collections across asset
  types (replaces `localStorage gib-*` + per-pane server SQLite).
- A component composer: real HTML/CSS/JS triplets assembled from indexed
  assets, live previewed in embedded Chromium, exportable.
- A GUI that a professional designer keeps open all day: fast search,
  keyboard-first, virtualized at six-figure asset counts.
- Linux + Windows + macOS first-class; mobile as a staged companion.

**Non-goals (v1)**

- No cloud accounts, no sync service, no telemetry. Local-first is retained
  verbatim from 0.x.
- No hosted/multi-user server (Django/Elixir remain future *server-layer*
  options, out of scope here).
- No plugin API yet (the provider interface is the seam it would hang off).

## 4. Repository layout (new code lives under `qt/`)

```
qt/
  pyproject.toml            # PySide6 pin, entry point, deps
  README.md                 # skeleton status + local run instructions
  src/fengrid/
    __init__.py             # __version__
    __main__.py             # entry point (QGuiApplication + QML engine)
    app.py                  # app metadata + brand tokens (single source)
    core/                   # (planned M0) db.py, index.py, scanner.py,
                            #   watcher.py, thumbs.py, export.py, settings.py
    providers/              # (planned M0) icon.py, font.py, snippet.py,
                            #   color.py — one interface per asset kind
    bridges/                # (planned M1) QObject bridges exposing core to QML
    web/                    # (planned P3) scheme handler, preview profiles
  qml/Main.qml              # shell (skeleton today; workbench lands in M1)
  tests/                    # (planned M0) pytest + pytest-qt smoke
```

The 0.x app stays untouched in the repo root until the Qt app reaches parity
(strangler approach); `index.html` & co. freeze as the reference
implementation.

## 5. Process model

Single desktop process. Qt WebEngine runs Chromium child-renderer processes
(sandboxed, managed by Qt) for preview surfaces. No HTTP server is required
for the app to function — the LAN webshare (P5) is the only networking
component, and it is an *embedded, read-only* server, not the app's backbone.

## 6. Data model (SQLite + FTS5)

```sql
source(id, kind, path, label, enabled, added_at)          -- scan roots + manual folders
asset(id, source_id, kind,                                -- kind: icon|font|snippet|palette
      rel_path, name, theme, context, ext, size, mtime,
      content_hash, mono, width, height, colorspace, color_count)
asset_variant(asset_id, size, path)                       -- 16..256 icon variants
tag(id, name)               asset_tag(asset_id, tag_id)
collection(id, name, query) collection_item(collection_id, asset_id, position)
snippet(id, title, html, css, js, markdown, lang, created, updated)   -- imports from snippets.db
palette(id, name)           palette_color(palette_id, position, hex, locked)
component(id, name, html, css, js, tokens_json)                       -- Figma pillar
project(id, name, spec_json)      project_ref(project_id, kind, ref_id, position)
setting(key, value)                                       -- replaces gib-* keys
scan_state(path, fingerprint, last_seen)                  -- replaces meta-state.tsv
-- FTS5 virtual table over asset(name, tags, theme, context, path)
```

`gib-*` import mapping (M4 migration): `gib-sort/gib-context/gib-ext/gib-tone`
→ `setting` filter defaults; `gib-theme` → `setting.theme`; `gib-tag` /
`gib-coll` payloads → `tag` / `collection` rows (exact JSON shapes to be
enumerated during implementation from the current writer code at
`index.html:1340-1422`, `:2090-2091`). One-shot importer, idempotent.

## 7. Provider abstraction (the scope-expansion insurance)

One interface per asset kind — `IconProvider`, `FontProvider`,
`SnippetProvider`, `ColorProvider` — each exposing scan(), search/filter, and
detail payloads to the same grid/search/inspector QML views. Everything the
0.x app bolted on per-pane (fonts, colors, snippets) becomes a provider; the
next asset type (video stills? emoji sets?) is a new provider, not a new pane.
The grid stays type-agnostic; providers own their thumbnails and detail
models.

## 8. Asset protocol (`fengrid-asset://`)

A `QWebEngineUrlScheme` handler registered on the preview profile, serving
**whitelisted absolute paths** (the scan index) to WebEngine surfaces with
correct MIME types. This replaces the `icons/` file-system copy — previews
render the originals in place, no 5.7 MB duplication, no `file://` quirk
matrix. The scheme is registered `off-the-record`-compatible with a strict
path allowlist (only paths present in the index resolve; traversal and
non-indexed paths 404).

## 9. Preview security model (designed up front, not deferred)

- **Dedicated `QWebEngineProfile`** for user-content previews — off-the-record,
  separate from any profile that touches the composer editor.
- **No network** from preview content: request interceptor blocks everything
  except the `fengrid-asset://` scheme; CSP meta injected into preview shells.
- **No navigation, no downloads** from previewed components; link clicks are
  intercepted and offered as "open in system browser?" only for http(s).
- **No privileged bridge inside previewed content.** `QWebChannel` exists only
  on the trusted editor/composer surface (the app's own page), never inside
  user-previewed HTML.
- Renderer watchdog: hung or crashed preview renderers are killed and the pane
  recovers with a notice (Chromium renderer processes are disposable by
  design; treat them as untrusted and replaceable).
- Preview content is user-authored code by definition — the threat model is
  "the user pastes a malicious snippet from the internet", so the preview pane
  is treated exactly like a browser tab with no special powers.

## 10. GUI specification (designer-grade)

**Tokens** (single source in `app.py`, mirrored to QML; values from the
existing design system / brand identity):

| Token | Dark | Light |
|---|---|---|
| bg | `#101418` | `#F7F8F9` |
| surface | `#161B21` | `#FFFFFF` |
| surface-2 | `#1D242B` | `#EEF1F3` |
| border | `#2A333B` | `#D5DCE0` |
| text | `#E7EDF2` | `#16202B` |
| text-muted | `#6E7B86` | `#6B7A88` |
| accent (teal) | `#39B8C4` | `#0E7C86` |
| lit pane (amber) | `#F5C25C` | `#F5B841` |
| success | `#5BB98B` | `#2E7D4F` |

(Dark base/surface/border values observed in the shared pane design system;
light values from `branding/fengrid-brand.md`. Re-extract the authoritative
set from the pane CSS at M0 into `app.py` — one source of truth thereafter.)

**Typography:** Inter (UI) + Iosevka (mono: names, sizes, paths) — both already
self-hosted in `fonts/`. Heading font: Inter SemiBold (brand identity; the
original Bebas Neue brief is superseded — open question #5 in the review).

**Layout:**

```
┌────────────────────────────────────────────────────────────────────┐
│ toolbar: [fengrid mark] [search ⌕  /]        [size ▬▬●▬] [⊞ ⧉ ☰] [◐]│
├──────────┬───────────────────────────────────────────┬─────────────┤
│ sources  │                                           │  inspector  │
│ · icons  │        virtualized asset grid             │  (context-  │
│ · fonts  │        (GridView, cacheBuffer)            │   aware:    │
│ · code   │                                           │   icon /    │
│ · colors │                                           │   font /    │
│ ▾ tags   │                                           │   snippet / │
│ ▾ colls  │                                           │   palette)  │
├──────────┴───────────────────────────────────────────┴─────────────┤
│ status: 761 icons · adwaita 707 · indexed 2s ago · ⚡idle           │
└────────────────────────────────────────────────────────────────────┘
```

- **Left rail:** sources (toggleable scan roots + manual folders), saved
  searches, collections, tag tree — all SQLite-backed, drag targets.
- **Grid:** virtualized `GridView` with disk-backed thumbnail cache; size
  slider snaps to 16/24/32/48/64/128/256; density presets.
- **Inspector:** per-kind detail — icons (dims, variants, palette, path,
  copy/export), fonts (weights/styles, live sample, link/copy/install),
  snippets (code + run), palettes (contrast table, export).
- **Command palette** on `/`: fuzzy over actions, assets, collections.
- **Keyboard:** arrows navigate the grid, Enter opens inspector, `⌘/Ctrl+C`
  copies the name, `Space` toggles collection membership, `/` palette,
  `⌘/Ctrl+K` command bar; everything reachable without the mouse.
- **Composer view (Figma pillar):** canvas of component cards; each card =
  HTML triplet + design tokens + asset references; live preview pane renders
  through the sandboxed WebEngine profile; token panel exports CSS custom
  properties (parity with the 0.x Projects spec panel, then beyond).
- **Shell details:** native menus, real file dialogs, window-state persistence
  (QSettings), HiDPI clean, theme follows `styleHints` (auto/light/dark),
  single-instance activation, `fengrid://` deep links reserved.

## 11. Feature parity matrix

| Feature (0.x) | Qt 6 implementation | Phase |
|---|---|---|
| Offline / zero-cloud | local-first by design | P0 |
| Light/dark themes | QML tokens + `styleHints` auto | P0 |
| Platform scan roots (incl. snap/flatpak/CoreTypes) | `IconProvider.scan()` (port of `scan-icons.sh` logic) | P1 |
| Icon grid + 16–256 size slider | virtualized `GridView` + token sizing | P1 |
| Search + filters (name/tags/source/context/type/tone) | FTS5 + `QSortFilterProxyModel` | P1 |
| Tags & collections | SQLite + left rail | P1 |
| Inspector (dims/variants/colorspace/path…) | per-kind detail models | P1 |
| One-click copy | clipboard | P1 |
| Export PNG/JPEG/WebP/ICO/PDF/GIF/TIFF/BMP | native (Pillow) + ImageMagick fallback | P2 |
| `.icns`/`.xpm` conversion | Pillow (icns read) + IM fallback (xpm) | P2 |
| Fonts: families/navigator/selection/export/link mode | `FontProvider` + fontTools; symlink preserved | P2 |
| Colors: harmonies, WCAG, CSS/JSON/board exports | `ColorProvider` (port of colors.html logic) | P3 |
| Code playground | embedded WebEngine + CodeMirror 6 | P3 |
| Snippet import (VSCode/massCode) | core importer (port of `snippet_import.py`) | P3 |
| Projects coordinator + token export | core exporter (port of import_engine) | P4 |
| QR LAN webshare | embedded read-only HTTP server (port of serve.py static core) — **dropped from Qt v1** (2026-10-19): the 0.x `serve.py` webshare stays the phone path | P5 |
| Weekly update check | in-app check, `git ls-remote` probe kept | P5 |
| Three-OS install | packaging (Flatpak/NSIS/dmg) | P6 |
| Help guides | QML help overlay per pane | with each pane |

## 12. Mobile roadmap (honest staging)

- **M0 (kept from 0.x):** the QR LAN webshare is the phone path — an embedded,
  read-only HTTP server serving the index over LAN (port of `serve.py`'s
  static core + `/_connect`).
- **M2:** collections/tags import-export as JSON files — phones get data via
  file share, no sync service implied.
- **M3 (evaluation gate):** an Android companion. PySide6 Android deployment
  exists but is experimental; the realistic options are (a) PySide6 on
  Android, flagged experimental, or (b) a thin Qt Quick (C++) read-only
  browser reusing the schema. Composition editing stays desktop-first.
- **iOS:** PySide6 on iOS is not production-viable today. Options when the
  gate opens: a Qt Quick (C++) read-only app, or a PWA built from the
  webshare UI. No promises in the roadmap beyond "evaluated at the gate".
- Everything above is gated on the **provider abstraction** (§7) existing —
  that is what makes a read-only mobile client cheap.

## 13. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| PySide6 Windows ARM64 wheels unavailable on PyPI | Medium (one target) | Fail-fast probe in `build-windows.ps1` + stub Dockerfile with explanatory error; ship x64 for Win11-on-ARM emulation meanwhile; re-verify wheel status at M6 |
| QtWebEngine adds ~150–250 MB per bundle; LGPL obligations (dynamic linking, license texts, source offer) | Medium | Accepted with open eyes; compliance checklist in §14; strip unused locales/resources at package time |
| macOS cannot be built inside Docker (Apple EULA; no macOS base images) | Low (process) | Native scripts on macOS runners; Dockerfiles for macOS are fail-fast stubs; workflow already routes around it |
| QML performance at six-figure asset counts | Medium | Virtualized GridView + `cacheBuffer` tuning, disk thumbnail cache, provider-side pagination; tested against a 100k synthetic index in M1 |
| `.xpm` has no Pillow path | Low | ImageMagick optional fallback (parity with 0.x); drop if user okays (open question #2) |
| Engine drift between Qt WebEngine and user browsers | Low | Same-engine guarantee is *within* Fengrid; preview "open in browser" remains available |
| `snippets.db` / server SQLite schema drift before import is built | Low | Import reads are schema-tolerant (JSONC-style leniency already the norm); freeze a fixture DB in `qt/tests/fixtures/` |

## 14. Licensing / compliance

- PySide6 + Qt WebEngine are **LGPLv3**: dynamic linking (PyInstaller onedir
  keeps Qt shared libs dynamic — verify no static-link temptation), ship
  license texts + acknowledgments, honor the relinking/source-offer
  obligation for the bundled form.
- Proprietary codecs are **absent by default** in embedded Chromium — fine for
  CSS/HTML preview; flag if video preview ever matters.
- Fonts remain OFL (Inter, Iosevka); project stays MIT (Native IT © 2026).
- Add a `qt/dist/LICENSES/` bundle to the packaging step in M6.

## 15. Milestones

| Milestone | Content | Exit criteria |
|---|---|---|
| M0 | Skeleton runs; SQLite core; indexer + watcher; gib-* importer; tokens extracted | `fengrid` opens an empty indexed library; existing localStorage state imports |
| M1 | Icons parity (scan → grid → search/filter → tags/collections → inspector → copy) | Daily-drivable replacement for the icons pane |
| M2 | Native export + fonts pane parity | Export without the server; fonts browser at parity |
| M3 | Colors + snippets + code playground | Colors/code panes retired |
| M4 | Projects coordinator + component composer (Figma pillar) | 0.x projects export reproduced; composer live-preview works |
| M5 | In-app updater (webshare dropped from v1 — see §16) | update check in-app |
| M6 | Packaging (12-target pipelines live), signing, docs, parity cutover | 0.x frontends frozen with a pointer to the Qt app |

## 16. Open questions

RESOLVED 2026-10-19 (details in `docs/review/2026-current-state-review.md`
§4.1): webshare-in-v1 → dropped from Qt v1; `.xpm` → kept via the optional
ImageMagick fallback; IDE-binding parity → flexible, recorded in
`0002-editor-bindings.md`; Windows ARM64 → deferred (fail-fast stub stands);
heading font → Bebas Neue confirmed by the user (TTF bundled, OFL license).

## 17. Validation record

- 2026-10-19, linux-x64 prod: `build/scripts/build-linux.sh linux-x64` green
  end-to-end — PyInstaller onedir + `fengrid-prod-linux-x64.tar.gz`; the
  frozen binary smoke-tested offscreen (`--screenshot`, full first scan of
  926 assets, zero QML/thread errors; bundled Bebas Neue/Inter/Iosevka all
  render — no font fallback in the frozen app).
- Headless QA gate: `qt/tests/qa_render.sh` (pytest + dark/light offscreen
  renders; hard-fails on any TypeError / QColor-assignment / QThread noise).
  Green at commit time.
- Known warnings: PyInstaller cannot resolve `libxcb-cursor.so.0` for the
  xcb platform plugin on this headless build host — that library ships with
  normal desktop installs, and offscreen/software rendering is unaffected.
  linux-arm64 remains DRAFT (no arm64 runtime exercised yet).
