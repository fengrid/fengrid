"""License recognition + short summary for inspector LICENSE tabs.

Pure stdlib: recognizes the common standard open-source licenses by
SPDX identifier or signature phrases and returns a structured summary
(name, permissions / conditions / limitations) suitable for the
Properties panel's License tab. Anything else is reported as
non-standard — the UI then just links the file.

Detection order (first hit wins):
  1. an ``SPDX-License-Identifier: <id>`` line anywhere in the text
  2. signature phrases in the first 4 KB (case-insensitive)

The recognition data is hand-curated (no network, no license DB) —
these are the licenses the bundled ecosystem actually ships.  Usage:

    from . import licenses as core_licenses
    summary = core_licenses.recognize(text)   # dict | None
"""

from __future__ import annotations

import re

# signature → canonical SPDX id for the licenses we summarize
_SIGNATURES: tuple[tuple[str, str], ...] = (
    ("permission is hereby granted, free of charge, to any person obtaining a copy",
     "MIT"),
    ("isp license", "ISC"),
    ("permission to use, copy, modify, and/or distribute this software",
     "ISC"),
    ("redistribution and use in source and binary forms, with or without modification",
     "BSD"),
    ("apache license, version 2.0", "Apache-2.0"),
    ("mozilla public license version 2.0", "MPL-2.0"),
    ("gnu general public license version 3", "GPL-3.0-only"),
    ("gnu general public license version 2", "GPL-2.0-only"),
    ("gnu affero general public license version 3", "AGPL-3.0-only"),
    ("gnu library general public license version 2.1", "LGPL-2.1-only"),
    ("gnu lesser general public license version 3", "LGPL-3.0-only"),
    ("this is free and unencumbered software released into the public domain",
     "Unlicense"),
    ("creative commons zero", "CC0-1.0"),
)

# per-SPDX summary rows — the TL;DR-style bullets the License tab shows
_LICENSES: dict[str, dict] = {
    "MIT": {
        "name": "MIT License", "url": "https://spdx.org/licenses/MIT.html",
        "permissions": ["commercial use", "modify", "distribute", "private use"],
        "conditions": ["keep the license + copyright notice"],
        "limitations": ["no liability", "no warranty"],
    },
    "ISC": {
        "name": "ISC License", "url": "https://spdx.org/licenses/ISC.html",
        "permissions": ["commercial use", "modify", "distribute", "private use"],
        "conditions": ["keep the license + copyright notice"],
        "limitations": ["no liability", "no warranty"],
    },
    "BSD-2-Clause": {
        "name": "BSD 2-Clause (Simplified)", "url": "https://spdx.org/licenses/BSD-2-Clause.html",
        "permissions": ["commercial use", "modify", "distribute", "private use"],
        "conditions": ["keep the license + copyright notice"],
        "limitations": ["no liability", "no warranty"],
    },
    "BSD-3-Clause": {
        "name": "BSD 3-Clause (New)", "url": "https://spdx.org/licenses/BSD-3-Clause.html",
        "permissions": ["commercial use", "modify", "distribute", "private use"],
        "conditions": ["keep the license + copyright notice",
                       "no endorsement without written consent"],
        "limitations": ["no liability", "no warranty"],
    },
    "Apache-2.0": {
        "name": "Apache License 2.0", "url": "https://spdx.org/licenses/Apache-2.0.html",
        "permissions": ["commercial use", "modify", "distribute", "patent grant"],
        "conditions": ["keep the license + copyright notice", "state changes made"],
        "limitations": ["no liability", "no warranty", "trademark use"],
    },
    "MPL-2.0": {
        "name": "Mozilla Public License 2.0", "url": "https://spdx.org/licenses/MPL-2.0.html",
        "permissions": ["commercial use", "modify", "distribute", "patent grant"],
        "conditions": ["keep the license + copyright notice",
                       "disclose source of modified files", "state changes made"],
        "limitations": ["no liability", "no warranty", "trademark use"],
    },
    "GPL-2.0-only": {
        "name": "GNU GPL v2", "url": "https://spdx.org/licenses/GPL-2.0-only.html",
        "permissions": ["commercial use", "modify", "distribute"],
        "conditions": ["disclose source", "license + copyright notice",
                       "same license (copyleft)"],
        "limitations": ["no liability", "no warranty"],
    },
    "GPL-3.0-only": {
        "name": "GNU GPL v3", "url": "https://spdx.org/licenses/GPL-3.0-only.html",
        "permissions": ["commercial use", "modify", "distribute", "patent grant"],
        "conditions": ["disclose source", "license + copyright notice",
                       "same license (copyleft)"],
        "limitations": ["no liability", "no warranty"],
    },
    "AGPL-3.0-only": {
        "name": "GNU AGPL v3", "url": "https://spdx.org/licenses/AGPL-3.0-only.html",
        "permissions": ["commercial use", "modify", "distribute", "patent grant"],
        "conditions": ["disclose source (incl. network use)",
                       "license + copyright notice", "same license (copyleft)"],
        "limitations": ["no liability", "no warranty"],
    },
    "LGPL-2.1-only": {
        "name": "GNU LGPL v2.1", "url": "https://spdx.org/licenses/LGPL-2.1-only.html",
        "permissions": ["commercial use", "modify", "distribute",
                        "link from non-GPL works"],
        "conditions": ["disclose source of the library", "license + copyright notice",
                       "same license (copyleft)"],
        "limitations": ["no liability", "no warranty"],
    },
    "LGPL-3.0-only": {
        "name": "GNU LGPL v3", "url": "https://spdx.org/licenses/LGPL-3.0-only.html",
        "permissions": ["commercial use", "modify", "distribute",
                        "link from non-GPL works"],
        "conditions": ["disclose source of the library", "license + copyright notice",
                       "same license (copyleft)"],
        "limitations": ["no liability", "no warranty"],
    },
    "Unlicense": {
        "name": "The Unlicense", "url": "https://spdx.org/licenses/Unlicense.html",
        "permissions": ["commercial use", "modify", "distribute", "private use"],
        "conditions": [],
        "limitations": ["no liability", "no warranty"],
    },
    "CC0-1.0": {
        "name": "Creative Commons Zero (public domain)",
        "url": "https://spdx.org/licenses/CC0-1.0.html",
        "permissions": ["commercial use", "modify", "distribute", "private use"],
        "conditions": [],
        "limitations": ["no liability", "no warranty"],
    },
}

# SPDX ids with variant suffixes collapse to their base for summaries
_BASE_IDS = {"GPL-2.0": "GPL-2.0-only", "GPL-3.0": "GPL-3.0-only",
             "LGPL-2.1": "LGPL-2.1-only", "LGPL-3.0": "LGPL-3.0-only",
             "AGPL-3.0": "AGPL-3.0-only", "BSD-2": "BSD-2-Clause",
             "BSD-3": "BSD-3-Clause"}

_SPDX_RE = re.compile(r"SPDX-License-Identifier:\s*([A-Za-z0-9.+\-]+)")


def _base_spdx(spdx: str) -> str:
    if spdx in _BASE_IDS:
        return _BASE_IDS[spdx]
    for known in _LICENSES:
        if spdx.startswith(known + "-or-later") or spdx.startswith(known + "-only"):
            return known
    return spdx


def recognize(text: str) -> dict | None:
    """Summary dict for a standard open-source license, else None.

    Shape: {name, spdx, url, permissions[], conditions[], limitations[]}
    — the License tab renders the bullets; None means "not standard".
    """
    body = (text or "")[:4096]
    low = body.lower()

    # 1) explicit SPDX line — authoritative when present
    m = _SPDX_RE.search(body)
    if m:
        spdx = _base_spdx(m.group(1))
        row = _LICENSES.get(spdx)
        if row is not None:
            return _summary(spdx, row)

    # 2) signature phrases
    for sig, spdx in _SIGNATURES:
        if sig in low:
            row = _LICENSES[spdx]
            return _summary(spdx, row)
    return None


def _summary(spdx: str, row: dict) -> dict:
    return {"name": row["name"], "spdx": spdx, "url": row["url"],
            "permissions": list(row["permissions"]),
            "conditions": list(row["conditions"]),
            "limitations": list(row["limitations"])}


LICENSE_NAMES = ("LICENSE.md", "LICENSE.MD", "license.md", "LICENSE.txt",
                 "LICENSE", "COPYING", "COPYING.txt")
