# Fengrid — Brand Package

> One of three finalist name candidates for the gtk4-icon-browser project. Written for review; nothing has been renamed or published yet.

---

## 1. Brand Strategy

### 1.1 The name

**Fengrid** — *FE* (frontend) + *grid*, with a hidden second reading: *fen* (window) + *grid* = **a grid of windows**. Every asset card in the UI is a small window onto a file — the name unknowingly preserves the entire window/showcase metaphor family inside a single word.

The name makes a **visual promise**: the product *is* a grid — the icon browser's core experience is a resizable asset grid with a size slider. Where Fendex names the architecture, Fengrid names the experience: open it and you are looking at a grid.

Growth runway: icons, fonts, and CSS snippets all present naturally as grids. The metaphor is presentation-level, not asset-type-specific, so it survives the scope expansion cleanly.

### 1.2 Positioning statement

> **Fengrid turns everything on your machine into a grid.** Icons, fonts, styles — every frontend asset you own, laid out, searchable, and inspectable on one local page. No cloud, no account, no build step.

Positioning pillars:

1. **See everything at once.** The grid is the brand: whole-collection visibility, zoomable from 16px to 256px, on one page.
2. **Local-first, always.** (Shared pillar across all three candidates — this is the product's identity regardless of name.)
3. **Every card is a window.** Tap/click any asset and you're through the glass: variants, dimensions, path, export. Use this line in copy; it's the name's built-in story.
4. **Cross-platform, zero-dependency.** Linux, macOS, Windows; single file; works offline.

### 1.3 Audience

- Primary: frontend developers and design-engineers who think in grids (CSS Grid natives).
- Secondary: themers/ricers; icon-pack authors checking their packs; anyone curating a personal asset library.

### 1.4 Voice & tone

Slightly warmer than Fendex, still tool-plain:

- Lead with sight-words: *see, lay out, browse, scan, spot*.
- Comfortable with a little delight ("a grid of windows onto your machine") but never cutesy.
- Precise numbers still matter (sizes, counts, file sizes — the inspector data is the proof).

### 1.5 Tagline candidates

1. **Every asset on your machine, on one grid.** (primary recommendation)
2. A grid of windows onto what you own.
3. See your whole asset drawer at once.
4. Browse what you own, at a glance.

### 1.6 Naming system (future modules)

- **Fengrid** — the umbrella app; asset types are *panes* of the grid (Icons pane, Fonts pane, Styles pane).
- The "grid of windows" story scales: each asset type is literally a pane in a larger fenestration. Module naming can stay descriptive rather than coined.

### 1.7 Risks & mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| Misread as a CSS grid-layout tool (a grid *generator*) | **Medium — the defining risk** | Always pair the name with a concrete subtitle: "Fengrid — the UI asset explorer." First-paragraph descriptions must name icons/fonts/styles explicitly. Never describe the product as "a grid tool" without "asset" in the same sentence. |
| Trivial existing uses: an Amazon toner-cartridge storefront ("FenGrid"), a private Instagram | Low | Unrelated industries, no software use found (2026-10-18). SERP is weak commercial pages — an active project should out-rank them within months. |
| Reads slightly like a personal name ("Feng + rid") | Low | harmless; wordmark styling (lowercase `fengrid`, mono accent on `grid`) resolves it. |

### 1.8 Verified availability snapshot (2026-10-18)

- npm `fengrid`: **free**
- PyPI `fengrid`: **free**
- `fengrid.dev`, `fengrid.io`: **likely available** (RDAP check; confirm at purchase)
- Web: no software collisions; SERP occupied only by printer-toner listings and personal accounts — the cleanest SERP path of the three finalists.

---

## 2. Brand Identity Specification

### 2.1 Logo concept — FINALIZED (2026-10-18)

**Chosen mark: the "glint quad".** A 2×2 grid of rounded glass panes. Three panes are teal outlines with a diagonal **glass-glint** streak; the bottom-right pane is filled with an amber gradient, carries a small specular dot, and emits a soft radial glow that fades to zero inside its radius (no hard edges). The story: three empty slots, one found-and-lit asset — the moment an asset is found *is* the brand moment.

Implemented variants in `assets/` (canonical SVGs; PNGs are renders):

- `fengrid-mark.svg` — dark-theme colors, transparent background (primary)
- `fengrid-mark-light.svg` — light theme; glints are slate (white reflections don't exist on light ground)
- `fengrid-mark-mono.svg` — single-color via `currentColor`; opacity-tinted glints, no glow/dot
- `fengrid-glyph.svg` — favicon variant: chunkier strokes (44), glints/dot dropped, amber kept — detail is removed but the silhouette is preserved below ~48px
- `fengrid-wordmark.svg` / `-light.svg` — horizontal lockup: mark + `fen` (Inter SemiBold) + `grid` (Noto Sans Mono Bold, teal accent); the color split lands exactly on the name's two halves
- `fengrid-og.svg` — 1200×630 social banner (single ghost pane top-right, clear of all text)
- `hero-illustration.png` — optional AI-generated decorative hero (see `README.md` caveats)

Rejected during exploration (kept in `assets/candidates/` for the record): flat quad (inert baseline), bento mosaic (strong but five-shape silhouette weak at favicon size), ajar casement (most narrative but needs a dedicated small-size variant), dusk glass (fill contrast too low on dark ground).

- Do not use: literal OS window chrome, spreadsheets, masonry imagery, or a second warm accent — one lit pane per composition, always.

### 2.2 Typography

- **Wordmark & UI:** geometric-grotesque sans (e.g. Inter, Space Grotesk) — the grid deserves a typeface with even, cell-like rhythm.
- **Signature detail:** the wordmark's letters sit on an implied grid — slightly wider tracking than Fendex's, optically aligned to a 4px base grid.
- **Mono accent** for `grid` in `fengrid`, CLI examples, and data readouts (dimensions, file sizes) — the inspector's numbers set in mono is a brand moment.

### 2.3 Color palette

Glass-and-daylight: cooler than Fendex, oriented to the "window" reading.

| Role | Light theme | Dark theme |
|---|---|---|
| Background | `#F7F8F9` (daylight white) | `#101418` (night glass) |
| Foreground/text | `#16202B` | `#E7EDF2` |
| **Accent (primary)** | `#0E7C86` (pane teal) | `#39B8C4` |
| Secondary | `#6B7A88` (frame gray) | `#93A3B0` |
| Lit-pane highlight | `#F5B841` (warm light through glass) | `#F5C25C` |

Rationale: teal = glass/pane; the single warm amber "lit pane" accent gives the logo and UI one focal pop, echoing the mark. Dark theme remains primary (hero screenshot is dark).

### 2.4 Iconography

Two strong options — **user decision required** (standing preference: never emoji):

1. **Feather Icons** (default) — clean 24px/2px-stroke, matches the precise grid.
2. **Dooodle Icons** — hand-drawn warmth; pairs charmingly with "little windows" but loosens the grid discipline.

Recommendation: **Feather** for UI chrome; reserve Dooodle only if the brand later wants a friendlier community face.

### 2.5 UI theming rules

- The asset grid *is* the hero visual; screenshots should always show the grid with varied tile sizes (16/32/64px mix) to demonstrate the size slider.
- The "lit pane" accent maps to selection/hover/inspector-open states in the UI — brand and interaction share one device.
- Filter chips remain swipeable and rounded; keep touch targets large in mobile screenshots.

### 2.6 Wordmark usage

- Lowercase in text: `fengrid`. Spoken form: "FEN-grid" (or playfully "fen-GRID" when emphasizing the grid — pick one in docs; recommend FEN-grid).

---

## 3. Launch & Migration TODO

Phase 0 — claim:
- [ ] Purchase `fengrid.dev` + `fengrid.io` (both verified likely available — unusually cheap to lock down both)
- [ ] Register `fengrid` on npm and PyPI (both verified free; defensive placeholder)
- [ ] GitHub repo rename → `nativeit/fengrid` (auto-redirect from old name)

Phase 1 — code migration:
- [ ] Update README, QUICKSTART.md, install.sh, install.ps1, page `<title>`/meta, CHANGELOG
- [ ] Rename single-file HTML asset + installer outputs; changelog compatibility note
- [ ] Update GitHub Pages links; tag release `v0.3.0 — "Fengrid"`

Phase 2 — web presence:
- [ ] Custom domain or `fengrid.nativeit.dev`, public (auth gate removed)
- [ ] Landing page rebuilt around the grid: animated lit-pane hero, positioning statement, tagline #1
- [ ] Meta description targets "UI asset grid", "icon grid", "font browser", "offline"
- [ ] FAQ line killing the misread explicitly: "Not a CSS grid framework — a grid of your assets."

Phase 3 — announcement:
- [ ] Launch post leading with the visual story: a GIF of the size slider sweeping 16→256px (the product demo *is* the brand demo)
- [ ] Show HN / r/linux / themer communities
- [ ] Monthly SERP check on "fengrid" until the top page is yours

Standing rule for this candidate: **the word "grid" never appears without "asset" or "UI" nearby** — "asset grid," "UI grid," never bare "the grid" in external copy.
