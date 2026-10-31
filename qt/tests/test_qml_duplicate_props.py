"""QML duplicate-property guard (#76, upgraded after #131's merge).

The merge of #56's and #47's edits to SettingsScreen.qml concatenated
two assignments to the same property (`spacing: 3` / `spacing: 1`) on
adjacent lines — a syntax-level error that made the whole component
fail to load and the app refuse to launch, while each branch alone had
passed QA. The #76 guard only caught ADJACENT duplicates; the #119
merge (279b321) then shipped a collision the guard could not see:
two `text:` bindings on the same element separated by comments and a
multi-line binding — QML rejects a repeated property within the same
object REGARDLESS of what sits between the assignments (comments,
continuation lines, blank lines all count). The app again refused to
launch after the user's local merge.

This version scans per OBJECT (brace-depth scopes, with string
literals and // comments stripped first) and flags any property
assigned twice inside the same object, so the whole class dies at PR
time instead of only the adjacent-line special case.

Not a full QML parser — a cheap structural tripwire. String contents
are elided before brace counting, so braces inside literals don't
skew scope depth; JS object literals inside bindings open a transient
scope that closes with its own brace, leaving outer scopes intact.
"""

import re
import subprocess
from pathlib import Path

QML_DIR = Path(__file__).resolve().parents[1] / "qml"

_ASSIGN_RE = re.compile(
    r"^(?:property\s+(?:alias\s+|var\s+|bool\s+|int\s+|real\s+|string\s+|"
    r"color\s+|date\s+|list\s+)?|[A-Za-z_][\w.]*|on[A-Z]\w*)\s*:")


def _strip_noise(line: str) -> str:
    """Remove string-literal contents and // comments; keep braces."""
    line = re.sub(r'"[^"\n]*"', '""', line)
    line = re.sub(r"'[^'\n]*'", "''", line)
    return re.sub(r"//.*", "", line)


def _duplicate_keys(path: Path):
    """(key, lineno) pairs assigned twice within one QML object."""
    dupes = []
    scopes = [{}]
    for lineno, raw in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1):
        line = _strip_noise(raw).strip()
        if not line:
            continue
        # record an assignment in the CURRENT scope before any brace opens
        m = _ASSIGN_RE.match(line)
        if m:
            key = re.split(r"\s*:", line, maxsplit=1)[0].strip()
            if key in scopes[-1]:
                dupes.append((path.name, lineno, key,
                              scopes[-1][key]))
            scopes[-1][key] = lineno
        # brace tracking: push a scope per '{', pop per '}'
        opens = line.count("{")
        closes = line.count("}")
        for _ in range(opens):
            scopes.append({})
        for _ in range(closes):
            if len(scopes) > 1:
                scopes.pop()
    return dupes


def _tracked_qml_files():
    out = subprocess.run(
        ["git", "ls-files", "qml/*.qml", "qml/components/*.qml"],
        cwd=QML_DIR.parent, capture_output=True, text=True, check=True)
    return [QML_DIR.parent / line for line in out.stdout.splitlines()]


def test_no_duplicate_property_assignments_within_an_object():
    offenders = []
    for path in _tracked_qml_files():
        offenders.extend(_duplicate_keys(path))
    assert not offenders, \
        "duplicate property assignments within one QML object " \
        "(merge collision — QML rejects repeats regardless of what " \
        "sits between the lines; #76 / #131): " \
        + ", ".join(f"{f}:{n} {k!r} (first at {n0})" for f, n, k, n0
                    in offenders)
