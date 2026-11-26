# ADR-0003 — Projects Canvas: collaborative design + code boards

- **Status:** accepted (2026-11-23) — v1 landed on `dev-qt`
- **Scope:** `qt/src/fengrid/core/canvas.py`, `bridges/canvas.py`,
  `qml/components/StudioCanvas.qml`, `api/v1` board routes
- **Relates to:** ADR-0001 (Qt6 rewrite), the Studio block-page model
  (`core/studio.py`)

## 1. Problem

The Projects pane had a *block-page* builder (Studio → Design): a vertical
tree of HTML blocks edited through forms. It is good at producing a page,
but it is not a canvas — no free placement, no zoom, no flows, no way to lay
a collection of icons next to a palette next to the snippet that uses them,
and nobody else can work on it at the same time.

The goal is a Figma-class surface that is native to Fengrid: every object on
the board can be a **live reference into the library** (the asset panes'
icons, fonts, images and media, the Colors pane's palettes, the Code pane's
snippets, collections, smart collections and saved libraries), and the
board is **collaborative** from day one.

## 2. Decision

### 2.1 Boards and nodes

- A **board** (`canvas_board`) belongs to a project (FK, cascades), carries
  a GUID like every tracked object, and stores settings (grid, background,
  last viewport) plus a Lamport-clock high-water mark.
- A **node** (`canvas_node`) is one flat row: type, parent, name, geometry
  (`x y w h rot`), stacking `z` (a real, so restacking never renumbers
  neighbours), `props` JSON, an optional `bind` locator, and flags.
- Coordinates are **board-absolute**; `parent` is membership (move, layers,
  export), not a transform. That keeps hit-testing, alignment and
  collaboration merges trivial; nested transforms can come later as an
  export concern.
- Types: `frame group rect ellipse line text sticky code connector` (drawn)
  and `icon image font palette snippet asset collection` (bound).

### 2.2 Collaboration: an op log with per-field last-writer-wins

Every edit is an op `{node, fields, clock, actor}` appended to `canvas_op`
and folded into `canvas_node`. Each field carries its own `(clock, actor)`
stamp (`stamps` column); an incoming field wins iff its stamp is greater.

Properties this buys, all covered by `tests/test_canvas.py`:

- **Convergence regardless of arrival order** — two replicas fed the same
  ops in opposite orders end identical.
- **Concurrent edits to different fields both survive** (Alice moves a
  frame while Bob recolours it).
- **Deletes are a field** (`deleted = 1`), so a stale edit cannot
  resurrect a node, and undoing a delete is an ordinary edit.
- **Edit-before-create** merges: an op for an unknown node creates an
  invisible stub that the create fills in.
- **Undo is collaboration-safe**: the bridge stores *inverse ops* and
  applies them as new local edits, never rewinding shared history.

Why not a full CRDT library (Yjs/Automerge)? The board model is a map of
small maps with no rich-text sequences, which is exactly the case where an
LWW-element map is sufficient and keeps the core dependency-free, Qt-free,
and inspectable in SQLite. Rich-text co-editing inside a single text node
(character-level merge) is the one thing this does *not* give us; it is
listed under follow-ups.

### 2.3 Transport

- **Same machine / same database:** the desktop bridge polls the board's
  head `seq` (one indexed query, ~0.9 s) and reloads only when another actor
  wrote — so a second window, a script, or the REST API all show up live.
- **Network:** the REST API exposes the join/merge surface:
  `GET /boards/{id}` (snapshot + head), `GET /boards/{id}/ops?since=&exclude=`,
  `POST /boards/{id}/ops` (`{actor, ops}`), presence heartbeats with cursors
  and selections, comments, placement by `[[ ref ]]`, and HTML/SVG export.
  Any HTTP client can be a collaborator. The existing bearer-token auth
  applies; LAN exposure carries the CORS caveats in SEC-11.

### 2.4 Library integration

- Bindings store `{kind, id, guid, slug, name}` and resolve **GUID first**,
  so nodes survive rescans that renumber rows; unresolved bindings render a
  visible *missing* placeholder, never silently vanish (same rule as
  `[[ ref ]]` expansion).
- `place_asset / place_ref / place_collection / place_smart_collection /
  place_library_view / explode_palette` drop library objects as bound nodes;
  collections land as a titled, grid-laid frame.
- Usage is indexed (`bind_kind/bind_id/bind_guid`) → `usage()` answers
  "which boards use this?", and `sync_links()` mirrors it into `asset_link`
  (project → asset, role `canvas`) so the Properties panel's Links section
  shows canvas usage without any new UI.
- **Code ↔ snippets:** a code cell can be promoted to a Code-pane snippet;
  the node becomes bound to it, so later edits in the Code pane render on
  the board.

### 2.5 Rendering and export

- QML renders nodes in a scaled `world` item (one transform for pan/zoom);
  selection chrome, grid and connectors draw in screen space so they stay
  crisp at any zoom. Drag/resize are view-local and commit **one op** on
  release.
- `render_html` → absolutely positioned HTML (code-cell CSS scoped per
  node); `render_svg` → the vector layer; `export_bundle` → `index.html`,
  `board.svg`, `board.json` (re-importable snapshot) and **copied** assets.
  All user/path-derived strings are HTML-escaped; colors pass an allowlist
  (no `url()`/`javascript:` smuggling) — tests cover the breakout cases.
- The pane's live preview renders the open board through the existing
  sandboxed WebEngine profile using `fengrid-asset://` links.

## 3. Consequences

- New tables are created by an idempotent `canvas.migrate()` called at
  startup (before bridges) and by every API entry point.
- The Projects pane gains a **Canvas** screen (now the default); the pane
  inspector hides there because the canvas carries its own.
- The op log grows with edits; `compact(keep=N)` trims it (peers further
  behind re-join from the snapshot).

## 4. Follow-ups (not in v1)

1. **QAbstractListModel for nodes** — the QML Repeater currently rebuilds
   delegates on every change; fine to a few thousand nodes, not beyond.
2. **Character-level text merge** for simultaneous typing in one node.
3. **Push transport** (WebSocket/SSE) instead of polling for remote peers;
   the op format does not change.
4. **Auto-layout frames** (flex-like stacks) and **components/instances**
   bridged to Studio's `component` pages.
5. **Export frames as Studio pages** so a board can graduate into the
   page builder / Docker pipeline.
6. Postman collection entries for the board routes (OpenAPI is updated).
