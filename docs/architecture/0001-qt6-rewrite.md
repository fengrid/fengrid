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

- 2026-10-21, MULTI-DATABASE + STORAGE BACKENDS (user spec: one active
  Fengrid database at a time with Recent/Quick-Access switching;
  local/SMB/NFS/SSHFS/S3 storage backends + a "personal cloud sync
  coming soon" note): core/registry.py opens
  `<data_dir>/registry.db` (registry_db table + its own setting
  table) — known/starred/active databases plus the GLOBAL prefs set
  (settings.GLOBAL_KEYS: theme, icon_size, search_mode, editor_keymap,
  colors_rule, startup_pane, update_check, last_export_dir). The
  settings module gains bind_registry(): global keys route to the
  registry connection, everything else stays per-database; unbound
  (no registry) behaves exactly like the old single-DB store, so
  pre-existing tests/environments are untouched; seed_globals() copies
  the active DB's values into the registry FIRST-WINS on first open
  (migration path for existing installs). bridges/databases.py (new):
  current/quick/recent properties, star/clear/create/open/switch
  slots; switching = registry flip + os.execv relaunch (every bridge
  holds the one con — hot-swap is unsafe; the chunked scan commits
  from the settings batch make an interrupted scan restart-safe), argv
  filtered of --db so the registry wins next start;
  FENGRID_NO_RELAUNCH=1 keeps tests in-process, and _activate updates
  the session path so suppressed mode behaves post-switch. Startup:
  active → fallback to the default DB with a toast (startupNotice)
  when the file vanished. QML: the hamburger menu grows a Database
  block (disabled header "Database — <label>", Quick access + Recent
  Repeaters with when/missing states, Star/New/Open/Clear items) —
  Repeater delegates inside a Menu work in Qt 6.9; New/Open are
  FileDialogs (fileMode SaveFile/OpenFile, defaultSuffix,
  Icons.toLocalPath); the window title carries the DB label.
  core/storage.py (new) + bridges/storage.py (new) + storage_mount
  table: backends local/smb/nfs/sshfs/s3 attach by MOUNTING into
  data_dir/mounts (sshfs/gio/s3fs/mount through an injectable runner —
  unit-tested without root or network; smb discovers its gvfs entry by
  diffing /run/user/…/gvfs before/after), returning a local path so
  the entire scan pipeline stays untouched; credentials stay in the
  system (agent / keyring / passwd-s3fs) and are never stored by
  Fengrid. Settings → Storage section: availability rows (missing tool
  ⇒ "install X — …" + disabled Attach), attached-mount rows with
  health + Eject, a local row pointing at the folder picker, and the
  coming-soon callout for personal cloud sync. Mounts persist per
  database and remount BEFORE the first scan at startup
  (ready → _start_initial_scans ordering). GOTCHAS: one-shot QThread
  workers must QThread.currentThread().quit() when their slot returns —
  otherwise the thread idles until aboutToQuit and destroying the
  bridge first ABORTS the process ("QThread: Destroyed while running";
  this latent flaw existed in the scan workers too — fixed in all
  three bridges); _clear_thread_refs must be generation-aware (a
  finished event can arrive AFTER a newer rescan installed the next
  thread — nulling the new generation's refs would GC a running
  worker); sqlite connections are thread-affine — the storage worker
  only mounts, all DB writes happen in _on_done on the main thread
  (the first bridge test caught the ProgrammingError); a SettingRow
  written with `visible:` instead of `rowMatches:` silently pins
  rowMatches to its `true` default so its section never hides (diag:
  rowMatches=True under visible=False); QML `visible` reads confirmed
  EFFECTIVE again (property() under a hidden parent returns False).
  CORRECTION to the settings entry below: Repeaters ARE Items and
  their delegates DO reparent into a layout's `children` — the
  first-run sections vanished because their children carry no
  `rowMatches` property, not because Repeaters are invisible to the
  introspection loop. Verified: 118 tests (test_registry:
  routing/seed/CRUD + bridge flows incl. junk-DB rejection and create
  refusal; test_storage: pure cmd builders, availability honesty,
  runner-injected mount + failure tails, detach no-ops, mount-table
  persistence, full threaded attach/detach) + QA gate (dark/light
  clean) + --dialog menu / settings-storage / settings renders with
  ZERO QML errors + vision on all three (database header, Quick
  access, Recent with times, coming-soon callout, four backends with
  live availability, dimmed Attach buttons for missing tools).
- 2026-10-21, SETTINGS + FIRST-RUN SETUP (user spec: VS Code-style
  settings surface; one-time setup defining system paths, asset
  folders, look/layout and core features while the initial scan runs):
  the header grows a hamburger main menu (Menu with
  `parent: Overlay.overlay`, position recomputed in onAboutToShow —
  mapToItem creates no layout dependencies, so a create-time binding
  goes stale) with Settings… / Check for updates / About; Ctrl+, also
  toggles. `SettingsScreen.qml` loads through a content-area Loader
  (REBUILD-ON-OPEN: creation-time bindings capture bridge state, which
  kills the whole binding-death sync class; only controls the always-
  live header can also change — theme combo, search-mode combo,
  icon-size slider — keep Connections re-syncs). Rows: category tree +
  live search filter via matches(); sections carry General (search
  mode, startup pane, run-setup-again), Appearance (theme, icon size),
  Library (system icon roots + font dirs with per-path checkboxes,
  custom folder rows with kind chip/count/enable/trash, add + rescan
  buttons), Editor (keymap), Colors (palette rule), Updates (startup
  probe toggle + status + check now), About (version, db path,
  releases). `FirstRun.qml` is a modal card on Overlay.overlay while
  setupOpen: system paths, asset folders, look & feel, behavior — all
  writing the SAME keys Settings reads — scan progress in the footer
  while the initial ingest runs; Escape/Get started →
  complete_first_run → Connections flips setupOpen → toast pointing at
  the menu + IconButton.flash() pulse. `__main__` computes
  initialFirstRun (flag unset AND NOT --screenshot, so pane shots stay
  clean on a fresh DB; --dialog settings|firstRun forces the surfaces
  for QA) and --pane now defaults to the startup_pane setting.
  prefs bridge (NEW) owns icon_size/startup_pane/update_check/
  first_run_done + the detected path lists (resolved, so they
  string-match scanner rows); update_check gates the Updater's startup
  probe delay. Core-layer fixes this exposed: the library scan worker
  passed the default kinds=("system") so user-added folder sources
  registered but were NEVER scanned; scans chunk-commit every 400
  files (settings saves during the first-run scan would otherwise hit
  SQLITE_BUSY behind one whole-scan transaction); _sweep_disabled
  purges disabled sources' assets + fingerprints at scan start
  (uncheck = leaves the grid, re-check = re-indexes) with
  set_path_enabled upserting before the first scan registers a path;
  asset upserts are id-preserving UPDATEs (DELETE+INSERT orphaned
  item_tag/collection_ref/asset_link rows on every mtime touch — FTS
  has an AFTER UPDATE trigger so search stays in sync); rescan()
  queues (_rescan_pending → singleShot drain) because first-run adds
  folders WHILE the initial scan runs. GOTCHAS: QQmlComponent
  instances DIE with their component — a helper that returns after
  comp.create() destroys the scene before the test runs (keep `comp`
  alive on the yielding fixture frame); QML `visible` READS are
  effective — a section filtering rows by their `visible` self-
  deadlocks (it hides itself on the first non-match, then reads its
  rows false forever); filter on plain data (rowMatches mirror);
  QQuickSlider has moved()/pressed but NO valueModified (load-time
  "Cannot assign to non-existent property"); pane shortcuts
  (Space/Ctrl+S/…) are window-scoped and fire THROUGH overlays —
  typing a space in the settings search regenerated the palette — so
  overlays publish Shell.overlayOpen (new singleton) and pane/main
  shortcuts gate on it (Escape stays unambiguous); Repeaters are not
  Items, so sections introspecting `children` never see Repeater-housed
  rows (first-run sections 1–2 vanished; filterRows opt-out);
  Basic-style ScrollBar handles render invisibly on light surfaces —
  style them token-driven. Verified: 105 tests (new test_prefs +
  test_qml_settings: clamp/persist round-trip, flag flip + signal,
  upsert-before-scan, component creation, the full filter chain
  through real bindings, four-section visibility, scrollability of the
  setup card) + offscreen pane/settings/firstRun renders with ZERO
  QML errors + vision on all three (menu button, category tree, rows
  + controls, all four setup sections, scrollbars, clean layout).
- 2026-10-20, PANE TABS IN THE RAIL (user direction change: "include the
  Panes as tabs at the top of the left panel"): the top-bar color-coded
  PaneButton row was built first (AbstractButton + icons + glow underline)
  but the user replaced it with a tab strip INSIDE the rail. SideRail
  grows a 44px tabBar row: 5 compact 34x32 icon-only PaneTabs (image /
  type / droplet / code / package — three new Feather paths in Icons.qml:
  type, droplet, package), each tinted with its category accent; the
  active tab gets a 16%-alpha accent wash + glowing underline (layered
  translucent fills, no MultiEffect — software-renderer friendly), hover
  10% wash, 120ms fades. Clicking a tab emits the restored panePicked
  signal; Main binds onPanePicked → root.pane, so the tab row and the
  pane are one control (no separate menu — user rule: buttons and menu
  one and the same). The rail content starts directly below a hairline.
  Pol flair kept from the round: header vertical gradient + hairline,
  translucent Toast (88% alpha glass), full-window accent flash on pane
  switch (paneFlash, 7% → 0 over 300ms, tinted by the incoming pane's
  accent, enabled:false so it never eats input), Ctrl+1..5 pane
  shortcuts. GOTCHAS: AbstractButton's `icon` is FINAL (declared
  `property string icon` fails "Cannot override FINAL property" — named
  iconName); AbstractButton has no cursorShape (HoverHandler
  cursorShape instead); QQuickIcon assignment fails on string
  (instantiation sites must use iconName too). Search box made flexible
  (fillWidth, min 140/max 320) so right-side controls never clip.
  Verified: dark render + pane-0 vision (5 tabs, teal glow on Icons,
  no Panes list, no clipping), light render + pane-2 vision (droplet
  tab rose glow, palette content below, top bar clean), QA gate.
- 2026-10-20, LOCK TEST FLAKE ROOT CAUSE: test_lock_button_click_
  flips_lock_state failed intermittently in full-suite runs (and 1 of 6
  in a fixed-order loop) at the SECOND click — `assert locked is False`.
  Two QCoreApplication.sendEvent presses at the same scene point within
  QGuiApplication's double-click interval are converted to
  MouseButtonDblClick (MouseArea's onClicked never fires) — a real Qt
  delivery rule, not a test-harness artifact. Fix: QTest.qWait(style
  hints' mouseDoubleClickInterval + 30ms) between the lock and unlock
  clicks. GOTCHA: styleHints().mouseDoubleClickInterval is a METHOD in
  PySide6 (call it — bare attribute passes a builtin to int() and
  TypeErrors). 10 consecutive file loops green; full suite 10x both
  orders (fixed + random) 96/96.
- 2026-10-20, RAIL CONTENT FOLLOWS THE PANE (fonts split): the icons
  rail was showing font-derived entries — Themes/Contexts/Types queried
  the whole asset table without a kind filter, so font rows surfaced as
  "truetype"/"opentype" themes and ttf/otf Types, while the Fonts pane
  rail had nothing. Fixes: _refresh_lists scopes every list to
  kind='icon' (tags count via a correlated subquery so zero-count tags
  stay visible); new iconCount property backs the rail's "All assets"
  row (totalAssets keeps counting all kinds for the footer/needsScan);
  _apply_filters pins a.kind='icon' so the icons grid can never list
  font files; the Fonts bridge gains rail lists (families + fontTypes
  by ext) and filters (familyFilter exact-match, typeFilter by
  extension — families matching = own a file of that ext); the rail
  grows a Fonts-pane block: All fonts / Families / Types, each row
  click-to-filter with toggle-off, violet accent. Verified: 96 tests,
  DB probe (0 font-named icon themes; icon exts svg/png/xpm/ico/bmp
  only; font exts ttf only), vision on both rails (Fonts pane shows
  All fonts 7 / five families / TTF 7; Icons Themes clean).
- 2026-10-20, TAXONOMY LAYER (user feature request batch): custom
  libraries, smart collections, custom fields + generated IDs, and typed
  links — core/taxonomy.py + bridges/taxonomy.py + new tables.
  1. SCHEMA: library_view (name UNIQUE, tags csv, match_all),
     smart_collection (name UNIQUE, item_kind, criteria JSON),
     asset_field (name UNIQUE, type text|number|bool|date|select|id,
     options JSON), asset_field_value (PK asset_id+field_id, cascade),
     asset_link (from_kind/from_id → to_kind/to_id, role, UNIQUE
     incl. role, indexes both directions). All CREATE IF NOT EXISTS in
     SCHEMA (executescript runs every connect → upgrades are automatic).
  2. SAVED LIBRARIES: named tag sets; match_any (union) or match_all
     (intersection); library_view_assets resolves to asset ids. The rail
     gains a Libraries section (Icons pane) with a "+ New library…"
     affordance and a Configure/Delete context menu; clicking a row
     activates library.set_library_view → multi-tag grid filter
     (EXISTS-per-tag for match_all, IN for any; toggles off on re-click;
     single-tag picks and other activations supersede the overlay).
  3. SMART COLLECTIONS: criteria JSON evaluated LIVE (no membership
     rows). Icon criteria: tags (any/all), theme, context, ext, starred,
     q (name/path LIKE). Snippet/palette criteria: tags + q against the
     tags column. Rail shows a Smart subsection inside the collections
     block on every pane that carries its kind (amber zap accent), with
     a "New smart collection…" affordance + Edit/Delete context menu;
     the criteria editor edits tags/match-all/q and previews nothing
     stale because matching happens at query time. Clicking activates:
     icons → library.set_smart_collection (criteria overlay in
     _apply_filters), palettes/snippets → colors/code set_smart with a
     python-side _matches_smart filter over their tag columns.
  4. CUSTOM FIELDS: global definitions (text/number/bool/date/select/id);
     per-asset values; missing values list as ''. The asset inspector
     gains FIELDS + LINKS sections — type-appropriate editors (text
     input; checkbox; choice combo; id gets a Generate button), a
     "+ Field…" dialog (name/type/choices or prefix+pad), and
     right-click-a-field-label → Delete field.
  5. GENERATED IDs: id-type fields with {prefix, pad}; counter = highest
     numeric suffix already minted with that prefix + 1 (suffix scan —
     no separate sequence state to corrupt; manual high values push the
     counter past them). Context menu on asset cards: Generate ID ▸
     (one item per id field).
  6. LINKS: directed, role-labelled, between any two of icon/font/
     snippet/palette/collection/library/project/smart. One-to-many /
     many-to-many are free; many-to-one = many sources on one target.
     Asset-card context menu gains Link to… (live target list pulled
     when the menu opens); the inspector lists links both directions
     (→/← prefix, click a row to remove).
  7. TAG MANAGEMENT: tags are right-clickable — Rename tag… / Delete tag
     (core db.rename_tag/delete_tag; memberships follow the rename via
     the FK; an active tag filter clears when its tag is deleted).
  8. PROJECTS × COLLECTIONS: project_asset kind set extended with
     'collection' — a project can collect an entire collection (its refs
     follow live); Projects context menu gains Attach collection… ▸.
  COLLECTIONS/KINDS NOTE: collections carry per-kind ref counts and are
  shown per pane (interaction-refinement batch); libraries are asset
  (icon) views; smart collections are per-kind. Projects span kinds.
  Verified: +9 core tests (96 total; CRUD/matching/id-gen/links/tag
  rename-delete/project-collection), bridge probes for view + smart
  activation (3→toggle→3; smart 3→2; match-all →1), full QA gate green,
  app loads offscreen with the new rail sections.
- 2026-10-20, MONO FONT SWAP (user readability feedback): bundled
  Iosevka Mono (deliberately condensed — cramped at 9–13px UI sizes)
  replaced with Roboto Mono (Apache-2.0, googlefonts/RobotoMono static
  Regular + Medium TTFs). theme.monoFont pick order: Roboto Mono /
  Roboto Mono Medium (the style-specific family the Medium static TTF
  also registers) / Source Code Pro / Noto Sans Mono / DejaVu Sans Mono.
  Sweep: SVG palette-board exports (core/colors.py), demo snippet CSS
  (core/demo.py), and the 0.x reference pages (index/colors/code/fonts/
  projects.html @font-face + --font-mono stacks) now point at
  RobotoMono-*.woff2 — converted from the TTFs with fontTools+brotli —
  and server/connect.html's mono stack. Iosevka TTFs, woff2s, and
  license removed (no remaining references in app code; historical docs
  mentions left as-is). fonts/ROBOTO-LICENSE.txt added (per-font license
  convention). Verified: QFontDatabase registers 'Roboto Mono' +
  'Roboto Mono Medium'; Theme probe returns monoFont='Roboto Mono'; 87
  tests green; dark/light renders clean.
- 2026-10-20, INTERACTION-REFINEMENT BATCH (user UX feedback):
  1. GENERATE VARIATION: core generate() grew a `variation` counter —
     with locks the pure template math was fully deterministic (repeated
     presses were no-ops). Two sources fix it: (a) ANCHOR ROTATION — the
     anchor rotates through the locked set (variation % n_locks), so
     multi-lock schemes re-derive around a different member each press;
     (b) SEEDED JITTER — deterministic _pick(seed + v*const) drift on
     hue (±4° strict rules, ±14° pleasing) and the L/S bases. GATED ON
     v > 0: variation=0 reproduces the historical math bit-for-bit (the
     anchoring tests pin exact hues); the bridge starts presses at 1.
     GOTCHA: ORDER BY columns must take table aliases once a JOIN exists
     (`s.id` — bare `id` is ambiguous with collection_ref.id).
  2. RANDOM MODE: rule "random" — unlocked slots get fully random hues
     with L/S spread; locks still pass through. GENERATION_MODES =
     HARMONIES + ("random",); bridge set_rule accepts it; Colors combo
     gains "Random".
  3. DRAG-TO-REORDER swatches: press → >8px → dragging; the card lifts
     (z:3 + Translate dragDX), open-hand cursor on hover / closed-hand
     while dragging (standard indicators), ONE move_swatch on release
     (mid-drag moves would recreate delegates and drop the grab).
     Target = index + round(dragDX / (slot+spacing)). Click still selects.
     Tested with window-level press/move/release events (test_qml_colors).
  4. LOCK CHIPS ALWAYS VISIBLE: hover/selection gating removed — per the
     user's rule, anything visible must perform its primary function on
     engagement; hover-only reveal also proved fragile (stale hover).
  5. FONTS SINGLE-CLICK: family card click now selects AND opens the
     details screen (the old hover-preview cue forced a second click).
  6. CONTEXT-SPECIFIC RAIL: paneKind (icon/palette/snippet) drives the
     rail — icon-only sections (All assets, Themes, Contexts, Types,
     Tags, Add-folder) render only on the Icons pane; Collections show
     per-kind counts and hide rows with none of the current kind (empty
     collections stay listed as create targets); clicking a collection
     filters the ACTIVE pane via its own bridge filter (library→icons,
     colors→palettes via list_palettes(collection_id), code→snippets via
     list_snippets(collection_id)); each bridge keeps its own filter
     state (colors.collectionFilter / code.collectionFilter). Fonts and
     Projects hide the collections block entirely (no font refs exist).
  7. FLICKER SMOOTHING: Behavior on color/tint (90ms ColorAnimation) on
     SideRail RailItem + add-folder row and IconButton tint/background —
     abrupt hover flips read as flicker when the mouse sweeps.
  Verified: 87 tests (was 81; +5 core generation/filter tests, +1 QML
  drag test), clean dark/light renders, vision-verified Colors pane
  (chips always visible, rail shows only Panes+Collections) and Fonts
  pane (collections block correctly absent — no font refs).
- 2026-10-20, COLOR-LOCK FIX: root cause was NOT the generator — the
  swatch card's selection MouseArea was declared AFTER the lock/remove
  tool buttons, so it stacked on top and swallowed every click aimed at
  them (locks could never be SET from the UI; bridge logic was correct
  all along). Fixes: tools Row z:2 over the MouseArea; tools also stay
  visible while the swatch is selected (hover-only reveal was fragile);
  locked chips tint amber; save_palette now persists per-position locked
  flags (bridge save() passes them) so locks survive Save + reopen.
  Verified by qt/tests/test_qml_colors.py: window-level synthetic mouse
  events through the REAL delivery path (itemAt stacking) — click flips
  lock, second click un-locks, locks survive rule switch + generate.
  GOTCHA: inline-component instances report className "SwTool_QMLTYPE_n"
  (no "Button" substring) — find them by class prefix, and re-find after
  any swatchesChanged (delegates are re-created, old references dangle).
- 2026-10-20, feature batch (7 items):
  1. COLOR LOCKS: `generate()` anchors unlocked slots to the FIRST locked
     swatch's actual hue, offset by the harmony template (hues[i] -
     hues[anchor_slot]); scheme switches + Generate now keep locks fixed
     while fresh colors coordinate with them. No-locks behavior unchanged
     (base_hue path). GOTCHA: rgb2hsl returns (h, s, l) — hue FIRST; an
     `_, _, x =` unpack reads LIGHTNESS.
  2. FONT DETAILS: FontDetail.qml popup — size slider (10–96px), editable
     sample text, light/dark preview background, glyph sentence, and every
     indexed variant rendered in its own weight/italic (CSS weights mapped
     to Qt Font enums). Opened via double-click, right-click menu, or the
     Details… button in the fonts detail strip.
  3. CONTEXT MENUS: asset cards (star/unstar, copy, add-to-collection),
     snippet rows (open, copy title, add-to-collection submenu, delete),
     projects (open, export…, delete), saved palettes (load, export…,
     add-to-collection, delete), font families (details, export CSS/ZIP),
     collections (new sub-collection, edit tags, delete). Pattern: delegate
     exposes `readonly property var row: modelData`; a root-level Menu
     reads `list.currentItem.row` or a `target` set at popup time.
  4. COLLECTIONS v2: migration adds collection.parent_id + collection.tags
     and the collection_ref table (item_kind × item_id — icon/font/
     snippet/palette); legacy collection_item rows are copied in once as
     'icon' refs (old table kept, unused). starring moved to collection_ref.
     db.collection_tree (parents before children, per-kind counts),
     create_sub_collection, set_collection_tags, delete_collection
     (children re-parent, not orphaned), add/remove_collection_ref with
     row-existence validation. Rail renders the tree (indented children,
     tags as a second line) with the context menu.
  5. SEARCH: core/search.py — fuzzy (subsequence + difflib ratio ranking),
     regex (compiled once, SearchError on bad patterns), content (snippet
     bodies via SQL + text-like asset files, capped at MAX_FILE_BYTES
     256KB / MAX_SCANS 2000). Bridge: library.set_search_mode +
     searchMode property; the top bar gains a mode combo. Code-pane
     snippet search already covers body content. PERFORMANCE GUIDANCE:
     fuzzy/regex scan a bounded candidate list (100k names ≈ a few MB,
     ~0.5s/search) — fine to ~100k assets; beyond that, precompute a
     name index. Content search is I/O-bound by design; the right scale-up
     is an FTS5 content index populated by the indexer's metadata pass
     (it already visits every file), not query-time reads. Regex patterns
     are user-supplied: the cap bounds the damage, but a dedicated regex
     timeout worker would be the next hardening step.
  6. CATEGORY ACCENTS: theme tokens accent_icon (teal), accent_font
     (violet), accent_code (coral), accent_color (rose), accent_project
     (green) — dark + light variants (0.x pane colors). Applied: rail pane
     indicator bars, Code tabs/Save, Fonts selection borders, Projects
     new-button/selection, Colors GenButton hover/Terminal toggle/Derive/
     Save-to-snippets, Terminal section headers.
  7. TERMINAL THEMES: core/termcolors.py — 16-slot theme model
     (bg/fg/cursor/selection + 8 ANSI + 8 bright), derive() from
     bg/fg/accent (deterministic HSL rotations), exports: iTerm2 plist
     (plistlib), Windows Terminal JSON, Guake palette string (16+bg+fg),
     GNOME dconf script, kitty.conf, alacritty.toml, generic JSON.
     preview_html doubles as a saved-snippet body (live terminal mock with
     the JSON export embedded as a comment) — themes persist via
     "Save to snippets" (collectable + project-attachable). Bridge
     TermColors (working theme, presets, set_value/derive/export/
     save_as_snippet). Colors pane gains Harmonies | Terminal sub-tabs
     (--term QA flag); designer = preset picker + name + derive anchors +
     slot editor + pure-QML live terminal preview + export bar.
  PRESETS: 14 example themes transcribed from Gogh-Co/Gogh themes/*.yml
  (MIT/Apache-2.0): Dracula, Nord, Gruvbox Dark, Solarized Dark/Light,
  One Half Dark/Light, Tomorrow Night, Tokyo Night, Catppuccin Mocha,
  Monokai Pro, Snazzy, Ayu Dark, One Dark — fetched verbatim from the
  upstream repo (selection colors chosen per theme; Gogh YAML has none).
  Verified: 19 new core tests (65→78 total incl. generate-anchoring,
  termcolors roundtrips/plists/exports/presets/snippet roundtrip, search
  modes, collections v2 incl. migration preservation and re-parenting),
  bridge probes (search mode switching, collections tree/tags/delete,
  demo bridge), and offscreen screenshots (terminal designer opaque +
  complete; --term QA flag added). QML lessons reconfirmed: adjacent
  string literals need `+`; Slot-with-result must be CALLED in QML
  (`terms.presets()`, not `terms.presets`); repeater delegates need ids
  (parent.parent.modelData traps).
- 2026-10-20, demo data suite: `core/demo.py` — one-call showcase install:
  20 generated Feather-style SVG icons (theme/context/tag metadata so the
  icons-pane filters and tags have real content), a font row (bundled Bebas
  Neue copied into the demo tree so removal stays uniform), 12 code
  snippets (product card, stat card, pricing table, table-based email
  signature, newsletter masthead, markdown recipe card, gallery grid, code
  block style, hero split, sticky navbar, testimonial, badge chips) and 8
  named palettes, all wired into 14 demo projects (SaaS marketing site,
  admin dashboard, e-commerce storefront, online magazine, photographer
  portfolio, developer blog, toolkit docs, HTML email signature, email
  newsletter, recipe collection, design system starter, mobile app UI kit,
  conference/events, nonprofit landing) — each with tags, a per-project
  prefix/radius/type scale, and attached assets across all four kinds; the
  email projects are preview-driven (`preview.snippetId` resolved at
  install). Every created row id is recorded in the `demo_ids` setting, so
  `remove(kinds)` deletes EXACTLY the demo rows — per kind (projects /
  icons / fonts / snippets / palettes / tags), leaving user data and any
  kinds the caller keeps untouched; demo files live under
  `<data-dir>/demo-assets/` and are swept with their rows. Install is
  failure-atomic (a crashed run sweeps its own partial state back out) and
  idempotent. UI: a Demo button in the Projects toolbar — "Load demo
  suite" / "Remove demo…" opening a per-kind checkbox dialog (Select
  all / Keep all / Delete). Verified: 3 core tests (install roundtrip
  incl. counts + snippet-preview wiring + demo tagging; selective removal
  keeping tags+palettes while user-created rows survive; full sweep clearing
  the marker and directory with clean re-install), a bridge probe
  (property/slot/signal behavior incl. partial removal keeping
  installed=True), and seeded screenshots of the loaded Projects pane
  (14 projects with asset counts, "Remove demo…" button) and the Icons
  pane (21 assets, themed filters). QA gate: 65 tests + clean renders.
  Lesson: connections must come from db.connect() — a raw sqlite3.connect
  probe crashed in get_project (no sqlite3.Row factory), which is what
  surfaced the failure-atomicity requirement.
- 2026-10-20, editor keymap schemes: the Code pane's command layer is now
  scheme-driven (Code bridge `keymap` property + `set_keymap` slot,
  persisted on the `setting` table as `editor_keymap`, default vscode):
  **vscode** — native TextArea behavior (Ctrl+A selects all, word motions
  work natively), only Tab/Shift+Tab indent/dedent handled; **emacs** —
  the ported 0.x layer (Ctrl+A/E/K/Y/D, Alt+B/F/D/Backspace, Ctrl+X
  Ctrl+S); **vim** — the modal layer, enabled from launch (the VIM toggle
  still overlays/escapes any scheme); **readline** — the emacs set plus
  Ctrl+U (kill to line start) and Ctrl+W (kill word back), which stay out
  of the emacs scheme because Ctrl+U is universal-argument there.
  Shift+Tab dedent works in every scheme incl. vim insert mode
  (`tabDedent`, snapshot-undo-aware). The picker lives next to the VIM
  button in the editor toolbar; the help popup documents all four.
  Note: emacs/readline intercept Ctrl+A — the QA keys harness therefore
  sets the scheme explicitly per test; the default scheme is vscode.
  QA gate: 62 tests + clean dark/light renders; pane-3 screenshot
  confirms the combo renders unclipped next to VIM.
- 2026-10-20, starring + context menu: `db.ensure_defaults()` runs at every
  connect() — the `starred` tag and `Starred Assets` collection exist from
  the first launch and are re-created on demand if a user deletes them
  (`_starred_ids`). `db.set_starred()` toggles the tag AND the collection
  membership in one action so the tag filter and collection navigator
  always agree (idempotent). The grid model gains a computed `starred`
  role (EXISTS subquery in _apply_filters — no per-delegate queries); the
  grid renders a filled lit-pane star badge on starred cards; a
  right-click context menu on cards offers Star/Unstar, Copy name, and
  Add to collection (submenu over existing collections); the inspector
  carries a star toggle button (get_details now includes `starred`, so the
  amber active state refreshes via the existing tagsRevision reload path).
  Icons.qml gained the Feather star (outline + filled via a new optional
  `fill` param on url()). IconName Gotcha: the Qt theme has NO
  `borderStrong` token (0.x only) — using it fails with "Unable to assign
  [undefined] to QColor" caught by the QA render gate. Verified by 5 new
  core tests (defaults exist, toggle both sides, deleted-defaults
  recreation, idempotency, role plumbing) + a seeded-DB screenshot: star
  badge on the starred card only, `Starred Assets — 1` in the rail,
  `#starred — 1` in tags. QA gate: 56 tests + clean dark/light renders.
- 2026-10-20, M5 updater: `core/updater.py` — release probe via the GitHub
  releases API over urllib (no external binary on end-user machines), with
  the 0.x `git ls-remote --tags` probe kept as the fallback; pure parsing
  helpers (`parse_version`, `is_newer` — '0.3.0.dev0' compares as 0.3.0,
  a dev suffix never counts as newer; `parse_ls_remote` skips peeled
  `^{}` lines and non-version tags). `bridges/updater.py` probes on a
  daemon thread (a blocked socket must not freeze the UI) and reports
  through queued signals; auto-check 4 s after startup, DISABLED under
  offscreen/screenshot QA so the gate never touches the network. Footer
  version text flips to an amber "update available: vX — click to open"
  that opens the releases page; clicking the plain version re-checks.
  QA gate: 51 tests + clean dark/light renders.
- 2026-10-20, M4 projects pane: `core/projects.py` — full port of the 0.x
  configurator export adapted to the Qt data model (attached assets are
  rows of the indexed `asset` table rather than install-tree files):
  tokens.css (six roles falling back positionally to the first attached
  palette, then to the 0.x dark defaults; radius; modular type scale;
  font stacks), fonts.css @font-face set, icons.css classes + icons.js
  name map, the boilerplate index.html driven entirely by the tokens,
  snippet pages, palettes.json, manifest.json, README — as zip OR tar.gz.
  `build_site_html(inline_css=True)` is the SAME generator for the live
  preview, so preview and export cannot drift; attached icon/font urls
  are rewritten to absolute fengrid-asset:// paths (the scheme allowlists
  exactly the scan index). Schema: `projects` + `project_asset`
  (UNIQUE(project_id, asset_kind, asset_id), FK ON DELETE CASCADE — the
  0.x (type,key) join model kept, rows instead of keys). Bridge: CRUD,
  search, per-key settings setter, positional palette→roles assignment,
  picker slots (icons/fonts/snippets/palettes/families read from the same
  index the other panes use). QML: sidebar + four parameter areas + assets
  strip + preview split. QML lessons recorded: inline `component` blocks
  must be declared INSIDE the root object (outside breaks the parser with
  a misleading "Expected token `)'" far away), and QML JS does NOT
  auto-concatenate adjacent string literals (needs explicit `+`).
  Vision pass caught a real horizontal overflow in the params column
  (fixed with explicit Layout widths); re-verified clean.
  QA gate: 46 tests + clean dark/light renders.
- 2026-10-20, M3 code pane (snippets + playground): schema (`snippet` table
  in db.py SCHEMA), `core/snippets.py` (1:1 port of snippet_import.py —
  JSONC stripper, language map with ≥3-char prefix constraint so short keys
  like "c"/"go" stay exact-only, VSCode + massCode readers; the 0.x cobol/
  c-prefix bug is fixed and test-encoded), `bridges/code.py` (CRUD + filter/
  sort + import bridge), `Code.qml` (tabbed HTML/CSS/JS editors with the
  transparent-TextArea-over-highlight-overlay technique ported from 0.x,
  both layers inside the Flickable contentItem so they scroll as one;
  snippet sidebar with search/sort/lang filter/tag cloud; VSCode/massCode
  FileDialog import; title/tags inline; Ctrl+S / Ctrl+Enter / Tab-indent;
  help popup). Preview runs through the hardened off-the-record profile
  (`web.make_preview_profile`) via PreviewPane's new `document` mode
  (loadHtml with an fengrid-asset:// base URL) inside an on-demand Loader.
  WebEngine startup ordering FIXED: QtWebEngineQuick.initialize() must run
  before QGuiApplication (Qt 6 requirement) — previously deferred, which
  would have made every preview dead on arrival; now skipped only under
  QT_QPA_PLATFORM=offscreen so the QA gate stays free of Chromium teardown
  noise. `web/` restructured: Qt-bound classes moved to web/handlers.py and
  all entry points guarded, so platforms without WebEngine wheels (Windows
  ARM64) import cleanly. GLX robustness: app.py gains hl_ink/ink_faint
  tokens (0.x values); `glprobe.py` degrades to QT_QUICK_BACKEND=software
  + QT_XCB_GL_INTEGRATION=none when the display has no usable GL; the
  Xvfb end-to-end test proved the frozen binary launches and renders the
  full shell where the old build SIGABRTed. KNOWN GAP vs 0.x: the
  emacs/vim keybinding layer is NOT yet ported (recorded as the next code-
  pane increment); editor shows line:col status only. QA gate: 37 tests +
  clean dark/light renders; --pane N CLI flag added for per-pane QA
  screenshots.
- 2026-10-19, M3 colors pane: full port of colors.html — harmony generator
  (exact hue offsets + fract(sin(seed)) jitter, deterministic for tests),
  HSL/hex editor with WCAG AAA/AA/AA·lg/fail readouts, deterministic color
  naming (same anchor set), lock/remove/reorder, space-to-reroll, palette
  CRUD in the library DB (palette/palette_color tables via CREATE IF NOT
  EXISTS — no migration needed), and the four exports (CSS vars, JSON,
  board SVG, 2x PNG drawn with Pillow). QML: Colors.qml with imperative
  slider sync (dragged sliders lose `val` bindings) and hex fields that
  only follow selection changes (0.x anti-fight-typing behavior).
  QA gate: 28 tests + clean dark/light renders.
- 2026-10-19, M2 increment (fonts + WebEngine scaffold): fonts pane at parity
  for scan/family-grouping/filter/export — fontTools metadata (family, style,
  weight, italic; OS/2 + name tables, no fc-scan and thus no .ttc trailing-
  newline trap), incremental `indexer.scan_fonts` with per-file cancellation,
  `Fonts` bridge + `Fonts.qml` (family grid, filter, CSS/ZIP export), font
  columns via idempotent `_migrate` (M1-era DBs upgrade on connect, tested).
  WebEngine scaffold landed per §8/§9: `web/` with the `fengrid-asset://`
  path-allowlist scheme handler, blocking request interceptor, and the
  off-the-record `make_preview_profile` factory; scheme registered before
  QGuiApplication, `QtWebEngineQuick.initialize()` deliberately deferred to
  the first surface that shows a view (keeps the qa_render QThread tripwire
  quiet). `PreviewPane.qml` ships unused by the shell until M3. QA gate: 21
  tests + clean dark/light renders.
- 2026-10-19, containerized linux-x64 prod: first Docker pipeline run green
  end-to-end via `build/scripts/build-docker-linux.sh` (buildx, arch-native)
  — bundle + tarball artifact, sha256 recorded, container-side offscreen
  smoke test (`FENGRID_SMOKE=1`) passed. Findings folded back: the runtime
  mark ships from tracked `qt/resources/branding/` (branding/ stays
  gitignored), the spec is regenerated per run into
  `build/pyinstaller/<target>-<variant>/` (never committed), a root
  `.dockerignore` shrinks the context, and the artifact stage lands the full
  `dist/` tree.
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
