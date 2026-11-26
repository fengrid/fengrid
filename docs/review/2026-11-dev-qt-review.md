# dev-qt review — 2026-11-23

Scope: the Projects pane (Studio), its bridges/core, the asset-reference and
taxonomy layers it builds on, the REST API router, and shared QML theming.
Method: read-through plus headless reproduction. Each "fixed" item has a
regression test that fails on the pre-change tree and passes after.

Environment note: this pass ran without a display or PySide6, so the
QML-loading tests (`test_qml_*` that construct an engine) and anything
importing a bridge were **not executed here**. They need a run on a
machine with the Qt toolchain (see "Verify locally" at the end).

## Fixed in this change

| # | Area | Finding | Fix | Test |
|---|------|---------|-----|------|
| F1 | `core/studio.py` | **Snippet blocks never rendered.** `_snippet_body` selected a nonexistent `body` column; the bare `except Exception: pass` turned the `OperationalError` into "missing" for every snippet block on every page. | Read `html`/`css`, emit CSS in a `<style>` (with `</` escaped); no blanket except. | `test_canvas.py::test_studio_snippet_block_renders` |
| F2 | `core/studio.py` | `_ref()` inserted `assetrefs.url_for()` output into `src` **unescaped** — the SEC-2 class, missed in this renderer. | Escape the URL like every other attribute. | `test_canvas.py::test_studio_image_ref_escaped` |
| F3 | `api/v1/server.py` | **Router passed query params positionally before path params**, so every handler shaped `(ctx, body, item_id, params)` received swapped arguments. `GET /assets/data/{id}/points` answered 500 on every call. | Bind path and query params by name. | `test_api.py::test_points_get_route_binds_params_by_name` |
| F4 | `api/v1/server.py` | Query strings were split by hand and only `%20` was decoded: `?q=a%26b`, `+`, `%2B` reached handlers still encoded. | `urllib.parse.parse_qsl`. | `test_api.py::test_query_params_fully_decoded` |
| F5 | QML theming | `theme.tokens.*` are **strings**; `Toast.qml`, `Main.qml` (header gradient) and `CommandPalette.qml` read `.r/.g/.b` off them, which is `undefined`, so those translucent tints never applied. | Convert via `Qt.lighter(token, 1.0)` first. | visual — verify locally |
| F6 | `Projects.qml` layout | Screen column **capped at 420 px** → on wide windows everything past it was dead space between the screens and the inspector. Upper/lower split fixed at 55 %. Screen checks compared raw indices (`studioScreen === 0`), so inserting a screen would silently retarget them. | No cap; draggable, per-screen split with collapse; key-based screen checks; collapsible project list; segmented screen rail. | `test_qml_projects_layout.py::test_screen_column_has_no_width_cap` (+ updated existing tests) |
| F7 | `core/projects.py` | Deleting a project left its `asset_link` rows (polymorphic, no FK) behind. | Delete both directions with the project. | `test_canvas.py::test_project_delete_drops_its_links` |

## Outstanding — recommended, not changed here

- **O1 · Orphaned polymorphic rows (medium).** `collection_ref`,
  `item_tag`, `item_field_value` and `asset_link` reference items by
  `(kind, id)` with no FK. `delete_snippet` and `delete_palette` remove only
  their own row, so their tags, fields, collection memberships and links
  outlive them (the indexer cleans asset rows on rescan; nothing cleans
  snippets/palettes). Suggest one `core.db.purge_item(con, kind, id)` called
  from every delete path, plus a one-off maintenance sweep in Settings →
  Database.
- **O2 · Silent excepts (medium).** F1 survived because of a blanket
  `except Exception: pass`. Nine such sites remain (indexer, backup, fonts,
  probes). Probes are fine; the indexer/backup ones should at least log
  via `qtlog`.
- **O3 · `taxonomy.related_by_tags` is N+1 (low/perf).** One query per
  candidate per shared tag; it runs on every Properties-panel open. A single
  grouped query (`GROUP BY item_kind, item_id` with `group_concat(t.name)`)
  does the same work.
- **O4 · Studio button `href` (low).** `javascript:` URLs pass through to
  exported sites (the preview sandbox mitigates; exports don't). Allowlist
  `http(s):`, `mailto:`, `#`, and relative paths.
- **O5 · UI-thread DB work.** Bridges (Studio, Canvas) do synchronous
  SQLite work in slots. Fine at current scale; the canvas node model
  should move to a `QAbstractListModel` with row-level updates before
  boards reach thousands of nodes (ADR-0003 §4).
- **O6 · Repo-root clutter.** `list.txt` (745 KB), `meta-state.tsv.new`
  (475 KB) and `console.log` sit in the repo root, against the
  DEVELOPMENT.md rule. If they're tracked, move them under `qa/` or
  ignore them.
- **O7 · Postman** does not list the new board routes yet (OpenAPI and
  the API README do).

## Verify locally (needs the Qt toolchain)

```bash
cd qt
.venv/bin/python -m pytest tests/test_canvas.py tests/test_api.py \
    tests/test_qml_projects_layout.py tests/test_qml_bridge_callnames.py -q
QT_QPA_PLATFORM=offscreen FENGRID_NO_RELAUNCH=1 \
  .venv/bin/python -m fengrid --screenshot /tmp/fg-canvas.png --pane 4 --no-scan
```

`pyside6-qmllint qml/components/StudioCanvas.qml qml/components/Projects.qml`
is worth a run too — this pass checked bracket balance, id uniqueness
and the bridge call-name rule statically, but not types.

### Verified locally — 2026-11-24

Ran on a machine with PySide6 6.9.3 (offscreen). Full suite: **640 passed**.

- Three `test_qml_projects_layout.py` tests failed first; both causes were
  in the test harness, not in the pane: the fixture never hosted the pane
  in a window, so Qt Quick Layouts never re-polished after a screen switch
  toggled the inspector's visibility (stale 0-width geometry), and the
  `BOARDS` header is an inline `PanelLabel` type the `QQuickText` walk
  skipped. The fixture now uses a `QQuickWindow`, like the other QML tests.
- `--screenshot --pane 4` renders the Canvas screen. Fixed one visual
  defect there: the empty-board copy overflowed the board column at
  1280 px; it now wraps inside it.
- `pyside6-qmllint` reports no errors on `StudioCanvas.qml` /
  `Projects.qml`.
