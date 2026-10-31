#!/usr/bin/env python3
"""Generate the icon path dictionary in qt/qml/components/Icons.qml
from the vendored Qlementine SVGs.

This is Fengrid's equivalent of Qlementine's own `update.py` process:
the SVG files under qt/resources/icons/qlementine/16/ are the source
of truth; this script reads them and rewrites the generated block in
Icons.qml between the GENERATED markers.

To add an icon:
  1. copy the upstream SVG into qt/resources/icons/qlementine/16/<category>/
  2. add a mapping entry below (fengrid name -> qlementine category/name)
  3. run: python3 qt/scripts/generate-icons-qml.py

Source: https://github.com/oclero/qlementine-icons (MIT).
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ICONS_DIR = REPO / "qt" / "resources" / "icons" / "qlementine" / "16"
ICONS_QML = REPO / "qt" / "qml" / "components" / "Icons.qml"

# fengrid icon name -> qlementine 16px path (category/name, no extension)
MAPPING = {
    "check": "shape/check-tick",
    "chevron-down": "navigation/chevron-down",
    "chevron-left": "navigation/chevron-left",
    "chevron-right": "navigation/chevron-right",
    "chevron-up": "navigation/chevron-up",
    "code": "software/code-markup",
    "copy": "action/copy",
    "download": "action/download",
    "droplet": "misc/paint-drop",
    "external-link": "action/external-link",
    "file-text": "file/file-text",
    "folder-plus": "action/add-folder",
    "git-branch": "software/version-control",
    "grid": "misc/grid",
    "hard-drive": "hardware/hdd",
    "help": "misc/help",
    "image": "file/picture",
    "layers": "navigation/layers-2",
    "lock": "action/lock",
    "menu": "navigation/menu-burger",
    "moon": "misc/moon",
    "package": "shape/cube",
    "play": "media/play",
    "plus": "action/plus",
    "refresh": "action/refresh",
    "search": "navigation/search",
    "star": "shape/star",
    "sun": "misc/sun",
    "tag": "misc/tag",
    "trash": "action/trash",
    "type": "file/font",
    "unlock": "action/unlock",
    "upload": "action/import",
    "x": "action/close",
    "zap": "misc/light-bulb-on",
}

BEGIN = "    // BEGIN-GEN"
END = "    // END-GEN"

# per-element fill='#000' is stripped so the root fill (the tint) governs;
# rendering rules (fill-rule/clip-rule) pass through untouched.
_FILL_RE = re.compile(r"\s*fill=['\"]#[0-9a-fA-F]{3,8}['\"]")


def load_body(rel: str) -> str:
    """Inner elements of an upstream SVG, fills stripped."""
    svg = (ICONS_DIR / f"{rel}.svg").read_text(encoding="utf-8")
    m = re.match(r"<svg[^>]*>(.*)</svg>\s*$", svg, re.S)
    if not m:
        raise ValueError(f"unparseable SVG: {rel}")
    body = m.group(1).strip()
    body = _FILL_RE.sub("", body)
    # single-quote the attributes for the QML string literal
    return body.replace('"', "'")


def main() -> None:
    entries = []
    for name in sorted(MAPPING):
        rel = MAPPING[name]
        body = load_body(rel)
        entries.append(f'        "{name}": "{body}",')
    block = (BEGIN + "\n"
             + "    readonly property var _paths: ({\n"
             + "\n".join(entries) + "\n"
             + "    })\n" + END)

    src = ICONS_QML.read_text(encoding="utf-8")
    if BEGIN not in src:
        raise SystemExit("Icons.qml has no generated markers — refusing")
    new = re.sub(
        re.escape(BEGIN) + r".*?" + re.escape(END),
        lambda _: block,  # lambda avoids backslash interpretation
        src,
        count=1,
        flags=re.S,
    )
    ICONS_QML.write_text(new, encoding="utf-8")
    print(f"generated {len(entries)} icon entries into {ICONS_QML.name}")


if __name__ == "__main__":
    main()
