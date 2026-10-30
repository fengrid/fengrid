# ADR-0003 — Projects pane overhaul: native canvas editor (OpenPencil-parity)

- **Status:** proposed (2026-10-29). The three scope questions below were put to
  the user and timed out unanswered; the **recommended defaults are taken** and
  flagged so they can be vetoed before implementation starts.
- **Driver:** user direction — the Projects pane should carry the functionality
  and interactivity of [OpenPencil](https://github.com/open-pencil/open-pencil)
  (an open-source Figma-class design editor), implemented in Fengrid's
  Qt6/QML/PySide6 architecture and integrated with Fengrid's asset management
  and taxonomy. "The core of the Fengrid project — the most functional and
  polished portion."
- **Workspace:** branch `feat/projects-pane-overhaul` off `v1.0.0-rc1-testing`
  (b4d766f); worktree at
  `.git/modules/projects/fengrid/.worktrees/projects-pane-overhaul`.
  Note: `qt/.venv` is untracked and stays in the main checkout — run tests/QA
  from the worktree with
  `/home/agents/agents/projects/fengrid/qt/.venv/bin/python` (verified:
  `test_icon_raster.py` 24 passed from the worktree).

## 1. Background

The current Projects pane (`qt/qml/components/Projects.qml`, ~2,000 lines) is
a **design-token configurator**: project sidebar → studio screen rail +
parameter forms (palette roles, radius, prefix, body/heading families, base
size + modular scale, icon size) → asset list → WebEngine WYSIWYG preview of
the boilerplate → bottom dock (console / logs / revisions / ask) → status bar.
Interaction is form-driven; the preview is a rendered HTML mirror of the
export, not an editing surface.

OpenPencil is a canvas-first editor. Its interactivity inventory (from the
README/docs):

- Infinite canvas: pan (scroll / space-drag), zoom toward cursor (Ctrl+wheel)
- Node tree: frames, groups, rectangles, ellipses, lines, text, images
- Direct manipulation: click / shift / marquee selection, drag-move, 8 resize
  handles + rotation, double-click to enter groups, snapping
- Layers panel: tree, drag-reorder, visibility/lock, rename
- Per-node properties panel (geometry, fill/stroke, radius, opacity, text)
- Tools + keyboard model (V/F/R/O/L/T/H, Escape), toolbars
- Undo/redo (inverse command pattern, batched)
- Components & variants, instances; auto layout (flex) & CSS grid
- AI chat that edits the document through tools; CLI/XPath/MCP programmability
- Real-time collaboration (WebRTC/Yjs: cursors, presence, follow, voice)

## 2. Decision

### 2.1 Target interaction model *(default taken — Q1 unanswered)*

**Replace** the pane's middle workspace (screen rail + parameter forms +
WebEngine preview) with a native QML canvas editor. **Keep:** the project
sidebar (search, list, context menus), header actions (name / export / run /
demo), and the bottom dock (console / logs / revisions / ask + source). The
parameter forms move into a collapsible **project-settings drawer** — they
remain the source of truth for token export. The pane's WebEngine dependency
retires with the preview (other panes' WebEngine tiers are untouched).

### 2.2 Rendering architecture

- A single `QQuickPaintedItem` subclass (Python) paints the node tree; the
  world→view transform carries pan/zoom. Software-renderer-safe by
  construction; **no ShaderEffects anywhere in the pane** (offscreen QA skips
  them silently; the software fallback segfaults on layer effects on real
  displays — qt-qml-ui skill).
- Interaction overlays — marquee, handles, snap guides, cursor feedback — are
  plain QML `Item`s layered above the painted canvas; they never live inside
  the paint item.
- Icon nodes render through the existing crisp-raster pipeline
  (whole-device-pixel strokes, center snap, `sourceSize` at device DPR) so
  glyphs stay sharp at every zoom level.
- Alternatives rejected: per-node Repeater delegates (model-churn/use-after-free
  pitfall class, O(N) items, no z-order painting control), keeping WebEngine
  (fragility tier, no native interaction). Scene-graph custom geometry is a
  later optimization if profiling demands it, not an M1 dependency.

### 2.3 Scene model & persistence

- New `core/scene.py` (SQLite via `core.db.connect()`): `scene_node` —
  project, page, parent, kind (`frame|group|rect|ellipse|line|text|image|icon|
  instance`), x/y/w/h/rotation, z, locked, hidden, name, props JSON
  (fill/stroke/radius/text/font/asset_ref). Pages reuse the existing studio
  page concept.
- Taxonomy reuse: node tags / custom fields ride the existing taxonomy tables;
  node↔asset and node↔node relations prefer real typed links (`asset_link`,
  extending linkable kinds with `scene_node`) over props-encoded refs.
- New `bridges/scene.py` (QObject): **cached** list properties + change
  signals (never query SQLite inside a QML property getter — the N+1 pitfall),
  CRUD/mutation slots, batch operations folded through `bridges/undo.py` +
  `core/history.py` so every canvas mutation is one undoable command.
- Revisions keep flowing through the existing source-control/revision dock —
  canvas saves produce revisions like any other project change.

### 2.4 Capability mapping

| OpenPencil capability | Plan |
| --- | --- |
| Infinite canvas pan/zoom (toward cursor) | M1 |
| Node tree (frames/groups/shapes/lines/text/images) | M1 (image/icon via assets), instances M3 |
| Direct manipulation: select/marquee/move/resize(8)/rotate, enter group | M1 |
| Snapping (edges/centers/spacing) + alignment guides | M1 |
| Layers panel: tree, reorder, hide/lock, rename | M1 |
| Properties inspector (geometry) | M1 |
| Tools + keyboard model (V/F/R/O/L/T/H, Esc) | M1 |
| Undo/redo, batched | M1 (existing undo bridge) |
| Copy/paste/duplicate, z-order, group/ungroup, lock/hide | M1 |
| Properties: fill/stroke/text bound to project tokens | M2 |
| Asset drag-drop / insert from the Fengrid library | M2 |
| Taxonomy on nodes (tags, custom fields, links) | M2 |
| Export selection/frame (PNG/SVG) via existing pipeline | M2 |
| Components & variants (presets/snippets as components) | M3 |
| AI chat editing the canvas via tools (evolve `ask` dock) | M3 |
| Auto layout (flex/grid constraints) | Deferred (stretch) |
| Real-time collaboration (WebRTC/Yjs, voice) | **Out of scope** — single-user desktop |
| .fig import/interop, MCP server / external CLI | Deferred |

### 2.5 Fengrid integration (the differentiator, M2)

- **Asset shelf + drag/drop + insert menus:** icons, fonts, palettes,
  snippets, presets drop onto the canvas as `asset_ref` nodes (reuses
  `projects.add_asset` / `core/assetrefs.py`).
- **Palette-bound fills:** color pickers enumerate the project's palette roles
  (`apply_palette` path); role recolors propagate to bound nodes.
- **Typography-bound text:** text nodes default to the project's body/heading
  families and modular scale.
- **Taxonomy on nodes:** tag / custom-field / typed-link editors in the
  inspector; saved libraries and smart collections drive the shelf's filters;
  the layer tree can filter by tag.
- Selection/context-menu convention holds: left-click selects, right-click
  opens the menu for the current selection.

## 3. Milestones

- **M1 — editor core.** Scene model + paint canvas + pan/zoom + selection
  (click/shift/marquee) + move/resize/rotate + snapping + z-order/group +
  undo/redo + layers panel + tool shortcuts. *Acceptance:* headless QA render
  of a seeded scene (`QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software`),
  pytest coverage for `core/scene` CRUD + undo batching, interaction driven
  through the app's QA route flags (never xdotool focus dependence), shortcut
  `enabled` gating per the overlay singleton rule, SplitView min-width
  arithmetic checked at the smallest supported window.
- **M2 — Fengrid integration.** Asset shelf/drop, palette + typography token
  binding, taxonomy editors, text editing, export paths, properties polish.
- **M3 — parity stretch + polish.** Components/instances, auto-layout-lite if
  wanted, `ask` → scene tools, minimap/zoom-to-fit extras, in-pane help guide
  update (every pane carries one), CHANGELOG.

## 4. Risks / pitfalls carried in from prior cycles

- No Repeater models bound to expressions that re-evaluate during delegate
  interaction; no SQLite reads inside property getters; per-row full-list
  scans forbidden (the `pathEnabled` O(N²) class).
- Shortcuts: publish transient-input state on a singleton and OR it into
  every window Shortcut's `enabled` (canvas tools must not eat palette/
  capture keys).
- QML comments are `//` only; boot the engine after multi-patch edits;
  QVariantList is not a JS Array (copy element-wise, assign once).
- `Dialog` FINAL-property redeclaration; lazy `Loader` for FileDialogs
  (portal freeze); open-before-fetch for dialogs launched from buttons.
- Verify every visual claim with a measured render + PIL pixel-sampling, not
  vision opinion; pixel-sample claimed defects before fixing them.

## 5. Open questions (defaults taken while confirmation timed out)

1. **Interaction model** — default: native canvas editor replaces the middle;
   params → drawer. Alternative held: canvas as an additional mode/tab with
   the configurator intact.
2. **Deferred capabilities** — default: collaboration and .fig interop out;
   auto-layout and MCP deferred behind M3.
3. **Sequencing** — default: editor core (M1) before Fengrid integration
   (M2). Alternative held: integration first on a simpler canvas.
