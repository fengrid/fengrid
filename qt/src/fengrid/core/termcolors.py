"""Terminal color themes: model, derivation, and emulator exports.

A theme is a dict: {name, bg, fg, cursor, selection, normal: {8 ANSI},
bright: {8 ANSI}} with #RRGGBB values everywhere. Exports cover iTerm2
(plist via plistlib), Windows Terminal (JSON scheme fragment), Guake
(palette string), GNOME Terminal (dconf shell script), kitty and
alacritty config files, and generic JSON. `derive()` builds a full 16+
color theme from bg/fg/accent deterministically, and `snippet_kwargs()`
packs a theme into a code-snippet (live HTML terminal preview + the
exports in a comment) so themes can live in snippet collections and be
attached to projects.
"""

from __future__ import annotations

import json
import plistlib
from pathlib import Path

from . import snippets as core_snippets

# canonical slot order (normal 0-7, bright 8-15)
SLOTS = ("black", "red", "green", "yellow", "blue", "magenta", "cyan",
         "white", "brightBlack", "brightRed", "brightGreen", "brightYellow",
         "brightBlue", "brightMagenta", "brightCyan", "brightWhite")

_DEFAULT_DARK = {
    "black": "#2E3440", "red": "#BF616A", "green": "#A3BE8C",
    "yellow": "#EBCB8B", "blue": "#81A1C1", "magenta": "#B48EAD",
    "cyan": "#88C0D0", "white": "#E5E9F0",
    "brightBlack": "#4C566A", "brightRed": "#D08770",
    "brightGreen": "#A3BE8C", "brightYellow": "#EBCB8B",
    "brightBlue": "#81A1C1", "brightMagenta": "#B48EAD",
    "brightCyan": "#8FBCBB", "brightWhite": "#ECEFF4",
}


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _shift(hex_color: str, ds: float, dl: float, dh: float = 0.0) -> str:
    """HSL-shift a hex color (colors pane helpers do the math)."""
    from .colors import hex2rgb, hsl2rgb, rgb2hsl, rgb2hex
    r, g, b = hex2rgb(hex_color)
    h, s, l = rgb2hsl(r, g, b)
    return rgb2hex(*hsl2rgb((h + dh) % 360, _clamp(s + ds, 8, 96),
                            _clamp(l + dl, 6, 94)))


def normalize(theme: dict) -> dict:
    """Fill every slot; missing values fall back to the Nord-ish defaults."""
    t = {
        "name": str(theme.get("name") or "Untitled terminal theme"),
        "bg": theme.get("bg") or "#1E2127",
        "fg": theme.get("fg") or "#D8DEE9",
        "cursor": theme.get("cursor") or theme.get("fg") or "#D8DEE9",
        "selection": theme.get("selection") or "#3B4252",
        "normal": {}, "bright": {},
    }
    for slot in SLOTS[:8]:
        t["normal"][slot] = theme.get("normal", {}).get(slot) \
            or _DEFAULT_DARK[slot]
    for slot in SLOTS[8:]:
        t["bright"][slot] = theme.get("bright", {}).get(slot) \
            or _DEFAULT_DARK[slot]
    return t


def derive(bg: str, fg: str, accent: str, name: str = "",
           selection: str = "") -> dict:
    """A full theme from three anchors. Deterministic; ANSI hues rotate off
    the accent, brightness lifts for the bright variants."""
    base = {
        "black": _shift(bg, -4, -6),
        "red": _shift(accent, 0, 2, 158),
        "green": _shift(accent, -6, 10, 105),
        "yellow": _shift(accent, 12, 12, 52),
        "blue": _shift(accent, 4, -2, 210),
        "magenta": _shift(accent, 6, 0, 300),
        "cyan": _shift(accent, -2, 8, 168),
        "white": _shift(fg, 0, -6),
        "brightBlack": _shift(bg, -2, 22),
        "brightRed": _shift(accent, 2, 12, 158),
        "brightGreen": _shift(accent, -4, 18, 105),
        "brightYellow": _shift(accent, 10, 18, 52),
        "brightBlue": _shift(accent, 2, 10, 210),
        "brightMagenta": _shift(accent, 4, 10, 300),
        "brightCyan": _shift(accent, 0, 16, 168),
        "brightWhite": _shift(fg, 0, 8),
    }
    return normalize({
        "name": name or "Derived terminal theme",
        "bg": bg, "fg": fg,
        "cursor": fg,
        "selection": selection or _shift(bg, 0, 12),
        "normal": {k: base[k] for k in SLOTS[:8]},
        "bright": {k: base[k] for k in SLOTS[8:]},
    })


# --------------------------------------------------------------------- exports

def to_json(theme: dict) -> str:
    return json.dumps(normalize(theme), indent=2)


def to_iterm2(theme: dict) -> bytes:
    """iTerm2 .itermcolors plist (components are 0..1 floats)."""
    from .colors import hex2rgb
    t = normalize(theme)

    def comp(hex_color: str) -> dict:
        r, g, b = hex2rgb(hex_color)
        return {"Red Component": round(r / 255, 5),
                "Green Component": round(g / 255, 5),
                "Blue Component": round(b / 255, 5)}

    keys = ["Ansi %d Color" % i for i in range(16)]
    values = [t["normal"][s] for s in SLOTS[:8]] + \
             [t["bright"][s] for s in SLOTS[8:]]
    plist: dict = {}
    for key, val in zip(keys, values):
        plist[key] = comp(val)
    plist["Background Color"] = comp(t["bg"])
    plist["Foreground Color"] = comp(t["fg"])
    plist["Cursor Color"] = comp(t["cursor"])
    plist["Selected Text Color"] = comp(t["selection"])
    return plistlib.dumps(plist)


def to_windows_terminal(theme: dict) -> str:
    t = normalize(theme)
    wt = {"name": t["name"], "background": t["bg"], "foreground": t["fg"],
          "cursorColor": t["cursor"], "selectionBackground": t["selection"]}
    for slot in SLOTS[:8]:
        wt[slot] = t["normal"][slot]
    # Windows Terminal names: brightBlack -> brightBlack etc. already match
    for slot in SLOTS[8:]:
        wt[slot] = t["bright"][slot]
    return json.dumps(wt, indent=2)


def to_guake(theme: dict) -> str:
    """Guake palette string: 16 ANSI + background + foreground."""
    t = normalize(theme)
    vals = [t["normal"][s] for s in SLOTS[:8]] + \
           [t["bright"][s] for s in SLOTS[8:]] + [t["bg"], t["fg"]]
    return ":".join(vals)


def to_gnome(theme: dict, profile_uuid: str = "PROFILE_UUID") -> str:
    t = normalize(theme)
    palette = ", ".join("'#%s'" % v.lstrip("#").lower()
                        for v in ([t["normal"][s] for s in SLOTS[:8]]
                                  + [t["bright"][s] for s in SLOTS[8:]]))
    base = "/org/gnome/terminal/legacy/profiles:/:{}"
    lines = [
        "# GNOME Terminal — run after replacing PROFILE_UUID with your"
        " profile id (dconf list /org/gnome/terminal/legacy/profiles:/)",
        "PROFILE_UUID=%s" % profile_uuid,
        "dconf write %s/palette \"[%s]\"" % (base, palette),
        "dconf write %s/background-color \"'%s'\"" % (base, t["bg"].lower()),
        "dconf write %s/foreground-color \"'%s'\"" % (base, t["fg"].lower()),
        "dconf write %s/cursor-background-color \"'%s'\""
        % (base, t["cursor"].lower()),
        "dconf write %s/use-theme-colors 'false'" % base,
        "dconf write %s/use-system-font 'false'" % base,
    ]
    return "\n".join(lines) + "\n"


def to_kitty(theme: dict) -> str:
    t = normalize(theme)
    lines = ["# %s — kitty config (append to kitty.conf)" % t["name"],
             "foreground %s" % t["fg"], "background %s" % t["bg"],
             "cursor %s" % t["cursor"], "selection_background %s"
             % t["selection"]]
    for i, slot in enumerate(SLOTS):
        val = t["normal"][slot] if i < 8 else t["bright"][slot]
        lines.append("color%d %s" % (i, val))
    return "\n".join(lines) + "\n"


def to_alacritty(theme: dict) -> str:
    t = normalize(theme)
    out = ["# %s — alacritty.toml" % t["name"], "",
           "[colors]", "draw_bold_text_with_bright_colors = true", "",
           "[colors.primary]", "background = \"%s\"" % t["bg"],
           "foreground = \"%s\"" % t["fg"],
           "[colors.cursor]", "cursor = \"%s\"" % t["cursor"],
           "text = \"%s\"" % t["bg"], "",
           "[colors.selection]", "background = \"%s\"" % t["selection"],
           "text = \"%s\"" % t["fg"], "", "[colors.normal]"]
    for slot in SLOTS[:8]:
        out.append("%s = \"%s\"" % (slot, t["normal"][slot]))
    out += ["", "[colors.bright]"]
    for slot in SLOTS[8:]:
        out.append("%s = \"%s\"" % (slot, t["bright"][slot]))
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------- presets
# Example themes sourced from the Gogh collection (Gogh-Co/Gogh, MIT/Apache)
# — values transcribed from the upstream themes/*.yml definitions.

def _p(name, bg, fg, cursor, selection, ansi16):
    return {"name": name, "bg": bg, "fg": fg, "cursor": cursor,
            "selection": selection,
            "normal": dict(zip(SLOTS[:8], ansi16[:8])),
            "bright": dict(zip(SLOTS[8:], ansi16[8:]))}


PRESETS: list[dict] = [
    _p("Dracula", "#282A36", "#F8F8F2", "#F8F8F2", "#44475A",
       ["#21222C", "#FF5555", "#50FA7B", "#F1FA8C", "#BD93F9", "#FF79C6",
        "#8BE9FD", "#F8F8F2", "#6272A4", "#FF6E6E", "#69FF94", "#FFFFA5",
        "#D6ACFF", "#FF92DF", "#A4FFFF", "#FFFFFF"]),
    _p("Nord", "#2E3440", "#D8DEE9", "#ECEFF4", "#434C5E",
       ["#3B4252", "#BF616A", "#A3BE8C", "#EBCB8B", "#81A1C1", "#B48EAD",
        "#88C0D0", "#E5E9F0", "#4C566A", "#BF616A", "#A3BE8C", "#EBCB8B",
        "#81A1C1", "#B48EAD", "#8FBCBB", "#ECEFF4"]),
    _p("Gruvbox Dark", "#282828", "#EBDBB2", "#EBDBB2", "#3C3836",
       ["#282828", "#CC241D", "#98971A", "#D79921", "#458588", "#B16286",
        "#689D6A", "#A89984", "#928374", "#FB4934", "#B8BB26", "#FABD2F",
        "#83A598", "#D3869B", "#8EC07C", "#EBDBB2"]),
    _p("Solarized Dark", "#001E27", "#708284", "#708284", "#003747",
       ["#002831", "#D11C24", "#738A05", "#A57706", "#2176C7", "#C61C6F",
        "#259286", "#EAE3CB", "#001E27", "#BD3613", "#475B62", "#536870",
        "#708284", "#5956BA", "#819090", "#FCF4DC"]),
    _p("Solarized Light", "#FCF4DC", "#536870", "#536870", "#EEE8D5",
       ["#002831", "#D11C24", "#738A05", "#A57706", "#2176C7", "#C61C6F",
        "#259286", "#EAE3CB", "#001E27", "#BD3613", "#475B62", "#536870",
        "#708284", "#5956BA", "#819090", "#FCF4DC"]),
    _p("One Half Dark", "#282C34", "#DCDFE4", "#A3B3CC", "#3B4048",
       ["#282C34", "#E06C75", "#98C379", "#E5C07B", "#61AFEF", "#C678DD",
        "#56B6C2", "#DCDFE4", "#5D677A", "#E06C75", "#98C379", "#E5C07B",
        "#61AFEF", "#C678DD", "#56B6C2", "#DCDFE4"]),
    _p("One Half Light", "#FAFAFA", "#383A42", "#BFCEFF", "#E4E7EB",
       ["#383A42", "#E45649", "#50A14F", "#C18401", "#0184BC", "#A626A4",
        "#0997B3", "#FAFAFA", "#4F525E", "#E06C75", "#98C379", "#E5C07B",
        "#61AFEF", "#C678DD", "#56B6C2", "#FFFFFF"]),
    _p("Tomorrow Night", "#1D1F21", "#C5C8C6", "#C5C8C6", "#373B41",
       ["#000000", "#CC6666", "#B5BD68", "#F0C674", "#81A2BE", "#B294BB",
        "#8ABEB7", "#FFFFFF", "#000000", "#CC6666", "#B5BD68", "#F0C674",
        "#81A2BE", "#B294BB", "#8ABEB7", "#FFFFFF"]),
    _p("Tokyo Night", "#1A1B26", "#C0CAF5", "#C0CAF5", "#292E42",
       ["#15161E", "#F7768E", "#9ECE6A", "#E0AF68", "#7AA2F7", "#BB9AF7",
        "#7DCFFF", "#A9B1D6", "#414868", "#F7768E", "#9ECE6A", "#E0AF68",
        "#7AA2F7", "#BB9AF7", "#7DCFFF", "#C0CAF5"]),
    _p("Catppuccin Mocha", "#1E1E2E", "#CDD6F4", "#F5E0DC", "#313244",
       ["#45475A", "#F38BA8", "#A6E3A1", "#F9E2AF", "#89B4FA", "#F5C2E7",
        "#94E2D5", "#A6ADC8", "#585B70", "#F37799", "#89D88B", "#EBD391",
        "#74A8FC", "#F2AEDE", "#6BD7CA", "#BAC2DE"]),
    _p("Monokai Pro", "#2D2A2E", "#FCFCFA", "#C1C0C0", "#403E41",
       ["#2D2A2E", "#FF6188", "#A9DC76", "#FFD866", "#FC9867", "#AB9DF2",
        "#78DCE8", "#FCFCFA", "#727072", "#FF6188", "#A9DC76", "#FFD866",
        "#FC9867", "#AB9DF2", "#78DCE8", "#FCFCFA"]),
    _p("Snazzy", "#1E1F29", "#EBECE6", "#E4E4E4", "#3B3C46",
       ["#000000", "#FC4346", "#50FB7C", "#F0FB8C", "#49BAFF", "#FC4CB4",
        "#8BE9FE", "#EDEDEC", "#555555", "#FC4346", "#50FB7C", "#F0FB8C",
        "#49BAFF", "#FC4CB4", "#8BE9FE", "#EDEDEC"]),
    _p("Ayu Dark", "#0A0E14", "#B3B1AD", "#E6B450", "#1A211C",
       ["#0A0E14", "#FF3333", "#C2D94C", "#FF8F40", "#59C2FF", "#FFEE99",
        "#95E6CB", "#B3B1AD", "#4D5566", "#FF3333", "#C2D94C", "#FF8F40",
        "#59C2FF", "#FFEE99", "#95E6CB", "#B3B1AD"]),
    _p("One Dark", "#1E2127", "#5C6370", "#5C6370", "#31353F",
       ["#000000", "#E06C75", "#98C379", "#D19A66", "#61AFEF", "#C678DD",
        "#56B6C2", "#ABB2BF", "#5C6370", "#E06C75", "#98C379", "#D19A66",
        "#61AFEF", "#C678DD", "#56B6C2", "#FFFEFE"]),
]


def preset_names() -> list[str]:
    return [p["name"] for p in PRESETS]


def get_preset(name: str) -> dict | None:
    for p in PRESETS:
        if p["name"].lower() == str(name).strip().lower():
            return normalize(p)
    return None


FORMATS = ("json", "iterm2", "windows", "guake", "gnome", "kitty",
           "alacritty")


def export(theme: dict, fmt: str, dest: str) -> str:
    t = normalize(theme)
    dest_path = Path(dest)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "iterm2":
        dest_path = dest_path.with_suffix(".itermcolors")
        dest_path.write_bytes(to_iterm2(t))
    elif fmt == "json":
        dest_path.write_text(to_json(t), encoding="utf-8")
    elif fmt == "windows":
        dest_path = dest_path.with_suffix(".json")
        dest_path.write_text(to_windows_terminal(t), encoding="utf-8")
    elif fmt == "guake":
        dest_path = dest_path.with_suffix(".txt")
        dest_path.write_text(to_guake(t) + "\n", encoding="utf-8")
    elif fmt == "gnome":
        dest_path = dest_path.with_suffix(".sh")
        dest_path.write_text(to_gnome(t), encoding="utf-8")
    elif fmt == "kitty":
        dest_path = dest_path.with_suffix(".conf")
        dest_path.write_text(to_kitty(t), encoding="utf-8")
    elif fmt == "alacritty":
        dest_path = dest_path.with_suffix(".toml")
        dest_path.write_text(to_alacritty(t), encoding="utf-8")
    else:
        raise ValueError("unknown terminal export format: %s" % fmt)
    return str(dest_path)


# --------------------------------------------------------------------- snippet

def preview_html(theme: dict, include_exports: bool = True) -> str:
    """A terminal-window mock that renders the theme — used both as the
    colors-pane WebEngine preview and as the saved snippet body."""
    t = normalize(theme)
    esc = json.dumps(to_json(t)).replace("-->", "--\\>")
    sample = [
        ("$", "fg"), (" ./deploy.sh --prod", "green"),
        ("  → building", "yellow"), ("  ✓ tests 128/128", "green"),
        ("  ✗ lint: 2 warnings", "brightRed"),
        ("$ git push origin main", "fg"),
        ("  → deployed in 3.2s", "cyan"),
        ("$ ", "magenta"),
    ]
    rows = "\n".join(
        "<div class='ln'><span class='c-%s'>%s</span></div>"
        % (cls, txt.replace("&", "&amp;").replace("<", "&lt;"))
        for txt, cls in sample)
    prompt_parts = "\n".join(
        "  .c-%s { color: %s; }" % (slot, col)
        for slot, col in list(t["normal"].items())
        + list(t["bright"].items()))
    exports = ("<p class='exports'>formats: JSON · iTerm2 · Windows"
               " Terminal · Guake · GNOME · kitty · alacritty</p>"
               if include_exports else "")
    return ("<!DOCTYPE html>\n<!-- fengrid terminal theme: %s\n%s\n-->\n"
            "<html><head><meta charset='utf-8'><style>\n"
            "body { margin: 0; background: %s; }\n"
            ".term { background: %s; color: %s; font-family: monospace;\n"
            "  font-size: 13px; line-height: 1.5; padding: 18px 20px;"
            " min-height: 200px; border-radius: 10px; }\n"
            ".bar { height: 22px; background: %s; border-radius: 10px"
            " 10px 0 0; display: flex; gap: 6px; align-items: center;"
            " padding: 0 12px; }\n"
            ".dot { width: 10px; height: 10px; border-radius: 99px; }"
            "%s\n.ln { white-space: pre; }\n"
            ".exports { color: %s; font: 11px monospace; margin-top: 10px; }\n"
            "</style></head><body>\n"
            "<div class='bar'><span class='dot' style='background:%s'></span>"
            "<span class='dot' style='background:%s'></span>"
            "<span class='dot' style='background:%s'></span></div>\n"
            "<div class='term'>\n%s\n</div>\n%s</body></html>\n"
            % (t["name"], esc, t["bg"], t["bg"], t["fg"], t["selection"],
               prompt_parts, t["fg"],
               t["bright"]["brightRed"], t["bright"]["brightYellow"],
               t["normal"]["green"], rows, exports))


def snippet_kwargs(theme: dict) -> dict:
    """Everything create_snippet() needs — a live preview of the theme with
    the JSON export embedded as a comment."""
    t = normalize(theme)
    return {
        "title": "Terminal theme — %s" % t["name"],
        "description": "Terminal color scheme (%s). Exports: iTerm2, "
                       "Windows Terminal, Guake, GNOME Terminal, kitty, "
                       "alacritty — JSON embedded in the HTML comment."
                       % t["name"],
        "language": "web",
        "html": preview_html(t, include_exports=True),
        "css": "",
        "js": "",
        "tags": "terminal, theme, colors",
    }


def save_as_snippet(con, theme: dict) -> int:
    return core_snippets.create_snippet(con, **snippet_kwargs(theme))
