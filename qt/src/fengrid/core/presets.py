"""Curated preset asset libraries: open-source fonts, icon sets and
static-site themes/templates hosted on GitHub.

Design contract (user spec):
- Preset libraries are tracked like any other library (taxonomy kind
  "preset", entries kind "preset_entry" — taggable, slug/GUID carrying,
  visible in the inspector) but are marked REMOTE: nothing is cloned
  until the user asks for a specific entry.
- Entries hold name/URL/metadata ONLY — no font/icon/template files
  ship with Fengrid; the preview grid shows a remote placeholder until
  an entry is cloned, then a preview is derived from the repo's
  README.md imagery / social images.
- Cloning goes through Fengrid's built-in git wrapper
  (core.projects_git.Repo.clone) using the entry's configured source
  URL and branch.

Descriptions/tags below were curated from the projects' own READMEs
and GitHub descriptions; the license column is filled only where the
project states it unambiguously.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path

# ---------------------------------------------------------------- data


def _e(name, repo, desc, tags, license="", homepage="", branch=""):
    return {
        "name": name, "repo": repo,
        "url": f"https://github.com/{repo}.git",
        "branch": branch, "description": desc, "tags": tags,
        "license": license, "homepage": homepage,
    }


def _c(name, desc, colors, tags, license="", homepage=""):
    """Palette-kind preset entry (color harmony, no remote URL)."""
    return {
        "name": name,
        "repo": "",
        "url": "",
        "branch": "",
        "description": desc,
        "tags": tags,
        "license": license,
        "homepage": homepage,
        "colors": colors,
    }


PRESET_PACKS = [
    {
        "name": "Open Fonts",
        "kind": "font",
        "summary": "Curated open-source font families on GitHub. Browse "
                   "the catalogue freely — a family is only cloned into "
                   "your library when you download it.",
        "tags": "fonts, webfonts, opensource, typography",
        "entries": [
            _e("Inter", "rsms/inter",
               "Variable typeface carefully designed for computer "
               "screens, with extensive OpenType features.",
               "sans-serif, variable, ui, web, modern",
               "SIL OFL 1.1", "https://rsms.me/inter/"),
            _e("Fira Code", "tonsky/FiraCode",
               "Free monospaced font with programming ligatures; the "
               "most popular coding font on GitHub.",
               "monospace, coding, ligatures",
               "SIL OFL 1.1", "https://tonsky.me"),
            _e("JetBrains Mono", "JetBrains/JetBrainsMono",
               "Typeface for developers: increased letter height for "
               "reading comfort, 145+ languages, ligatures.",
               "monospace, coding, ligatures",
               "SIL OFL 1.1", "https://jetbrains.com/mono"),
            _e("IBM Plex", "IBM/plex",
               "IBM's corporate typeface family: Sans, Serif, Mono and "
               "Condensed with TrueType, Webfont and IBM Power fonts.",
               "sans-serif, serif, mono, corporate",
               "SIL OFL 1.1", "https://ibm.com/plex"),
            _e("Cascadia Code", "microsoft/cascadia-code",
               "Fun new terminal font with programming ligatures, "
               "shipped with Windows Terminal.",
               "monospace, terminal, coding, ligatures",
               "SIL OFL 1.1"),
            _e("Roboto", "googlefonts/roboto",
               "The Roboto family — Android's default neo-grotesque "
               "sans, now fully variable.",
               "sans-serif, android, web, neo-grotesque",
               "SIL OFL 1.1"),
            _e("Noto Fonts", "notofonts/notofonts.github.io",
               "Home of the Noto project: fonts for every script, "
               "covering 1000+ languages — no more tofu.",
               "multilingual, unicode, sans-serif, serif",
               "SIL OFL 1.1", "https://notofonts.github.io"),
            _e("Source Han Sans", "adobe-fonts/source-han-sans",
               "Open-source Pan-CJK typeface family (Adobe & Google) "
               "covering Simplified/Traditional Chinese, Japanese and "
               "Korean.",
               "cjk, chinese, japanese, korean, sans-serif",
               "SIL OFL 1.1"),
            _e("Montserrat", "JulietaUla/Montserrat",
               "Urban sans-serif typeface inspired by old signs and "
               "posters of the Montserrat neighbourhood, Buenos Aires.",
               "sans-serif, display, geometric",
               "SIL OFL 1.1"),
            _e("Open Sans", "googlefonts/opensans",
               "Humanist sans serif typeface by Steve Matteson — "
               "optimized for print, web and UI.",
               "sans-serif, humanist, web, ui",
               "SIL OFL 1.1"),
            _e("Atkinson Hyperlegible", "googlefonts/atkinson-hyperlegible",
               "Braille Institute typeface designed for maximum "
               "legibility by low-vision readers.",
               "accessibility, sans-serif, legible",
               "SIL OFL 1.1"),
            _e("Maple Mono", "subframe7536/maple-font",
               "Rounded monospace font with ligatures, Nerd Font "
               "variants and CJK support.",
               "monospace, coding, rounded, ligatures",
               "SIL OFL 1.1"),
            _e("Victor Mono", "rubjo/victor-mono",
               "Free monospaced cursive font with optional ligatures "
               "and beautiful italics.",
               "monospace, coding, italic, ligatures",
               "SIL OFL 1.1", "https://rubjo.github.io/victor-mono"),
        ],
    },
    {
        "name": "Open Icon Sets",
        "kind": "icon",
        "summary": "Curated open-source icon families on GitHub. Icons "
                   "stay remote until you clone a set; entries carry "
                   "each project's licence and URL.",
        "tags": "icons, svg, opensource, ui",
        "entries": [
            _e("Feather Icons", "feathericons/feather",
               "Simply beautiful open source icons — 280+ clean, "
               "light 24px stroke icons.",
               "stroke, minimal, web, 24px",
               "MIT", "https://feathericons.com"),
            _e("Lucide", "lucide-icons/lucide",
               "Community-maintained Feather fork — 1500+ consistent, "
               "customizable SVG icons.",
               "stroke, minimal, web, feather-fork",
               "ISC", "https://lucide.dev"),
            _e("Tabler Icons", "tabler/tabler-icons",
               "5700+ free MIT-licensed SVG icons with stroke "
               "adjustments, ideal for dashboards.",
               "stroke, dashboard, large, web",
               "MIT", "https://tabler.io/icons"),
            _e("Phosphor Icons", "phosphor-icons/core",
               "Flexible icon family: 9000+ icons across six weights "
               "from thin to fill.",
               "weights, fill, duotone, web",
               "MIT", "https://phosphoricons.com"),
            _e("Bootstrap Icons", "twbs/icons",
               "1500+ free SVG icons from the Bootstrap team — "
               "glyphs from UI to commerce.",
               "web, bootstrap, ui, svg",
               "MIT", "https://icons.getbootstrap.com"),
            _e("Heroicons", "tailwindlabs/heroicons",
               "Hand-crafted SVG icons by the Tailwind CSS team — "
               "outline, solid and mini styles.",
               "outline, solid, tailwind, ui",
               "MIT", "https://heroicons.com"),
            _e("Remix Icon", "Remix-Design/RemixIcon",
               "2700+ open-source neutral-style system icons mixing "
               "outline and filled styles.",
               "outline, filled, system, web",
               "Apache-2.0", "https://remixicon.com"),
            _e("Material Design Icons", "Templarian/MaterialDesign",
               "Community fork of Material Design icons — 7000+ "
               "glyphs maintained by Pictogrammers.",
               "material, community, large, web",
               "Apache-2.0", "https://pictogrammers.com"),
            _e("Font Awesome Free", "FortAwesome/Font-Awesome",
               "The iconic library's free tier: solid, regular and "
               "brands with SVG + webfont builds.",
               "brands, solid, webfont, svg",
               "MIT", "https://fontawesome.com"),
            _e("Ionicons", "ionic-team/ionicons",
               "Premium hand-crafted icons for the Ionic framework — "
               "iOS, Material and outline variants.",
               "ios, material, outline, mobile",
               "MIT", "https://ionicons.com"),
            _e("Simple Icons", "simple-icons/simple-icons",
               "3000+ brand SVG logos of popular products and "
               "services, usable as SVG or font.",
               "brands, logos, svg",
               "CC0-1.0", "https://simpleicons.org"),
            _e("Devicon", "devicons/devicon",
               "Icon set for programming languages, tools and "
               "frameworks — original and plain variants.",
               "dev, brands, tech, languages",
               "MIT", "https://devicon.dev"),
            _e("Octicons", "primer/octicons",
               "GitHub's own icon set — the glyphs you see across "
               "github.com, as SVG sprites.",
               "github, ui, svg",
               "MIT", "https://primer.style/foundations/icons"),
        ],
    },
    {
        "name": "Site Templates & Themes",
        "kind": "template",
        "summary": "Curated open-source static-site themes and starter "
                   "templates (Hugo, Jekyll, Astro, Eleventy, "
                   "Bootstrap). Templates stay remote until cloned.",
        "tags": "templates, themes, static-site, web, opensource",
        "entries": [
            _e("Hugo PaperMod", "adityatelange/hugo-PaperMod",
               "Fast, clean, responsive and modern Hugo blog theme "
               "with dark mode and rich featured options.",
               "hugo, blog, dark-mode, minimal",
               "MIT"),
            _e("Minimal Mistakes", "mmistakes/minimal-mistakes",
               "Flexible two-column Jekyll theme — perfect for "
               "personal sites, blogs and portfolios.",
               "jekyll, blog, portfolio, responsive",
               "MIT"),
            _e("AstroPaper", "satnaing/astro-paper",
               "Minimal, accessible and SEO-friendly Astro blog "
               "theme built with TypeScript and Tailwind.",
               "astro, blog, accessibility, seo, tailwind",
               "MIT"),
            _e("AstroWind", "onwidget/astrowind",
               "Free Astro + Tailwind starter template for "
               "startups, marketing sites and landing pages.",
               "astro, tailwind, landing-page, startup",
               "MIT", "https://astrowind.vercel.app"),
            _e("Eleventy Base Blog", "11ty/eleventy-base-blog",
               "The official Eleventy starter blog — a lean, "
               "dependency-light template with sensible defaults.",
               "eleventy, 11ty, blog, starter",
               "MIT"),
            _e("Poole", "poole/poole",
               "The Jekyll butler — a minimal foundation theme "
               "designed to be a starting point, not a destination.",
               "jekyll, minimal, foundation",
               "MIT", "https://getpoole.com"),
            _e("Hyde", "poole/hyde",
               "Brazen two-column Jekyll theme built on Poole — "
               "sidebar navigation with a content focus.",
               "jekyll, blog, sidebar, poole",
               "MIT"),
            _e("Minima", "jekyll/minima",
               "The default Jekyll theme: a minimal, responsive "
               "one-size-fits-all starting point.",
               "jekyll, default, minimal, blog",
               "MIT"),
            _e("StartBootstrap Freelancer",
               "StartBootstrap/startbootstrap-freelancer",
               "One-page Bootstrap portfolio theme for freelance "
               "projects — flat design, easy to customize.",
               "bootstrap, portfolio, one-page, html",
               "MIT", "https://startbootstrap.com"),
            _e("Bootswatch", "thomaspark/bootswatch",
               "Free themes for Bootstrap that can be dropped in as "
               "a stylesheet or compiled from source.",
               "bootstrap, themes, css",
               "MIT", "https://bootswatch.com"),
            _e("Doks", "gethyas/doks",
               "Documentation theme and build system — 100/100 "
               "Lighthouse scores, Alpine.js and Hugo-powered.",
               "hugo, docs, documentation, hyas",
               "MIT", "https://getdoks.org"),
            _e("Hextra", "imfing/hextra",
               "Modern, batteries-included Hugo documentation "
               "theme with search, dark mode and sidebar nav.",
               "hugo, docs, documentation, modern",
               "MIT"),
            _e("Hugo Bear Blog", "janraasch/hugo-bearblog",
               "Hugo port of the Bear Blog theme — what if a "
               "website was just text? Fast, tiny, readable.",
               "hugo, blog, minimal, fast",
               "MIT", "https://bearblog.dev"),
        ],
    },
    {
        "name": "Color Harmonies",
        "kind": "palette",
        "summary": "Curated color-harmony palettes (complementary, triadic, "
                   "analogous, split-complementary, tetradic, monochrome). "
                   "Click any card to load it into the Harmony generator.",
        "tags": "colors, harmony, palette, curated",
        "entries": [
            _c("Complementary Ocean",
               "Deep navy and sky blue — complementary hues for "
               "nautical interfaces.",
               ["#03045E", "#023E8A", "#0077B6", "#00B4D8", "#90E0EF"],
               "complementary, blue, nautical, cool"),
            _c("Complementary Ember",
               "Scarlet and charcoal — high-contrast complementary warmth.",
               ["#370617", "#6A040F", "#9D0208", "#D00000", "#DC2F02"],
               "complementary, red, warm, bold"),
            _c("Triadic Bright",
               "Blue, pink, and yellow equally spaced — energetic triadic "
               "scheme.",
               ["#03045E", "#FF006E", "#FFBE0B", "#8338EC", "#3A86FF"],
               "triadic, bright, colorful, primary"),
            _c("Triadic Tropical",
               "Teal, orange, and violet — warm tropical triadic palette.",
               ["#0077B6", "#FB5607", "#FFBE0B", "#8338EC", "#3A86FF"],
               "triadic, tropical, warm, vibrant"),
            _c("Analogous Forest",
               "Greens from deep canopy to fresh leaf — serene analogous "
               "range.",
               ["#081C15", "#1B4332", "#2D6A4F", "#40916C", "#52B788"],
               "analogous, green, nature, calm"),
            _c("Analogous Lavender",
               "Violet gradient from midnight to soft lavender.",
               ["#240046", "#3C096C", "#5A189A", "#7B2CBF", "#9D4EDD"],
               "analogous, purple, soft, gradient"),
            _c("Split-Complementary Berry",
               "Violet with teal accents — split-complementary contrast.",
               ["#5A189A", "#7B2CBF", "#C77DFF", "#06D6A0", "#1B9AAA"],
               "split-complementary, purple, teal, contrast"),
            _c("Split-Complementary Coral",
               "Coral pink with ocean blue accents — beachy split scheme.",
               ["#FF4D6D", "#FF8FA3", "#FFB3C1", "#00B4D8", "#0077B6"],
               "split-complementary, pink, blue, beach"),
            _c("Tetradic Muted",
               "Four muted hues plus cream — balanced tetradic harmony.",
               ["#264653", "#2A9D8F", "#E9C46A", "#F4A261", "#E76F51"],
               "tetradic, muted, earth, balanced"),
            _c("Tetradic Earth",
               "Olive, brown, ochre, and cream — grounded tetradic tones.",
               ["#606C38", "#283618", "#DDA15E", "#BC6C25", "#FEFAE0"],
               "tetradic, earth, olive, warm"),
            _c("Monochrome Charcoal",
               "Five grays from black to mid-tone — monochrome elegance.",
               ["#0F0F0F", "#2C2C2C", "#484848", "#646464", "#808080"],
               "monochrome, gray, neutral, elegant"),
            _c("Monochrome Rose",
               "Pink gradient from deep rose to soft blush.",
               ["#4A0E17", "#7B1E3A", "#A62D5C", "#D44D7E", "#FF6FA0"],
               "monochrome, pink, rose, gradient"),
        ],
    },
]


# ------------------------------------------------------------ persistence

def ensure_presets(con: sqlite3.Connection) -> None:
    """Create the preset tables (idempotent) and register any pack
    rows missing from this database. Never touches downloaded state —
    updates only ADD missing libraries/entries."""
    con.executescript("""
    CREATE TABLE IF NOT EXISTS preset_library (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        name       TEXT NOT NULL UNIQUE,
        kind       TEXT NOT NULL DEFAULT '',
        summary    TEXT NOT NULL DEFAULT '',
        tags       TEXT NOT NULL DEFAULT '',
        remote_url TEXT NOT NULL DEFAULT '',
        branch     TEXT NOT NULL DEFAULT '',
        remote     INTEGER NOT NULL DEFAULT 1,
        position   INTEGER NOT NULL DEFAULT 0,
        guid       TEXT,
        slug       TEXT
    );
    CREATE TABLE IF NOT EXISTS preset_entry (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        library_id   INTEGER NOT NULL
                     REFERENCES preset_library(id) ON DELETE CASCADE,
        name         TEXT NOT NULL,
        repo         TEXT NOT NULL DEFAULT '',
        url          TEXT NOT NULL DEFAULT '',
        branch       TEXT NOT NULL DEFAULT '',
        description  TEXT NOT NULL DEFAULT '',
        license      TEXT NOT NULL DEFAULT '',
        homepage     TEXT NOT NULL DEFAULT '',
        tags         TEXT NOT NULL DEFAULT '',
        position     INTEGER NOT NULL DEFAULT 0,
        downloaded   INTEGER NOT NULL DEFAULT 0,
        local_path   TEXT NOT NULL DEFAULT '',
        preview_path TEXT NOT NULL DEFAULT '',
        colors       TEXT NOT NULL DEFAULT '',
        palette_id   INTEGER,
        guid         TEXT,
        slug         TEXT
    );
    """)
    from . import db as core_db
    core_db._migrate_guid_slug(con)
    for pos, pack in enumerate(PRESET_PACKS):
        row = con.execute("SELECT id FROM preset_library WHERE name = ?",
                          (pack["name"],)).fetchone()
        if row is None:
            con.execute(
                "INSERT INTO preset_library(name, kind, summary, tags,"
                " remote, position) VALUES (?, ?, ?, ?, 1, ?)",
                (pack["name"], pack["kind"], pack["summary"], pack["tags"],
                 pos))
            lib_id = con.execute(
                "SELECT id FROM preset_library WHERE name = ?",
                (pack["name"],)).fetchone()["id"]
        else:
            lib_id = row["id"]
        for epos, e in enumerate(pack["entries"]):
            # dedup: font/icon/template entries key by repo; palette
            # entries have no repo, so key by name
            if pack["kind"] == "palette":
                if con.execute("SELECT 1 FROM preset_entry WHERE library_id = ?"
                               " AND name = ?", (lib_id, e["name"])).fetchone():
                    continue
                colors_json = json.dumps(e.get("colors", []))
                con.execute(
                    "INSERT INTO preset_entry(library_id, name, repo, url,"
                    " branch, description, license, homepage, tags,"
                    " position, colors) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (lib_id, e["name"], e["repo"], e["url"], e["branch"],
                     e["description"], e["license"], e["homepage"], e["tags"],
                     epos, colors_json))
            else:
                if con.execute("SELECT 1 FROM preset_entry WHERE library_id = ?"
                               " AND repo = ?", (lib_id, e["repo"])).fetchone():
                    continue
                con.execute(
                    "INSERT INTO preset_entry(library_id, name, repo, url,"
                    " branch, description, license, homepage, tags, position)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (lib_id, e["name"], e["repo"], e["url"], e["branch"],
                     e["description"], e["license"], e["homepage"], e["tags"],
                     epos))
    con.commit()


# --------------------------------------------------------- scan sources

def entry_scan_kind(pack_kind: str) -> str | None:
    """Scan-source kind for a downloaded preset pack's clone, or None
    when the clone must NOT be indexed: icon packs join the icon grid
    ('folder'), font packs the fonts pane ('fontroot'). Template clones
    stay out of the library on purpose — indexing a site theme's
    imagery would flood the asset grid with its screenshots/logos."""
    return {"icon": "folder", "font": "fontroot"}.get(pack_kind)


# pack kind -> the ASSET kind its downloads produce (collections are
# typed by asset kind, not by scan-source kind — #141)
_PACK_ASSET_KIND = {"icon": "icon", "font": "font"}


def _ensure_typed_collection(con: sqlite3.Connection, name: str,
                             kind: str) -> int:
    row = con.execute(
        "SELECT id FROM collection WHERE name = ? AND kind IS ?",
        (name, kind)).fetchone()
    if row is not None:
        return row["id"]
    from .db import new_guid
    cur = con.execute(
        "INSERT INTO collection(name, kind, guid) VALUES (?, ?, ?)",
        (name, kind, new_guid()))
    return int(cur.lastrowid or 0)


def sync_download_collections(con: sqlite3.Connection) -> None:
    """#141 download step: every downloaded preset pack files its
    indexed assets into a default 'Downloaded' collection (one per
    asset type) AND a collection named after the pack, so downloaded
    asset collections are browsable the moment they land.

    Idempotent — called after every download AND after every completed
    scan, because membership can only be built once the clone's assets
    are actually indexed. A pack whose clone never registers a source
    (templates) or whose source has no assets yet simply contributes
    nothing until a later scan reconciles it.
    """
    rows = con.execute(
        "SELECT e.name, e.local_path, l.kind AS pack_kind"
        " FROM preset_entry e JOIN preset_library l ON l.id = e.library_id"
        " WHERE e.downloaded = 1").fetchall()
    touched = False
    for r in rows:
        kind = _PACK_ASSET_KIND.get(r["pack_kind"])
        if kind is None:
            continue
        dl_id = _ensure_typed_collection(con, "Downloaded", kind)
        item_id = _ensure_typed_collection(con, r["name"], kind)
        if not r["local_path"]:
            continue
        src = con.execute(
            "SELECT id FROM source WHERE path = ?",
            (str(Path(r["local_path"]).resolve()),)).fetchone()
        if src is None:
            continue
        for cid in (dl_id, item_id):
            cur = con.execute(
                "INSERT OR IGNORE INTO collection_ref"
                "(collection_id, item_kind, item_id)"
                " SELECT ?, a.kind, a.id FROM asset a"
                " WHERE a.source_id = ?", (cid, src["id"]))
            if cur.rowcount:
                touched = True
    if touched:
        con.commit()


# pane kinds that support preset-derived default libraries
_DEFAULT_LIBRARY_KINDS = ("icon", "font", "palette")


def sync_pack_libraries(con: sqlite3.Connection) -> None:
    """#141 (reporter round 2): every downloaded pack becomes a discrete
    LIBRARY — a tag-driven ``library_view`` named after the pack, with
    the pack's tag applied to its indexed assets, so the pack is
    browsable/filterable from the global Libraries list on every pane.

    Idempotent — the same reconciliation discipline as
    sync_download_collections: called after downloads and after
    completed scans, because the tag can only land once the clone's
    assets are actually indexed. The library_view row itself is created
    immediately at download time (UNIQUE(name) guarded), counts fill in
    as assets index.
    """
    rows = con.execute(
        "SELECT e.name, e.local_path, l.kind AS pack_kind"
        " FROM preset_entry e JOIN preset_library l ON l.id = e.library_id"
        " WHERE e.downloaded = 1").fetchall()
    from . import taxonomy as core_tax
    for r in rows:
        if _PACK_ASSET_KIND.get(r["pack_kind"]) is None:
            continue
        name = str(r["name"]).strip()
        if not name:
            continue
        # the tag the pack's assets carry (library views are tag-driven)
        con.execute("INSERT OR IGNORE INTO tag(name) VALUES (?)", (name,))
        tag_id = con.execute("SELECT id FROM tag WHERE name = ?",
                             (name,)).fetchone()["id"]
        if r["local_path"]:
            src = con.execute(
                "SELECT id FROM source WHERE path = ?",
                (str(Path(r["local_path"]).resolve()),)).fetchone()
            if src is not None:
                # tag the pack's assets through the kind-aware item_tag
                # store — the same table every library/collection filter
                # reads (asset_tag is the legacy pre-taxonomy table; a
                # write there is invisible to the rail)
                con.execute(
                    "INSERT OR IGNORE INTO item_tag(item_id, item_kind,"
                    " tag_id) SELECT a.id, a.kind, ? FROM asset a"
                    " WHERE a.source_id = ?",
                    (tag_id, src["id"]))
        if con.execute("SELECT 1 FROM library_view WHERE name = ?",
                       (name,)).fetchone() is None:
            try:
                core_tax.create_library_view(con, name, name, False)
            except ValueError:
                pass
    con.commit()


def sync_default_library(con: sqlite3.Connection) -> None:
    """#135/#136: ensure each pane's 'Default' library contains the pane's
    preset content plus any downloaded assets.  Idempotent — safe to call
    after every scan or download.

    * icon pane  → Default (icon)  = every asset indexed from a downloaded
      icon preset pack clone
    * font pane  → Default (font)  = every asset indexed from a downloaded
      font preset pack clone
    * palette pane → Default (palette) = every colour-harmony preset entry
      materialised as a palette row
    """
    for kind in _DEFAULT_LIBRARY_KINDS:
        default_id = _ensure_typed_collection(con, "Default", kind)
        if kind in ("icon", "font"):
            _sync_default_assets(con, default_id, kind)
        elif kind == "palette":
            _sync_default_palettes(con, default_id)
    con.commit()


def _sync_default_assets(con: sqlite3.Connection, default_id: int,
                         asset_kind: str) -> None:
    """Add every asset whose source is a downloaded preset pack to the
    Default collection for this asset kind.  Idempotent."""
    rows = con.execute(
        "SELECT s.id FROM source s"
        " JOIN preset_entry e ON e.local_path = s.path"
        " JOIN preset_library l ON l.id = e.library_id"
        " WHERE e.downloaded = 1 AND l.kind = ?"
        " AND s.kind IN ('folder', 'fontroot')",
        (asset_kind,)).fetchall()
    for r in rows:
        con.execute(
            "INSERT OR IGNORE INTO collection_ref"
            " (collection_id, item_kind, item_id)"
            " SELECT ?, a.kind, a.id FROM asset a WHERE a.source_id = ?",
            (default_id, r["id"]))


def _sync_default_palettes(con: sqlite3.Connection, default_id: int) -> None:
    """Materialise every palette-kind preset entry as a palette row (if
    not already done) and ensure it is in the Default palette collection.
    Idempotent."""
    from . import db as core_db
    rows = con.execute(
        "SELECT e.id, e.name, e.tags, e.colors, e.palette_id"
        " FROM preset_entry e JOIN preset_library l ON l.id = e.library_id"
        " WHERE l.kind = 'palette' AND e.colors != ''"
    ).fetchall()
    for r in rows:
        if r["palette_id"]:
            pid = r["palette_id"]
        else:
            now = time.time()
            pid = con.execute(
                "INSERT INTO palette(name, tags, created, updated, guid)"
                " VALUES (?, ?, ?, ?, ?)",
                (r["name"], r["tags"], now, now, core_db.new_guid())
            ).lastrowid
            con.execute(
                "UPDATE preset_entry SET palette_id = ? WHERE id = ?",
                (pid, r["id"]))
        # upsert palette colors
        con.execute("DELETE FROM palette_color WHERE palette_id = ?", (pid,))
        colors = json.loads(r["colors"])
        for pos, hx in enumerate(colors):
            con.execute(
                "INSERT INTO palette_color(palette_id, position, hex, locked)"
                " VALUES (?, ?, ?, 0)", (pid, pos, hx))
        # add to Default collection
        con.execute(
            "INSERT OR IGNORE INTO collection_ref"
            " (collection_id, item_kind, item_id) VALUES (?, 'palette', ?)",
            (default_id, pid))


def sync_downloaded_sources(con: sqlite3.Connection) -> list[dict]:
    """Register scan sources for every downloaded preset entry whose
    clone exists on disk.

    Idempotent: an existing source row is left alone (a disabled one is
    re-enabled), and entries with no kind mapping or a vanished clone
    are skipped. Returns the registrations made BY THIS CALL so callers
    can trigger exactly the rescans needed — startup calls this so
    clones downloaded by older builds (#37) still reach the grid.
    """
    from . import indexer
    new: list[dict] = []
    rows = con.execute(
        "SELECT e.id, e.local_path, l.kind AS pack_kind"
        " FROM preset_entry e JOIN preset_library l ON l.id = e.library_id"
        " WHERE e.downloaded = 1").fetchall()
    for r in rows:
        kind = entry_scan_kind(r["pack_kind"])
        if kind is None or not r["local_path"]:
            continue
        p = Path(r["local_path"]).resolve()
        if not p.is_dir():
            continue
        existing = con.execute(
            "SELECT id, enabled FROM source WHERE path = ?",
            (str(p),)).fetchone()
        if existing is not None:
            if not existing["enabled"]:
                indexer.set_source_enabled(con, existing["id"], True)
                new.append({"path": str(p), "kind": kind})
            continue
        indexer.add_folder_source(con, str(p), kind=kind)
        new.append({"path": str(p), "kind": kind})
    return new


def remove_entry_source(con: sqlite3.Connection, local_path: str) -> bool:
    """Drop the scan source registered for a downloaded preset entry
    (forget() must undo what sync_downloaded_sources did — a forgotten
    pack must not leave a dangling source pointing at a deleted dir)."""
    if not local_path:
        return False
    row = con.execute(
        "SELECT id FROM source WHERE path = ?",
        (str(Path(local_path).resolve()),)).fetchone()
    if row is None:
        return False
    from . import indexer
    return indexer.remove_source(con, row["id"])


# ------------------------------------------------------------ file paths

def entry_dir(data_dir: str | Path, library_name: str, repo: str) -> Path:
    """Where an entry's clone lives: <data>/presets/<library>/<repo>."""
    from .projects_git import slugify
    lib = slugify(library_name)
    repo_name = repo.split("/")[-1] if "/" in repo else repo
    return Path(data_dir) / "presets" / lib / repo_name


# ------------------------------------------------------------ previews

_IMG_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg")
_PREFERRED_NAME_HINTS = ("social", "banner", "preview", "cover", "og",
                         "hero", "logo", "icon")


def readme_image_paths(clone: Path, limit: int = 8) -> list[Path]:
    """Local images referenced by the clone's README.md (relative refs
    resolved; absolute/external URLs skipped)."""
    md = next((clone / n for n in ("README.md", "readme.md", "Readme.md",
                                   "README.markdown")
               if (clone / n).is_file()), None)
    if md is None:
        return []
    try:
        text = md.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    out = []
    for m in re.finditer(r"!\[[^\]]*\]\(([^)\s]+)", text):
        ref = m.group(1).strip().replace("%20", " ")
        if ref.startswith(("http://", "https://", "data:")):
            continue
        ref = ref.split("?")[0].lstrip("/")
        cand = clone / ref
        if cand.suffix.lower() in _IMG_EXTS and cand.is_file():
            out.append(cand)
        if len(out) >= limit:
            break
    return out


def scan_social_image(clone: Path) -> Path | None:
    """Best social/preview image inside a cloned repo: named previews
    (social.png, banner…) beat README references, root beats docs/."""
    named = ("social.png", "social.jpg", "social-preview.png",
             "banner.png", "preview.png", "cover.png", "hero.png",
             "logo.png", "icon.png", "logo.svg")
    for base in (clone, clone / "docs", clone / "assets",
                 clone / ".github"):
        if not base.is_dir():
            continue
        for name in named:
            p = base / name
            if p.is_file():
                return p
    # else: any root-level image whose name hints at promo material
    try:
        for p in sorted(clone.iterdir()):
            if p.is_file() and p.suffix.lower() in _IMG_EXTS and any(
                    h in p.stem.lower() for h in _PREFERRED_NAME_HINTS):
                return p
    except OSError:
        pass
    return None


def preview_source(clone: Path) -> Path | None:
    """The repo's best preview image, social images first, then
    README references."""
    return scan_social_image(clone) or (
        readme_image_paths(clone)[0] if readme_image_paths(clone) else None)
