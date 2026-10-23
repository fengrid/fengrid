# ISSUES — v1.0.0-rc1-testing review

Findings from the pre-release evaluation (security, performance,
accessibility, UI quality). Each item maps to a GitHub issue (links in
the GitHub Issues section below). Do not fix here — track in issues.

## Security — HIGH

### SEC-1 · Script-tag breakout via expanded asset paths in JS context
- `qt/src/fengrid/bridges/code.py:220-228` (`fiddle_doc`)
- `exp_js` (user JS with `[[ ref ]]` expansion) is concatenated inside a
  `<script>` element. A resolved asset path containing `</script>`
  (legal in filesystem paths) breaks out of the script element and
  injects arbitrary HTML/JS into the preview document.
- Fix: context-sensitive escaping before concatenation (escape `</script`
  → `<\/script` for JS; `"`/`&` for attribute contexts).

### SEC-2 · HTML attribute injection via asset paths and markdown URLs
- `qt/src/fengrid/core/assetrefs.py:165-169` (`url_for`)
- `qt/src/fengrid/bridges/projects.py:326-330` (`preview_html`)
- `qt/src/fengrid/core/snippets.py:454-457` (`_md_inline`)
- `url_for()` returns `fengrid-asset://<abs path>` unescaped; a path
  containing `"` breaks out of the surrounding HTML attribute.
  Markdown image/link URLs are interpolated into `src`/`href` without
  escaping — `![alt](http://x"><script>…)` injects inline script.
- Fix: escape path segments in `url_for()` when embedded in HTML;
  HTML-escape URL and text in `_md_inline()`.

### SEC-3 · Unbounded memory on crafted rasters
- `qt/src/fengrid/core/indexer.py:107-110` (`identify`)
- `im.convert("RGB")` runs before the dimension check; a small file
  with a claimed 100000×100000 header can force ~30 GB allocation
  before the resize cap applies.
- Fix: check `im.width * im.height` against a sane cap (e.g. 256 Mpix)
  before `convert()`; skip color counting for huge rasters.

### SEC-4 · Optional defusedxml → billion-laughs on crafted SVG
- `qt/src/fengrid/core/indexer.py:31-37`
- Without `defusedxml` installed, stdlib ElementTree parses SVGs and is
  vulnerable to entity-expansion (billion laughs); the 4 MB byte cap
  does not help.
- Fix: make `defusedxml` a hard dependency, or reject SVGs containing
  DOCTYPE/entity declarations when it is absent.

## Security — MEDIUM

### SEC-5 · Symlink escape via `rglob("*")`
- `qt/src/fengrid/core/ingest.py:231` (import_folder sniff), 275, 286
  (`index_materialised` font sniff); `qt/src/fengrid/core/watch.py:119`
- `Path.rglob` follows directory symlinks (Python ≥3.10), so a symlink
  inside an import/watch root can walk the whole filesystem. The
  scanners themselves use `os.walk(followlinks=False)` correctly.
- Fix: replace `rglob` uses with `os.walk(..., followlinks=False)`.

### SEC-6 · Decompression / disk-fill bomb in `import_zip`
- `qt/src/fengrid/core/ingest.py:186-187`
- Members are streamed (64 KB buffer) but there is no per-member or
  total uncompressed-size cap; a 1 MB zip at 1:10000 ratio can fill the
  disk. Member count is capped (100 000).
- Fix: per-member byte budget (e.g. 500 MB) + total cap; abort import
  when exceeded.

### SEC-7 · ReDoS in user-supplied import regex
- `qt/src/fengrid/core/patterns.py:25-33` (`apply_regex`)
- `re.sub(find, repl, stem)` has no timeout; a pathological pattern
  burns CPU per filename. Invalid regex is caught, catastrophic
  backtracking is not.
- Fix: compile with timeout guard or reject obviously-nested patterns.

### SEC-8 · Local file read via DB-injected paths (scheme allowlist)
- `qt/src/fengrid/web/handlers.py:33-48`
- Allowlist is a plain `SELECT 1 FROM asset WHERE path = ?`. Any row
  pointing at an arbitrary file (crafted import, direct DB edit) makes
  the scheme handler serve that file. Scanner resolves realpaths, but a
  post-scan symlink swap defeats it.
- Fix: verify resolved path is under registered source roots at serve
  time, or record resolved-path checksums and validate.

### SEC-9 · OOM on “orig” export of huge rasters
- `qt/src/fengrid/core/export.py:62-73`
- `size="orig"` opens and converts a full-resolution image with no
  dimension cap (numeric sizes are clamped 8..1024, “orig” is not).
- Fix: max-dimension / max-pixel cap before `convert()`.

## Security — LOW

### SEC-10 · Information disclosure via `/links/expand`
- `api/v1/resources.py` (`links_expand`)
- An authenticated consumer can enumerate valid slugs/GUIDs and obtain
  absolute filesystem paths of indexed assets. localhost-only by
  default, but maps the FS when the API is exposed.
- Fix: rate-limit; consider redacting absolute paths for low-privilege
  tokens.

### SEC-11 · Overly permissive CORS on the API
- `api/v1/middleware.py:82-86`, `api/v1/server.py:231-244`
- `Access-Control-Allow-Origin: *` unconditionally; default bind is
  loopback but `--host 0.0.0.0` is supported.
- Fix: Origin allowlist / echo; document LAN exposure risk.

### SEC-12 · Unbounded markdown/HTML rendering
- `qt/src/fengrid/core/snippets.py:482-581`
- `markdown_doc` processes arbitrarily large input in memory.
- Fix: size cap (e.g. 1 MB) at entry points.

## Security — protections already verified (no action)
- Zip-slip blocked (member flattening to basename), streamed 64 KB
  copies, atomic `os.replace()` writes, argv-only subprocesses (no
  shell), symlink-cycle guards in scanners, chunked BEGIN IMMEDIATE
  commits, parameterised SQL everywhere, preview profile lockdown
  (no file/remote access from local content, no clipboard, off-the-
  record), token required on every API route (401 verified live).

## Performance / Architecture

### PERF-1 · Startup time — duplicate font walk + sync fontTools
- Severity: Medium-High. Mixed root cause (architecture + impl).
- `fonts.rescan` pre-counts via a full walk, then `scan_fonts` walks
  again; fontTools identification (~5-20 ms/file) runs serially on one
  QThread while holding WAL write locks in chunks. ~1000 fonts ≈ 5-20 s.
- Fix: cache pre-count, parallelise identification, lazy bridges.

### PERF-2 · Full-table `scan_state` load per source during rescans
- `qt/src/fengrid/core/indexer.py:325-330`
- Loads every scan_state row into Python to filter stragglers
  (~10-20 MB at 100k assets), per source, on every rescan.
- Implementation root cause. Fix: SQL-side
  `DELETE FROM scan_state WHERE path LIKE ? ESCAPE '\'` (helper
  `_like_escape` already exists in indexer.py).

### PERF-3 · Markdown preview regeneration on every keystroke
- `qt/qml/components/Code.qml` (`updateMarkdown`/`refreshHighlight`)
- Regex highlight + full markdown→HTML + `loadHtml` per keystroke on
  the main thread; jank on documents of a few KB+.
- Implementation root cause. Fix: 150-200 ms debounce; consider worker
  thread for large docs.

### PERF-4 · SQLite WAL contention between scan workers and UI writes
- Severity: Medium; architecture root cause but well-mitigated already
  (chunked BEGIN IMMEDIATE, timeout=30). A font-scan chunk can still
  hold the write lock ~1.5 s.
- Fix: defer/queue main-thread writes during active scans instead of
  blocking; keep chunking.

### PERF-5 · ThreadingHTTPServer adequate for v1.0
- Low for the localhost profile; if remote exposure is ever needed,
  wrap resources in an ASGI adapter rather than rewriting the data
  plane. No action for v1.0; documented.

## Accessibility / UI quality

### A11Y-1 · SideRail is mouse-only — no keyboard navigation
- `qt/qml/components/SideRail.qml`
- 0 `Keys.onPressed`, 0 `KeyNavigation`, no focus handling; rail
  sections/tabs unreachable by keyboard alone.
- Fix: KeyNavigation attached properties + focus ring on RailItem.

### A11Y-2 · Icon-only buttons lack Accessible.name
- PaneTab (SideRail), IconButton usages across panes rely on ToolTip
  only; screen readers announce nothing meaningful.
- Fix: `Accessible.name` on every icon-only control.

### A11Y-3 · Color-only signaling
- Clean/dirty pill (SourceControlPanel) and the red uncommitted-changes
  footer text in Main.qml signal state by color; red on surface is
  4.4:1 (passes AA only at large size). Section collapse chevrons
  rotate but sections do not expose expanded state to a11y.
- Fix: add text/aria equivalents (`Accessible.description`), consider
  an icon+text pair.

### A11Y-4 · Contrast: LIGHT Chip off-state 3.9:1
- `textMuted #6B7A88 on surface2 #EEF1F3` in the light theme is below
  AA 4.5:1 for small text. All dark-theme pairs verified PASS.
- Fix: darken light-theme textMuted one step.

### UI-1 · Minor cosmetic (for TODO, no issue)
- Settings → Source control button labels inconsistent ("Apply_push"
  vs "Run maintenance"); button widths differ.
- Hardcoded rgba overlays in Colors.qml SwTool backgrounds bypass the
  token system (`#40000000` / `#25000000`).
- Fonts pane: with zero fonts indexed, the collapsible Types/Families
  sections are hidden entirely (expected, but the chevron affordance
  then can't be discovered — mention in tooltip/hint).

## Console errors (console.log, recorded at repo root)

- `Main.qml` Shortcut warning ×2: "Only binding to one of multiple key
  bindings associated with 11/12. Use 'sequences: [ <key> ]'" — benign
  but should be migrated to `sequences`.
- No QML TypeErrors/ReferenceErrors remain after the cached-probe fix.
- libEGL/GPU warnings are environment-only (headless CI), not app bugs.

## GitHub issues opened

(see the PR comment for the live list; each SEC-x/PERF-x/A11Y-x above
with high/medium severity has a matching issue.)
