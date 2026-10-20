"""Demo data: a generous showcase suite the user can load and remove.

`install()` generates example assets (SVG icon pack, a font copy, code
snippets, palettes) and wires them into 14 demo projects covering the
app's intended use-cases — websites, web apps, admin panels, e-commerce,
magazine, portfolio, dev blog, toolkit, email, recipes… Everything
created is recorded by id in the `demo_ids` setting so `remove()` can
delete precisely — per data kind, e.g. keep tags but drop the rest.

Demo files live in their own directory (demo-assets/) under the app's
data dir, so removing demo assets never touches user folders.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import time
from pathlib import Path

from . import colors as core_colors
from . import db as core_db
from . import projects as core_projects
from . import settings
from . import snippets as core_snippets

DEMO_SETTING = "demo_ids"
DEMO_TAG = "demo"

# ---------------------------------------------------------------- SVG icons
# Feather-style 24/2px stroke shapes (MIT-licensed feather geometry).

_SVG = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'"
        " fill='none' stroke='#{stroke}' stroke-width='2'"
        " stroke-linecap='round' stroke-linejoin='round'>{body}</svg>")

ICONS: dict[str, str] = {
    "globe": "<circle cx='12' cy='12' r='10'/><line x1='2' y1='12' x2='22' y2='12'/>"
             "<path d='M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z'/>",
    "cart": "<circle cx='9' cy='21' r='1'/><circle cx='20' cy='21' r='1'/>"
            "<path d='M1 1h4l2.68 13.39a2 2 0 0 0 2 1.61h9.72a2 2 0 0 0 2-1.61L23 6H6'/>",
    "chart": "<line x1='18' y1='20' x2='18' y2='10'/><line x1='12' y1='20' x2='12' y2='4'/>"
             "<line x1='6' y1='20' x2='6' y2='14'/>",
    "user": "<path d='M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2'/><circle cx='12' cy='7' r='4'/>",
    "mail": "<path d='M4 4h16a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z'/>"
            "<polyline points='22,6 12,13 2,6'/>",
    "camera": "<path d='M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z'/>"
              "<circle cx='12' cy='13' r='4'/>",
    "code": "<polyline points='16 18 22 12 16 6'/><polyline points='8 6 2 12 8 18'/>",
    "terminal": "<polyline points='4 17 10 11 4 5'/><line x1='12' y1='19' x2='20' y2='19'/>",
    "book": "<path d='M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z'/>"
            "<path d='M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z'/>",
    "calendar": "<rect x='3' y='4' width='18' height='18' rx='2' ry='2'/>"
                "<line x1='16' y1='2' x2='16' y2='6'/><line x1='8' y1='2' x2='8' y2='6'/>"
                "<line x1='3' y1='10' x2='21' y2='10'/>",
    "heart": "<path d='M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z'/>",
    "card": "<rect x='1' y='4' width='22' height='16' rx='2' ry='2'/>"
            "<line x1='1' y1='10' x2='23' y2='10'/>",
    "package": "<line x1='16.5' y1='9.4' x2='7.5' y2='4.21'/>"
               "<path d='M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z'/>"
               "<polyline points='3.27 6.96 12 12.01 20.73 6.96'/><line x1='12' y1='22.08' x2='12' y2='12'/>",
    "coffee": "<path d='M18 8h1a4 4 0 0 1 0 8h-1'/>"
              "<path d='M2 8h16v9a4 4 0 0 1-4 4H6a4 4 0 0 1-4-4V8z'/>"
              "<line x1='6' y1='1' x2='6' y2='4'/><line x1='10' y1='1' x2='10' y2='4'/>"
              "<line x1='14' y1='1' x2='14' y2='4'/>",
    "bag": "<path d='M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z'/>"
           "<line x1='3' y1='6' x2='21' y2='6'/><path d='M16 10a4 4 0 0 1-8 0'/>",
    "clock": "<circle cx='12' cy='12' r='10'/><polyline points='12 6 12 12 16 14'/>",
    "image": "<rect x='3' y='3' width='18' height='18' rx='2' ry='2'/>"
             "<circle cx='8.5' cy='8.5' r='1.5'/><polyline points='21 15 16 10 5 21'/>",
    "pen": "<path d='M17 3a2.83 2.83 0 0 1 4 4L7.5 20.5 2 22l1.5-5.5z'/>",
    "speaker": "<rect x='4' y='2' width='16' height='20' rx='2' ry='2'/>"
               "<circle cx='12' cy='14' r='4'/><line x1='12' y1='6' x2='12.01' y2='6'/>",
    "compass": "<circle cx='12' cy='12' r='10'/><polygon points='16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76'/>",
}

# icon -> (theme-tag, context) so the icons pane filters have something to chew
ICON_META: dict[str, tuple[str, str]] = {
    "globe": ("web", "site"), "cart": ("commerce", "shop"),
    "chart": ("analytics", "app"), "user": ("app", "account"),
    "mail": ("email", "comms"), "camera": ("photo", "media"),
    "code": ("dev", "editor"), "terminal": ("dev", "cli"),
    "book": ("docs", "reading"), "calendar": ("events", "schedule"),
    "heart": ("social", "feedback"), "card": ("commerce", "checkout"),
    "package": ("commerce", "shipping"), "coffee": ("food", "menu"),
    "bag": ("commerce", "shop"), "clock": ("utility", "time"),
    "image": ("photo", "media"), "pen": ("editorial", "writing"),
    "speaker": ("events", "audio"), "compass": ("travel", "maps"),
}


# ------------------------------------------------------------------ palettes

PALETTES: list[tuple[str, list[str], str]] = [
    ("Demo — SaaS Teal", ["#0F1720", "#17222B", "#37B8C4", "#8FA5B3",
                          "#E8F0F4", "#233240"], "demo, saas, web"),
    ("Demo — Commerce Coral", ["#171212", "#221A18", "#F0785C", "#A98F84",
                               "#F4EDE8", "#33251F"], "demo, ecommerce"),
    ("Demo — Magazine Ivory", ["#F8F5EF", "#FFFFFF", "#8A2D2D", "#6E675C",
                               "#22201C", "#DDD6C9"], "demo, editorial"),
    ("Demo — Portfolio Mono", ["#101112", "#1A1C1E", "#E8E8E8", "#8A8F94",
                               "#F2F2F2", "#2A2D30"], "demo, portfolio"),
    ("Demo — Admin Dark", ["#0B0F14", "#131A21", "#4FB286", "#7D8C99",
                           "#DCE6EE", "#1F2933"], "demo, admin"),
    ("Demo — Event Violet", ["#140F1E", "#1F1830", "#A78BFA", "#9188A8",
                             "#EFEAF8", "#2A2140"], "demo, events"),
    ("Demo — Harvest", ["#1C130D", "#2A1D14", "#D9822B", "#A18B72",
                        "#F5EEDF", "#3C2B1C"], "demo, food, recipes"),
    ("Demo — Email Blue", ["#FFFFFF", "#F2F6FA", "#1B6EC2", "#6B7C8C",
                           "#10222F", "#D6E2EE"], "demo, email"),
]


# ------------------------------------------------------------------ snippets

def _snippet(title: str, desc: str, lang: str, html: str, css: str,
             js: str, tags: str) -> dict:
    return {"title": title, "description": desc, "language": lang,
            "html": html, "css": css, "js": js, "tags": tags}


SNIPPETS: list[dict] = [
    _snippet("Product card", "E-commerce product tile with hover lift",
             "web",
             "<div class='card'>\n  <img src='' alt='Product'>\n"
             "  <h3>Aurora Lamp</h3>\n  <p class='price'>$89</p>\n"
             "  <button>Add to cart</button>\n</div>",
             ".card { border-radius: 12px; padding: 16px;\n"
             "  box-shadow: 0 2px 10px rgba(0,0,0,.08);\n"
             "  transition: transform .18s ease; }\n"
             ".card:hover { transform: translateY(-4px); }\n"
             ".price { font-weight: 700; color: var(--fg-accent); }",
             "document.querySelector('.card button')\n"
             "  .addEventListener('click', () => console.log('added'))",
             "demo, ecommerce, card"),
    _snippet("Stat card", "Dashboard KPI tile with delta badge",
             "web",
             "<div class='stat'>\n  <span class='label'>MRR</span>\n"
             "  <strong>$24.6k</strong>\n"
             "  <span class='delta up'>▲ 8.4%</span>\n</div>",
             ".stat { display: flex; flex-direction: column; gap: 4px;\n"
             "  padding: 18px; border-radius: var(--fg-radius);\n"
             "  background: var(--fg-surface); }\n"
             ".delta.up { color: #4FB286; font-size: 12px; }\n"
             ".delta.down { color: #E05B5B; font-size: 12px; }",
             "", "demo, admin, dashboard"),
    _snippet("Pricing table", "Three-tier pricing row",
             "web",
             "<div class='tiers'>\n  <div class='tier'><h3>Starter</h3>"
             "<p class='p'>$9</p><button>Choose</button></div>\n"
             "  <div class='tier best'><h3>Pro</h3><p class='p'>$29</p>"
             "<button>Choose</button></div>\n"
             "  <div class='tier'><h3>Team</h3><p class='p'>$99</p>"
             "<button>Choose</button></div>\n</div>",
             ".tiers { display: grid; grid-template-columns:"
             " repeat(3, 1fr); gap: 14px; }\n"
             ".tier { padding: 22px; border-radius: 14px;"
             " border: 1px solid var(--fg-border); }\n"
             ".tier.best { outline: 2px solid var(--fg-accent); }",
             "", "demo, saas, pricing"),
    _snippet("Email signature", "Table-based HTML signature (client-safe)",
             "web",
             "<table cellpadding='0' cellspacing='0'>\n  <tr>\n"
             "    <td style='padding-right:14px;border-right:2px solid #1B6EC2'>\n"
             "      <img src='logo.png' width='52' alt=''>\n    </td>\n"
             "    <td style='padding-left:14px;font-family:Arial,sans-serif'>\n"
             "      <strong style='font-size:15px'>Sam Davis</strong><br>\n"
             "      <span style='color:#6B7C8C'>Design Engineer, Native IT</span><br>\n"
             "      <a href='https://nativeit.dev' style='color:#1B6EC2'>nativeit.dev</a>\n"
             "    </td>\n  </tr>\n</table>",
             "table { border-collapse: collapse; }",
             "", "demo, email, signature"),
    _snippet("Newsletter masthead", "Email-safe header block",
             "web",
             "<table width='100%' cellpadding='0' cellspacing='0'>\n  <tr>\n"
             "    <td align='center' style='padding:28px;"
             "background:#1B6EC2;color:#fff;font-family:Georgia,serif'>\n"
             "      <h1 style='margin:0;font-size:26px'>The Weekly Fen</h1>\n"
             "      <p style='margin:6px 0 0;opacity:.8'>Issue #12 — assets, fonts, tokens</p>\n"
             "    </td>\n  </tr>\n</table>",
             "", "", "demo, email, newsletter"),
    _snippet("Recipe card", "Markdown recipe template",
             "markdown",
             "",
             "",
             "",
             "demo, food, recipe"),
    _snippet("Gallery grid", "Responsive photo grid with captions",
             "web",
             "<div class='gallery'>\n  <figure><img src='' alt=''>"
             "<figcaption>Golden hour</figcaption></figure>\n"
             "  <figure><img src='' alt=''><figcaption>Low tide</figcaption></figure>\n"
             "  <figure><img src='' alt=''><figcaption>Dune walk</figcaption></figure>\n"
             "</div>",
             ".gallery { display: grid; grid-template-columns:"
             " repeat(auto-fill, minmax(160px, 1fr)); gap: 10px; }\n"
             "figure { margin: 0; }\nimg { width: 100%; aspect-ratio: 1;"
             " object-fit: cover; border-radius: 6px; }\n"
             "figcaption { font-size: 12px; color: var(--fg-muted);"
             " padding-top: 4px; }",
             "", "demo, portfolio, gallery"),
    _snippet("Code block style", "Pre/code styling for dev blogs",
             "web",
             "<pre><code class='lang'>const grid = css.grid('12')</code></pre>",
             "pre { background: var(--fg-surface); border-radius: 10px;\n"
             "  padding: 14px 16px; overflow-x: auto; }\n"
             "code { font-family: ui-monospace, 'Iosevka', monospace;\n"
             "  font-size: 13px; color: var(--fg-accent); }",
             "", "demo, blog, code"),
    _snippet("Hero split", "Marketing hero with two columns",
             "web",
             "<section class='hero'>\n  <div>\n    <h1>Ship assets faster</h1>\n"
             "    <p>One grid for every icon, font and palette you own.</p>\n"
             "    <button class='cta'>Get started</button>\n  </div>\n"
             "  <div class='art'></div>\n</section>",
             ".hero { display: grid; grid-template-columns: 1.2fr 1fr;\n"
             "  gap: 32px; align-items: center; padding: 48px 0; }\n"
             ".cta { background: var(--fg-accent); color: var(--fg-bg);\n"
             "  border: 0; border-radius: var(--fg-radius);\n  padding: 12px 22px; }",
             "", "demo, marketing, hero"),
    _snippet("Sticky navbar", "Minimal fixed top bar",
             "web",
             "<nav class='topbar'>\n  <span class='brand'>acme</span>\n"
             "  <a href='#'>Docs</a><a href='#'>Pricing</a>\n"
             "  <button>Sign in</button>\n</nav>",
             ".topbar { position: sticky; top: 0; display: flex;\n"
             "  gap: 18px; align-items: center; padding: 12px 20px;\n"
             "  background: var(--fg-surface);\n"
             "  border-bottom: 1px solid var(--fg-border); }\n"
             ".brand { font-weight: 700; margin-right: auto; }",
             "", "demo, web, nav"),
    _snippet("Testimonial", "Quote card with attribution",
             "web",
             "<blockquote class='quote'>\n  <p>Replaced four tools with one grid.</p>\n"
             "  <footer>— Priya, design lead</footer>\n</blockquote>",
             ".quote { margin: 0; padding: 20px 24px;\n"
             "  border-left: 3px solid var(--fg-accent);\n"
             "  background: var(--fg-surface); border-radius: 0 10px 10px 0; }\n"
             "footer { color: var(--fg-muted); font-size: 13px; }",
             "", "demo, marketing, social-proof"),
    _snippet("Badge chips", "Small status chips",
             "web",
             "<span class='chip ok'>stable</span>\n"
             "<span class='chip warn'>beta</span>\n"
             "<span class='chip bad'>deprecated</span>",
             ".chip { font-size: 11px; padding: 3px 10px;\n"
             "  border-radius: 99px; font-family: monospace; }\n"
             ".chip.ok { background: #173527; color: #4FB286; }\n"
             ".chip.warn { background: #3A2C12; color: #E2B93B; }\n"
             ".chip.bad { background: #3A1616; color: #E05B5B; }",
             "", "demo, toolkit, chips"),
]


# ------------------------------------------------------------------ projects

# (name, description, tags, settings overrides, attached asset refs)
# asset refs: ("icon", icon_name) | ("palette", palette_index)
#             | ("snippet", snippet_title) | ("font", "Bebas Neue")
P_PROJECTS: list[dict] = [
    {"name": "SaaS Marketing Site",
     "description": "Landing page tokens for a developer SaaS — teal on deep slate.",
     "tags": "demo, website, saas, marketing",
     "settings": {"prefix": "saas", "iconSize": 40,
                  "colors": {"radius": 12},
                  "type": {"baseSize": 17, "scale": 1.2}},
     "assets": [("palette", 0), ("icon", "globe"), ("icon", "chart"),
                ("snippet", "Hero split"), ("snippet", "Sticky navbar"),
                ("snippet", "Pricing table")]},
    {"name": "Admin Dashboard",
     "description": "Dark console UI kit — KPI cards, tables, dense spacing.",
     "tags": "demo, admin, dashboard, web-app",
     "settings": {"prefix": "admin", "iconSize": 28,
                  "colors": {"radius": 8},
                  "type": {"baseSize": 14, "scale": 1.15}},
     "assets": [("palette", 4), ("icon", "chart"), ("icon", "user"),
                ("icon", "clock"), ("snippet", "Stat card"),
                ("snippet", "Badge chips")]},
    {"name": "E-commerce Storefront",
     "description": "Shop tokens with warm coral accents and cart commerce icons.",
     "tags": "demo, ecommerce, shop, web",
     "settings": {"prefix": "shop", "iconSize": 36,
                  "colors": {"radius": 14},
                  "type": {"baseSize": 16, "scale": 1.25}},
     "assets": [("palette", 1), ("icon", "cart"), ("icon", "bag"),
                ("icon", "card"), ("icon", "package"),
                ("snippet", "Product card"), ("snippet", "Badge chips")]},
    {"name": "Online Magazine",
     "description": "Editorial light theme — ivory paper, oxblood accents, serif scale.",
     "tags": "demo, magazine, editorial, publishing",
     "settings": {"prefix": "mag", "iconSize": 32,
                  "colors": {"radius": 4},
                  "type": {"baseSize": 18, "scale": 1.333}},
     "assets": [("palette", 2), ("icon", "pen"), ("icon", "book"),
                ("snippet", "Testimonial"), ("snippet", "Code block style")]},
    {"name": "Photographer Portfolio",
     "description": "Gallery-first monochrome tokens; imagery does the talking.",
     "tags": "demo, portfolio, photography, gallery",
     "settings": {"prefix": "folio", "iconSize": 24,
                  "colors": {"radius": 2},
                  "type": {"baseSize": 15, "scale": 1.2}},
     "assets": [("palette", 3), ("icon", "camera"), ("icon", "image"),
                ("snippet", "Gallery grid")]},
    {"name": "Developer Blog",
     "description": "Reading-first blog tokens with mono code styling.",
     "tags": "demo, blog, writing, dev",
     "settings": {"prefix": "blog", "iconSize": 30,
                  "colors": {"radius": 6},
                  "type": {"baseSize": 17, "scale": 1.25}},
     "assets": [("palette", 0), ("icon", "code"), ("icon", "terminal"),
                ("snippet", "Code block style"), ("snippet", "Testimonial")]},
    {"name": "Developer Toolkit Docs",
     "description": "CLI/docs reference theme — dense, mono-forward, chip statuses.",
     "tags": "demo, docs, toolkit, dev",
     "settings": {"prefix": "tk", "iconSize": 26,
                  "colors": {"radius": 6},
                  "type": {"baseSize": 14, "scale": 1.125}},
     "assets": [("palette", 4), ("icon", "terminal"), ("icon", "book"),
                ("icon", "code"), ("snippet", "Badge chips"),
                ("snippet", "Sticky navbar")]},
    {"name": "HTML Email Signature",
     "description": "Client-safe signature kit — table layouts, web-safe stacks.",
     "tags": "demo, email, signature, business",
     "settings": {"prefix": "sig", "iconSize": 24,
                  "colors": {"radius": 0},
                  "type": {"baseSize": 14, "scale": 1.1},
                  "preview": {"mode": "snippet"}},
     "assets": [("palette", 7), ("icon", "mail"), ("snippet", "Email signature")]},
    {"name": "Email Newsletter",
     "description": "Newsletter masthead and content tokens, web-safe typography.",
     "tags": "demo, email, newsletter, marketing",
     "settings": {"prefix": "news", "iconSize": 24,
                  "colors": {"radius": 6},
                  "type": {"baseSize": 15, "scale": 1.2}},
     "assets": [("palette", 7), ("icon", "mail"), ("snippet", "Newsletter masthead"),
                ("snippet", "Testimonial")]},
    {"name": "Recipe Collection",
     "description": "Warm kitchen palette with menu icons and markdown recipe cards.",
     "tags": "demo, recipes, food, hobby",
     "settings": {"prefix": "kitchen", "iconSize": 40,
                  "colors": {"radius": 16},
                  "type": {"baseSize": 17, "scale": 1.2}},
     "assets": [("palette", 6), ("icon", "coffee"), ("icon", "clock"),
                ("icon", "book"), ("snippet", "Recipe card")]},
    {"name": "Design System Starter",
     "description": "Full token baseline to fork — every role explicit, dual palettes.",
     "tags": "demo, design-system, tokens, foundation",
     "settings": {"prefix": "ds", "iconSize": 32,
                  "colors": {"bg": "#0E1116", "surface": "#161C23",
                             "ink": "#E6EDF3", "muted": "#8DA0AF",
                             "accent": "#37B8C4", "border": "#232B33",
                             "radius": 10},
                  "type": {"baseSize": 16, "scale": 1.25}},
     "assets": [("palette", 0), ("palette", 3), ("icon", "pen"),
                ("icon", "compass"), ("snippet", "Badge chips"),
                ("snippet", "Hero split")]},
    {"name": "Mobile App UI Kit",
     "description": "Rounded mobile-first tokens — big radius, generous sizes.",
     "tags": "demo, mobile, app, ui-kit",
     "settings": {"prefix": "mob", "iconSize": 44,
                  "colors": {"radius": 22},
                  "type": {"baseSize": 16, "scale": 1.2}},
     "assets": [("palette", 5), ("icon", "user"), ("icon", "heart"),
                ("icon", "image"), ("snippet", "Stat card")]},
    {"name": "Conference & Events",
     "description": "Loud event-site tokens — violet stage light, big display type.",
     "tags": "demo, events, conference, marketing",
     "settings": {"prefix": "conf", "iconSize": 42,
                  "colors": {"radius": 12},
                  "type": {"baseSize": 17, "scale": 1.414}},
     "assets": [("palette", 5), ("icon", "calendar"), ("icon", "speaker"),
                ("icon", "compass"), ("snippet", "Hero split")]},
    {"name": "Nonprofit Landing",
     "description": "Warm, trust-forward landing tokens for a community org.",
     "tags": "demo, nonprofit, landing, community",
     "settings": {"prefix": "give", "iconSize": 38,
                  "colors": {"radius": 10},
                  "type": {"baseSize": 16, "scale": 1.25}},
     "assets": [("palette", 6), ("icon", "heart"), ("icon", "user"),
                ("snippet", "Testimonial"), ("snippet", "Hero split")]},
]


# --------------------------------------------------------------------- files

def _write_icons(demo_dir: Path) -> dict[str, Path]:
    out: dict[str, Path] = {}
    icons_dir = demo_dir / "icons"
    icons_dir.mkdir(parents=True, exist_ok=True)
    for name, body in ICONS.items():
        p = icons_dir / (name + ".svg")
        p.write_text(_SVG.format(stroke="39B8C4", body=body),
                     encoding="utf-8")
        out[name] = p
    return out


def _write_font(demo_dir: Path, fonts_dir: str) -> Path | None:
    """Copy one bundled font into the demo tree so removal stays uniform."""
    src = Path(fonts_dir) / "BebasNeue-Regular.ttf"
    if not src.is_file():
        return None
    dest_dir = demo_dir / "fonts" / "Bebas Neue"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "BebasNeue-Regular.ttf"
    if not dest.exists():
        shutil.copyfile(src, dest)
    return dest


# -------------------------------------------------------------------- status

def demo_ids(con: sqlite3.Connection) -> dict:
    raw = settings.get(con, DEMO_SETTING, None)
    data: dict = {}
    try:
        loaded = json.loads(raw) if raw else {}
        if isinstance(loaded, dict):
            data = loaded
    except (ValueError, TypeError):
        data = {}
    for k in ("projects", "snippets", "palettes", "assets", "tags"):
        v = data.get(k)
        data[k] = v if isinstance(v, list) else []
    return data


def is_installed(con: sqlite3.Connection) -> bool:
    d = demo_ids(con)
    return bool(d["projects"] or d["snippets"] or d["palettes"] or d["assets"])


# -------------------------------------------------------------------- install

def install(con: sqlite3.Connection, demo_dir: str, fonts_dir: str) -> dict:
    if is_installed(con):
        return {"installed": False, "reason": "already present"}
    demo_dir = Path(demo_dir)
    demo_dir.mkdir(parents=True, exist_ok=True)
    ids: dict = {"projects": [], "snippets": [], "palettes": [],
                 "assets": [], "tags": []}
    try:
        return _install(con, demo_dir, fonts_dir, ids)
    except Exception:
        # failure-atomic: flush what was recorded so far and sweep it back
        # out, so a crashed install can never leave half a suite behind
        try:
            settings.set(con, DEMO_SETTING, json.dumps(ids))
            con.commit()
            remove(con, str(demo_dir),
                   ["projects", "icons", "fonts", "snippets", "palettes",
                    "tags"])
        except Exception:  # noqa: BLE001 — best-effort cleanup
            pass
        raise


def _install(con: sqlite3.Connection, demo_dir: Path, fonts_dir: str,
             ids: dict) -> dict:
    src = con.execute(
        "SELECT id FROM source WHERE path = ?", (str(demo_dir),)).fetchone()
    if src:
        source_id = src["id"]
    else:
        source_id = int(con.execute(
            "INSERT INTO source (kind, path, label)"
            " VALUES ('folder', ?, 'Fengrid demo assets')",
            (str(demo_dir),)).lastrowid or 0)

    # -- demo tag (recorded so selective removal can take it or leave it)
    tag = con.execute("SELECT id FROM tag WHERE name = ?", (DEMO_TAG,)).fetchone()
    if tag:
        demo_tag_id = tag["id"]
    else:
        demo_tag_id = con.execute(
            "INSERT INTO tag(name) VALUES (?)", (DEMO_TAG,)).lastrowid
        ids["tags"].append(demo_tag_id)

    # -- icon files + rows
    icon_rows: dict[str, int] = {}
    now = time.time()
    for name, path in _write_icons(demo_dir).items():
        theme, context = ICON_META[name]
        size = path.stat().st_size
        row = con.execute(
            "INSERT INTO asset (source_id, kind, path, name, ext, theme,"
            " context, bytes, mtime) VALUES (?, 'icon', ?, ?, 'svg', ?, ?, ?, ?)",
            (source_id, str(path), name, theme, context, size, now))
        icon_rows[name] = int(row.lastrowid)
        ids["assets"].append(icon_rows[name])
        con.execute("INSERT OR IGNORE INTO asset_tag(asset_id, tag_id)"
                    " VALUES (?, ?)", (icon_rows[name], demo_tag_id))

    # -- font row (real metadata columns from the family's faces)
    font_path = _write_font(demo_dir, fonts_dir)
    font_row_id = None
    if font_path:
        row = con.execute(
            "INSERT INTO asset (source_id, kind, path, name, ext, family,"
            " style, weight, italic, bytes, mtime)"
            " VALUES (?, 'font', ?, 'BebasNeue-Regular', 'ttf',"
            " 'Bebas Neue', 'Regular', 400, 0, ?, ?)",
            (source_id, str(font_path), font_path.stat().st_size, now))
        font_row_id = int(row.lastrowid)
        ids["assets"].append(font_row_id)
        con.execute("INSERT OR IGNORE INTO asset_tag(asset_id, tag_id)"
                    " VALUES (?, ?)", (font_row_id, demo_tag_id))

    # -- palettes
    palette_rows: list[int] = []
    for name, hexes, tags in PALETTES:
        palette_rows.append(core_colors.save_palette(con, name, hexes, tags))
        ids["palettes"].append(palette_rows[-1])

    # -- snippets
    snippet_rows: dict[str, int] = {}
    for s in SNIPPETS:
        sid = core_snippets.create_snippet(
            con, s["title"], s["description"], s["language"],
            s["html"], s["css"], s["js"], s["tags"])
        snippet_rows[s["title"]] = sid
        ids["snippets"].append(sid)

    # -- projects
    for spec in P_PROJECTS:
        pid = core_projects.create_project(
            con, spec["name"], spec["description"], spec["tags"])
        ids["projects"].append(pid)
        s = json.loads(json.dumps(spec["settings"]))
        s.setdefault("colors", {})
        s.setdefault("type", {})
        s.setdefault("preview", {"mode": "site"})
        if font_row_id:
            s["type"].setdefault("heading", "Bebas Neue")
        core_projects.update_project(con, pid, settings=s)
        for kind, ref in spec["assets"]:
            if kind == "icon":
                core_projects.add_asset(con, pid, "icon", icon_rows[ref],
                                        ref)
            elif kind == "palette":
                core_projects.add_asset(con, pid, "palette",
                                        palette_rows[ref], "")
            elif kind == "snippet":
                core_projects.add_asset(con, pid, "snippet",
                                        snippet_rows[ref], ref)
            elif kind == "font" and font_row_id:
                core_projects.add_asset(con, pid, "font", font_row_id, ref)

    # preview mode: point the snippet-driven projects at their snippet row
    for spec, pid in zip(P_PROJECTS, ids["projects"]):
        pv = (spec["settings"].get("preview") or {})
        if pv.get("mode") == "snippet":
            proj = core_projects.get_project(con, pid)
            sn = [a for a in proj["assets"] if a["asset_kind"] == "snippet"]
            if sn:
                st = proj["settings"]
                st["preview"]["snippetId"] = sn[0]["asset_id"]
                core_projects.update_project(con, pid, settings=st)

    settings.set(con, DEMO_SETTING, json.dumps(ids))
    con.commit()
    return {"installed": True,
            "projects": len(ids["projects"]),
            "snippets": len(ids["snippets"]),
            "palettes": len(ids["palettes"]),
            "icons": len(icon_rows),
            "font": bool(font_row_id)}


# -------------------------------------------------------------------- remove

def remove(con: sqlite3.Connection, demo_dir: str,
           kinds: list[str]) -> dict:
    """Remove selected demo data kinds. Recorded ids drive the deletion, so
    anything the user created since stays untouched. Keeps the rows the
    caller asked to keep; the `demo_ids` ledger is updated accordingly."""
    ids = demo_ids(con)
    demo_dir = Path(demo_dir)
    removed: dict[str, int] = {}

    if "projects" in kinds:
        n = 0
        for pid in ids["projects"]:
            cur = con.execute("SELECT id FROM projects WHERE id = ?",
                              (pid,)).fetchone()
            if cur:
                core_projects.delete_project(con, pid)
                n += 1
        removed["projects"] = n
        ids["projects"] = []

    asset_ids = list(ids["assets"])
    if "icons" in kinds or "fonts" in kinds:
        doomed: list[int] = []
        for aid in asset_ids:
            row = con.execute("SELECT id, kind, path FROM asset WHERE id = ?",
                              (aid,)).fetchone()
            if row is None:
                continue
            if (row["kind"] == "icon" and "icons" in kinds) or \
               (row["kind"] == "font" and "fonts" in kinds):
                doomed.append(row["id"])
        # drop project references first so nothing dangles on live projects
        for aid in doomed:
            con.execute("DELETE FROM project_asset WHERE asset_kind IN"
                        " ('icon','font') AND asset_id = ?", (aid,))
            row = con.execute("SELECT path FROM asset WHERE id = ?",
                              (aid,)).fetchone()
            if row is not None:
                con.execute("DELETE FROM asset WHERE id = ?", (aid,))
                p = Path(row["path"])
                if str(p).startswith(str(demo_dir)) and p.exists():
                    p.unlink()
        removed["assets"] = len(doomed)
        kept = [a for a in asset_ids if a not in set(doomed)]
        if "icons" in kinds and "fonts" in kinds:
            ids["assets"] = []
        else:
            ids["assets"] = kept
        # tidy the demo tree when a kind is fully emptied
        if "icons" in kinds and (demo_dir / "icons").is_dir():
            shutil.rmtree(demo_dir / "icons", ignore_errors=True)
        if "fonts" in kinds and (demo_dir / "fonts").is_dir():
            shutil.rmtree(demo_dir / "fonts", ignore_errors=True)

    if "snippets" in kinds:
        n = 0
        for sid in ids["snippets"]:
            cur = con.execute("SELECT id FROM snippet WHERE id = ?",
                              (sid,)).fetchone()
            if cur:
                con.execute("DELETE FROM snippet WHERE id = ?", (sid,))
                con.execute("DELETE FROM project_asset WHERE asset_kind ="
                            " 'snippet' AND asset_id = ?", (sid,))
                n += 1
        removed["snippets"] = n
        ids["snippets"] = []

    if "palettes" in kinds:
        n = 0
        for pid in ids["palettes"]:
            cur = con.execute("SELECT id FROM palette WHERE id = ?",
                              (pid,)).fetchone()
            if cur:
                con.execute("DELETE FROM palette_color WHERE palette_id = ?",
                            (pid,))
                con.execute("DELETE FROM palette WHERE id = ?", (pid,))
                con.execute("DELETE FROM project_asset WHERE asset_kind ="
                            " 'palette' AND asset_id = ?", (pid,))
                n += 1
        removed["palettes"] = n
        ids["palettes"] = []

    if "tags" in kinds:
        n = 0
        for tid in ids["tags"]:
            cur = con.execute("SELECT id FROM tag WHERE id = ?", (tid,)).fetchone()
            if cur:
                con.execute("DELETE FROM tag WHERE id = ?", (tid,))
                n += 1
        removed["tags"] = n
        ids["tags"] = []
        # the 'demo' tag only exists for our rows; drop it too if now unused
        leftover = con.execute(
            "SELECT t.id FROM tag t WHERE t.name = ? AND NOT EXISTS"
            " (SELECT 1 FROM asset_tag at WHERE at.tag_id = t.id)",
            (DEMO_TAG,)).fetchone()
        if leftover:
            con.execute("DELETE FROM tag WHERE id = ?", (leftover["id"],))

    if not any(ids[k] for k in ("projects", "snippets", "palettes", "assets")):
        # nothing demo remains — clear the marker and the directory
        if demo_dir.is_dir():
            shutil.rmtree(demo_dir, ignore_errors=True)
        settings.set(con, DEMO_SETTING, "")
    else:
        settings.set(con, DEMO_SETTING, json.dumps(ids))
    con.commit()
    return removed
