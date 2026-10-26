"""QML duplicate-property guard (#76).

The merge of #56's and #47's edits to SettingsScreen.qml concatenated
two assignments to the same property (`spacing: 3` / `spacing: 1`) on
adjacent lines — a syntax-level error that made the whole component
fail to load and the app refuse to launch, while each branch alone had
passed QA. This guard parses every tracked .qml file for ADJACENT
duplicate property assignments so the class dies at PR time.

Note: only ADJACENT assignments are flagged (a comment or brace between
them breaks the sequence, and QML objects can't share adjacent lines),
so this is a cheap merge-collision tripwire, not a full QML linter.
"""

import subprocess
from pathlib import Path

QML_DIR = Path(__file__).resolve().parents[1] / "qml"


def _tracked_qml_files():
    out = subprocess.run(
        ["git", "ls-files", "qml/*.qml", "qml/components/*.qml"],
        cwd=QML_DIR.parent, capture_output=True, text=True, check=True)
    return [QML_DIR.parent / line for line in out.stdout.splitlines()]


def test_no_adjacent_duplicate_property_assignments():
    offenders = []
    for path in _tracked_qml_files():
        prev = None
        for lineno, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if (":" in stripped and not stripped.startswith("//")
                    and stripped.split(":")[0].strip().isidentifier()):
                key = stripped.split(":")[0].strip()
                if key == prev:
                    offenders.append(f"{path.name}:{lineno}: {key}")
                prev = key
                continue
            prev = None
    assert not offenders, \
        "adjacent duplicate property assignments (merge collision, #76): " \
        + ", ".join(offenders)