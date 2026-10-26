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

import re
import sqlite3
from pathlib import Path

# ---------------------------------------------------------------- data


def _e(name, repo, desc, tags, license="", homepage="", branch=""):
    return {
        "name": name, "repo": repo,
        "url": f"https://github.com/{repo}.git",
        "branch": branch, "description": desc, "tags": tags,
        "license": license, "homepage": homepage,
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
