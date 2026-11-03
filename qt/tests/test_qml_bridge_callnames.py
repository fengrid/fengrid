"""Recurrence guard for QML → bridge call-name mismatches (#138).

PySide6 exposes @Slot methods under their PYTHON name — there is no
automatic camelCase alias (PyQt's old dual-name behavior does not
apply). Main.qml called ``fonts.checkedFamilyIds(...)`` while the
Fonts bridge defines ``checked_family_ids`` — a TypeError on every
binding evaluation, flooding the terminal.

This test fails whenever any QML file calls ``.camelCase(...)`` on a
name that exists ONLY as a snake_case def in the bridges and is
neither (a) also defined camelCase in Python nor (b) a QML-local
``function``. It is intentionally conservative: anything ambiguous
passes, so only the proven-dead shape ever bites.
"""
import os
import re
import sys
from pathlib import Path

QT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(QT / "src"))


def _py_defs() -> tuple[set[str], set[str]]:
    snake: set[str] = set()
    camel: set[str] = set()
    for py in (QT / "src").rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        for m in re.finditer(r"^\s*def ([A-Za-z_][A-Za-z0-9_]*)\(",
                             py.read_text(encoding="utf-8", errors="replace"),
                             re.M):
            name = m.group(1)
            if "_" in name:
                snake.add(name)
            else:
                camel.add(name)
    return snake, camel


def _camel(name: str) -> str:
    parts = name.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def test_qml_never_calls_camelcase_names_that_only_exist_snake():
    snake, camel_py = _py_defs()
    qml_texts = {}
    for qml in (QT / "qml").rglob("*.qml"):
        qml_texts[str(qml)] = qml.read_text(encoding="utf-8",
                                            errors="replace")
    qml_functions: set[str] = set()
    for txt in qml_texts.values():
        qml_functions.update(re.findall(r"\bfunction ([A-Za-z0-9_]+)\(", txt))
        # JS object literals / delegates can carry method-shaped members
        qml_functions.update(re.findall(r"^\s*([A-Za-z0-9_]+):\s*function\(",
                                         txt, re.M))

    offenders = []
    for name in sorted(snake):
        c = _camel(name)
        if c in camel_py or c in qml_functions:
            continue
        for path, txt in qml_texts.items():
            if re.search(r"\." + c + r"\(", txt):
                offenders.append(f"{c}  (Python: {name})  ->  {path}")
    assert offenders == [], (
        "QML calls camelCase names that exist only as snake_case "
        "bridge defs (PySide6 has no camelCase alias — calls throw "
        "'... is not a function'):\n" + "\n".join(offenders))
