"""Color math, harmony generation, and palette persistence (colors pane).

Port of the 0.x colors.html logic (see the pane's JS for provenance):
- same harmony hue offsets and the fract(sin(seed)) jitter, so palettes
  generated here match what the web pane would roll for the same seed;
- WCAG 2.x relative luminance / contrast and the AAA / AA / AA·lg / fail
  labels;
- deterministic color naming from the same curated anchor set;
- exports: CSS custom properties, JSON, and the palettd-style board
  (SVG, plus a Pillow-rendered 2x PNG).

Persistence lives in the library's own SQLite (palette / palette_color
tables) — replacing the 0.x per-pane server endpoints, same local-first
posture (ADR-0001 §6).
"""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import time
from pathlib import Path

HARMONIES = ("pleasing", "analogous", "complementary", "triadic", "monochrome")

# exact offsets from colors.html generate()
_HARMONY_HUES = {
    "pleasing": [0, 28, -32, 155, -140],   # golden-ratio-ish spread
    "analogous": [0, -18, 18, -36, 36],
    "complementary": [0, 0, 180, 180, 12],
    "triadic": [0, 120, 240, 0, 120],
    "monochrome": [0, 0, 0, 0, 0],
}
_L_BASE = {"light": [88, 74, 58, 42, 28], "dark": [82, 66, 52, 38, 24]}
_S_BASE = [62, 52, 55, 48, 42]


# ----------------------------------------------------------------- color math

def hex2rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    if len(h) != 6:
        raise ValueError(f"bad hex: {h!r}")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgb2hex(r: float, g: float, b: float) -> str:
    c = lambda v: f"{max(0, min(255, round(v))):02x}"
    return f"#{c(r)}{c(g)}{c(b)}"


def rgb2hsl(r: int, g: int, b: int) -> tuple[float, float, float]:
    r, g, b = r / 255, g / 255, b / 255
    mx, mn = max(r, g, b), min(r, g, b)
    h = s = 0.0
    l = (mx + mn) / 2
    if mx != mn:
        d = mx - mn
        s = d / (2 - mx - mn) if l > 0.5 else d / (mx + mn)
        if mx == r:
            h = (g - b) / d + (6 if g < b else 0)
        elif mx == g:
            h = (b - r) / d + 2
        else:
            h = (r - g) / d + 4
        h /= 6
    return h * 360, s * 100, l * 100


def hsl2rgb(h: float, s: float, l: float) -> tuple[int, int, int]:
    h = ((h % 360) + 360) % 360 / 360
    s, l = s / 100, l / 100
    q = l * (1 + s) if l < 0.5 else l + s - l * s
    p = 2 * l - q

    def f(t):
        if t < 0:
            t += 1
        if t > 1:
            t -= 1
        if t < 1 / 6:
            return p + (q - p) * 6 * t
        if t < 1 / 2:
            return q
        if t < 2 / 3:
            return p + (q - p) * (2 / 3 - t) * 6
        return p

    return round(f(h + 1 / 3) * 255), round(f(h) * 255), round(f(h - 1 / 3) * 255)


def lum(rgb: tuple[int, int, int]) -> float:
    a = [(v / 255 / 12.92 if v / 255 <= 0.03928
          else ((v / 255 + 0.055) / 1.055) ** 2.4) for v in rgb]
    return 0.2126 * a[0] + 0.7152 * a[1] + 0.0722 * a[2]


def contrast(rgb1, rgb2) -> float:
    l1, l2 = lum(rgb1), lum(rgb2)
    return (max(l1, l2) + 0.05) / (min(l1, l2) + 0.05)


def wcag_label(r: float) -> str:
    return "AAA" if r >= 7 else "AA" if r >= 4.5 else "AA·lg" if r >= 3 else "fail"


def best_ink(rgb) -> str:
    return ("#FFFFFF" if contrast(rgb, (255, 255, 255))
            >= contrast(rgb, (16, 20, 24)) else "#101418")


# deterministic color naming — the same anchor set as colors.html
_NAME_PAIRS = [
    ("#000000", "Black"), ("#FFFFFF", "White"), ("#F5F5F5", "Whisper"),
    ("#E0E0E0", "Silver"), ("#A0A0A0", "Gray"), ("#616161", "Slate Gray"),
    ("#2B2B2B", "Charcoal"), ("#101418", "Night Glass"), ("#FF0000", "Red"),
    ("#DC143C", "Crimson"), ("#B22222", "Firebrick"), ("#8B0000", "Dark Red"),
    ("#FF6347", "Tomato"), ("#FF7F50", "Coral"), ("#E9967A", "Salmon"),
    ("#FFA07A", "Light Salmon"), ("#FF4500", "Orange Red"),
    ("#FF8C00", "Dark Orange"), ("#FFA500", "Orange"), ("#FFD700", "Gold"),
    ("#F5B841", "Lit Pane"), ("#DAA520", "Goldenrod"),
    ("#B8860B", "Dark Goldenrod"), ("#F0E68C", "Khaki"),
    ("#ADFF2F", "Green Yellow"), ("#32CD32", "Lime Green"),
    ("#228B22", "Forest Green"), ("#006400", "Dark Green"),
    ("#2E8B57", "Sea Green"), ("#3CB371", "Medium Sea"),
    ("#90EE90", "Light Green"), ("#00FA9A", "Medium Spring"),
    ("#00C48B", "Jade"), ("#40E0D0", "Turquoise"),
    ("#00CED1", "Dark Turquoise"), ("#39B8C4", "Pane Teal"),
    ("#20B2AA", "Light Sea"), ("#5F9EA0", "Cadet Blue"), ("#00FFFF", "Cyan"),
    ("#87CEEB", "Sky Blue"), ("#00BFFF", "Deep Sky Blue"),
    ("#1E90FF", "Dodger Blue"), ("#6D4FC4", "Deep Violet"),
    ("#4169E1", "Royal Blue"), ("#0000FF", "Blue"), ("#191970", "Midnight"),
    ("#A78BFA", "Soft Violet"), ("#8A2BE2", "Blue Violet"),
    ("#9400D3", "Dark Violet"), ("#BA55D3", "Orchid"),
    ("#9932CC", "Dark Orchid"), ("#B0306A", "Rosewine"), ("#800080", "Purple"),
    ("#4B0082", "Indigo"), ("#E879A6", "Petal Pink"), ("#FF69B4", "Hot Pink"),
    ("#FFB6C1", "Light Pink"), ("#F0885C", "Ember Coral"), ("#C44A1E", "Rust"),
    ("#8B4513", "Saddle Brown"), ("#A0522D", "Sienna"),
    ("#D2691E", "Chocolate"), ("#CD853F", "Peru"), ("#DEB887", "Burlywood"),
    ("#F5DEB3", "Wheat"), ("#FAF5E9", "Alabaster"), ("#F5F5DC", "Beige"),
    ("#FFF8DC", "Cornsilk"),
]
_HUE_NAMES = [(15, "Red"), (45, "Orange"), (70, "Yellow"), (150, "Green"),
              (190, "Teal"), (230, "Blue"), (280, "Violet"), (330, "Magenta"),
              (345, "Rose"), (360, "Red")]
_L_NAMES = [(20, "Deep"), (40, "Dark"), (60, "Medium"), (80, "Soft"),
            (95, "Pale")]


def color_name(hex_color: str) -> str:
    rgb = hex2rgb(hex_color)
    hsl = rgb2hsl(*rgb)
    best, bd = None, 1e9
    for anchor, name in _NAME_PAIRS:
        c = hex2rgb(anchor)
        d = (rgb[0] - c[0]) ** 2 * 0.9 + (rgb[1] - c[1]) ** 2 * 1.2 \
            + (rgb[2] - c[2]) ** 2 * 0.7
        if d < bd:
            bd, best = d, name
    if bd < 900:
        return best
    hue = "Neutral"
    if hsl[1] > 10:
        for limit, name in _HUE_NAMES:
            if hsl[0] < limit:
                hue = name
                break
    l_name = "Medium"
    for limit, name in _L_NAMES:
        if hsl[2] < limit:
            l_name = name
            break
    return f"{l_name} {hue}"


# ------------------------------------------------------------------ generator

def _pick(seed: float) -> float:
    """fract(sin(seed) * 10000) — the exact jitter helper from colors.html."""
    x = math.sin(seed) * 10000
    return x - math.floor(x)


def generate(rule: str, colors: list[dict], base_hue: float | None = None,
             mode: str = "dark") -> list[dict]:
    """Reroll unlocked swatches under a harmony rule.

    colors: [{hex, locked}] (2..5 entries supported by the UI). Returns a new
    list; locked swatches pass through untouched and ANCHOR the generation:
    unlocked slots take their hue relative to the first locked swatch's
    actual hue, offset by the harmony template — so locks survive scheme
    switches and the fresh colors coordinate with them (e.g. two locks in
    Complementary → Analogous Generate keeps both and hangs the rest off
    them). Without locks this reduces to the historical base_hue behavior.
    Deterministic for a given base_hue (tests); the UI passes None ->
    time-seeded like the web pane.
    """
    if rule not in HARMONIES:
        raise ValueError(f"unknown harmony rule: {rule}")
    if base_hue is None:
        base_hue = _pick(time.time() % 100000) * 360
    l_base = _L_BASE.get(mode, _L_BASE["dark"])
    hues = _HARMONY_HUES[rule]

    anchor_slot = next((i for i in range(5)
                        if i < len(colors) and colors[i].get("locked")), None)
    if anchor_slot is None:
        anchor_hue, template0 = base_hue, 0
    else:
        r, g, b = hex2rgb(colors[anchor_slot]["hex"])
        anchor_hue = rgb2hsl(r, g, b)[0]      # rgb2hsl returns (h, s, l)
        template0 = hues[anchor_slot]

    out: list[dict] = []
    for i in range(5):
        prev = colors[i] if i < len(colors) else None
        if prev is not None and prev.get("locked"):
            out.append(prev)
            continue
        jitter = _pick(i * 7 + 3) * 14 - 7 if rule == "pleasing" else 0
        h = (anchor_hue + (hues[i] - template0) + jitter + 360) % 360
        l = l_base[i] + math.floor(_pick(i * 13 + 7) * 10) - 5
        s = _S_BASE[i] + math.floor(_pick(i * 17 + 11) * 16) - 8
        rgb = hsl2rgb(h, max(8, min(96, s)), max(8, min(94, l)))
        out.append({"hex": rgb2hex(*rgb),
                    "locked": bool(prev["locked"]) if prev else False})
    return out


# ---------------------------------------------------------------- persistence

def list_palettes(con: sqlite3.Connection, q: str = "",
                  sort: str = "updated") -> list[dict]:
    order = {"updated": "updated DESC", "name": "name COLLATE NOCASE",
             "created": "created DESC"}.get(sort, "updated DESC")
    where, params = "", []
    if q:
        where = "WHERE name LIKE ? OR tags LIKE ?"
        params = [f"%{q}%", f"%{q}%"]
    rows = con.execute(
        f"SELECT id, name, tags, created, updated FROM palette {where}"
        f" ORDER BY {order}", params).fetchall()
    out = []
    for r in rows:
        colors = [c[0] for c in con.execute(
            "SELECT hex FROM palette_color WHERE palette_id = ?"
            " ORDER BY position", (r["id"],))]
        out.append({"id": r["id"], "name": r["name"], "tags": r["tags"] or "",
                    "updated": r["updated"], "created": r["created"],
                    "colors": colors})
    return out


def palette_colors(con: sqlite3.Connection, palette_id: int) -> list[dict]:
    rows = con.execute(
        "SELECT hex, locked FROM palette_color WHERE palette_id = ?"
        " ORDER BY position", (palette_id,)).fetchall()
    return [{"hex": r["hex"], "locked": bool(r["locked"])} for r in rows]


def save_palette(con: sqlite3.Connection, name: str, hexes: list[str],
                 tags: str = "", palette_id: int | None = None) -> int:
    """Insert (or update, when palette_id is given) and return the id."""
    name = (name or "").strip() or "Untitled palette"
    now = time.time()
    if palette_id is None:
        cur = con.execute(
            "INSERT INTO palette(name, tags, created, updated)"
            " VALUES (?, ?, ?, ?)", (name, tags, now, now))
        pid = cur.lastrowid
    else:
        if con.execute("SELECT 1 FROM palette WHERE id = ?",
                       (palette_id,)).fetchone() is None:
            raise ValueError(f"unknown palette id: {palette_id}")
        con.execute("UPDATE palette SET name = ?, tags = ?, updated = ?"
                    " WHERE id = ?", (name, tags, now, palette_id))
        pid = palette_id
        con.execute("DELETE FROM palette_color WHERE palette_id = ?", (pid,))
    for i, hx in enumerate(hexes):
        con.execute(
            "INSERT INTO palette_color(palette_id, position, hex, locked)"
            " VALUES (?, ?, ?, 0)", (pid, i, hx))
    con.commit()
    return pid


def delete_palette(con: sqlite3.Connection, palette_id: int) -> None:
    con.execute("DELETE FROM palette WHERE id = ?", (palette_id,))
    con.commit()


# -------------------------------------------------------------------- exports

_SAFE = re.compile(r"[^a-z0-9]+")


def _slug(name: str) -> str:
    return _SAFE.sub("-", (name or "").lower()).strip("-") or "palette"


def export_css(name: str, hexes: list[str]) -> str:
    base = _slug(name)
    body = ",\n".join(f"  --{base}-{i + 1}: {hx};"
                      for i, hx in enumerate(hexes))
    return f":root {{\n{body}\n}}\n"


def export_json(name: str, hexes: list[str]) -> str:
    return json.dumps({"name": name or "Untitled palette",
                       "colors": list(hexes)}, indent=2) + "\n"


_XML_ESC = (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"), ('"', "&quot;"))


def _esc_xml(s: str) -> str:
    for old, new in _XML_ESC:
        s = s.replace(old, new)
    return s


def board_svg(title: str, hexes: list[str]) -> str:
    """Palettd-style board — the exact layout from colors.html boardSvg()."""
    W, H, PAD, GAP, R = 640, 400, 28, 10, 12
    n = len(hexes)
    inner = W - 2 * PAD
    sw = (inner - GAP * (n - 1)) / n
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}"'
           f' viewBox="0 0 {W} {H}">',
           f'<rect width="{W}" height="{H}" rx="16" fill="#FFFFFF"/>',
           f'<text x="{PAD}" y="{PAD + 14}" font-family="Inter, Arial,'
           f' sans-serif" font-size="17" font-weight="600" fill="#16202B">'
           f'{_esc_xml(title)}</text>']
    cy, ch = 72, 220
    for i, hx in enumerate(hexes):
        x = PAD + i * (sw + GAP)
        rgb = hex2rgb(hx)
        ink = "#FFFFFF" if contrast(rgb, (255, 255, 255)) >= 3 else "#16202B"
        name = color_name(hx)
        fs = 8 if len(name) * 5.4 > sw - 12 else 10
        out.append(f'<clipPath id="sw{i}"><rect x="{x}" y="{cy}"'
                   f' width="{sw}" height="{ch}" rx="{R}"/></clipPath>')
        out.append(f'<rect x="{x}" y="{cy}" width="{sw}" height="{ch}"'
                   f' rx="{R}" fill="{hx}" stroke="#E5E5E5"'
                   f' stroke-opacity="0.6"/>')
        out.append(f'<g clip-path="url(#sw{i})">')
        out.append(f'<text x="{x + 10}" y="{cy + 24}" font-family="Iosevka,'
                   f' monospace" font-size="12" font-weight="500"'
                   f' fill="{ink}">{_esc_xml(hx.upper())}</text>')
        out.append(f'<text x="{x + 10}" y="{cy + 40}" font-family="Inter,'
                   f' Arial, sans-serif" font-size="{fs}" fill="{ink}"'
                   f' opacity="0.85">{_esc_xml(name)}</text>')
        out.append('</g>')
    fy = H - 24
    out.append(f'<text x="{PAD}" y="{fy}" font-family="Iosevka, monospace"'
               f' font-size="10" letter-spacing="2" fill="#93A3B0">PALETTE</text>')
    out.append(f'<text x="{W - PAD}" y="{fy}" text-anchor="end"'
               f' font-family="Iosevka, monospace" font-size="10"'
               f' fill="#93A3B0">fengrid</text>')
    out.append('</svg>')
    return "\n".join(out)


def write_exports(name: str, hexes: list[str], dest_dir: str | Path,
                  what: str) -> Path:
    """Write one export artifact; returns the output path (atomic per file)."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    stem = _slug(name)
    if what == "css":
        out = dest_dir / f"{stem}.css"
        data = export_css(name, hexes)
        out.write_text(data, encoding="utf-8")
        return out
    if what == "json":
        out = dest_dir / f"{stem}.json"
        out.write_text(export_json(name, hexes), encoding="utf-8")
        return out
    if what == "svg":
        out = dest_dir / f"{stem}.svg"
        out.write_text(board_svg(name, hexes), encoding="utf-8")
        return out
    if what == "png":
        return _board_png(name, hexes, dest_dir, stem)
    raise ValueError(f"unknown export kind: {what}")


def _board_png(name: str, hexes: list[str], dest_dir: Path, stem: str) -> Path:
    """2x PNG render of the board, drawn directly with Pillow (no SVG
    rasteriser dependency — the 0.x pane used canvas drawImage; the layout
    mirrors boardSvg)."""
    from PIL import Image, ImageDraw, ImageFont

    scale = 2
    W, H, PAD, GAP, R = 640 * scale, 400 * scale, 28 * scale, 10 * scale, 12 * scale
    n = len(hexes)
    inner = W - 2 * PAD
    sw = (inner - GAP * (n - 1)) / n

    img = Image.new("RGB", (W, H), "#FFFFFF")
    d = ImageDraw.Draw(img)

    def font(size: int, weight_bold: bool = False):
        try:
            f = ImageFont.load_default(size=size)
        except TypeError:  # Pillow < 10.1
            f = ImageFont.load_default()
        return f

    title_f, label_f, name_f, foot_f = (font(17 * scale), font(12 * scale),
                                        font(10 * scale), font(10 * scale))
    d.rounded_rectangle([0, 0, W - 1, H - 1], radius=16 * scale,
                        fill="#FFFFFF", outline="#E5E5E5")
    d.text((PAD, PAD), name or "Untitled palette", fill="#16202B",
           font=title_f)
    cy, ch = 72 * scale, 220 * scale
    for i, hx in enumerate(hexes):
        x = int(PAD + i * (sw + GAP))
        w = int(sw)
        rgb = hex2rgb(hx)
        ink = "#FFFFFF" if contrast(rgb, (255, 255, 255)) >= 3 else "#16202B"
        d.rounded_rectangle([x, cy, x + w, cy + ch], radius=R, fill=hx,
                            outline="#E5E5E5")
        d.text((x + 10 * scale, cy + 10 * scale), hx.upper(), fill=ink,
               font=label_f)
        d.text((x + 10 * scale, cy + 28 * scale), color_name(hx), fill=ink,
               font=name_f)
    fy = H - 24 * scale
    d.text((PAD, fy), "PALETTE", fill="#93A3B0", font=foot_f)
    foot = "fengrid"
    fw = d.textlength(foot, font=foot_f)
    d.text((W - PAD - fw, fy), foot, fill="#93A3B0", font=foot_f)

    out = dest_dir / f"{stem}.png"
    tmp = out.with_suffix(out.suffix + ".tmp")
    img.save(tmp, "PNG")
    os.replace(tmp, out)
    return out
