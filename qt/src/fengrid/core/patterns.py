"""Automated renaming engine for imports (and export batch ops).
Pure functions — no Qt, no DB — so every rule is unit-testable.

Composition order (documented + tested):
  1. regex find/replace on the ORIGINAL stem (re.sub, user pattern)
  2. template expansion ({name} {ext} {n} {guid} {csv} {rand})
  3. prefix / suffix wrapping around the result
  4. enumeration {n} is zero-padded from `enum_start + enum_index`
  5. sanitise for the filesystem, keep exactly one extension at the end

Templates without explicit {n}/{guid}/{rand} still get the configured
style appended when style != "none" (so "prefix + 001" needs no braces).
"""
from __future__ import annotations

import re
import uuid
from pathlib import PurePath

_FS_BAD = re.compile(r"[^\w.\- ]+", re.UNICODE)
_MULTI_DOT = re.compile(r"\.{2,}")


_NESTED_QUANT = re.compile(
    r"\([^()]*[+*}]\s*[^()]*\)\s*[+*{]")  # (…+…)  +  → nested quantifier

# SEC-7 second layer: the textual detector above is necessarily
# incomplete — patterns like `(a|a)*b` (overlapping alternation, no
# nested quantifier) backtrack exponentially while looking harmless.
# Enforcement uses the `regex` module whose C-level `timeout=` REALLY
# aborts a runaway match. The stdlib `re` engine cannot be preempted:
# a whole sub() call is a single C invocation that holds the GIL until
# it finishes, so a watchdog thread would only time out after the
# damage is done — that path is NOT attempted.
try:                                              # pragma: no cover - env
    import regex as _regex_mod
except ImportError:                               # optional at runtime
    _regex_mod = None

_PATTERN_PROBE_S = 0.25


def _sub_direct(find: str, repl: str, stem: str) -> str:
    return re.sub(find, repl, stem)


def _sub_guarded(find: str, repl: str, stem: str) -> str | None:
    """Run one substitution under the time budget.

    Returns the result string, or None when the pattern exceeded the
    budget (or is invalid — callers treat None as "keep the stem").
    Requires the `regex` module; without it only the textual detector
    guards (callers fall back to `re`, which is what pre-SEC-7 did).
    """
    if _regex_mod is None:
        try:
            return _sub_direct(find, repl, stem)
        except re.error:
            return None
    try:
        # regex raises builtin TimeoutError on expiry and regex.error
        # on invalid patterns — either way the stem survives unchanged
        return _regex_mod.sub(find, repl, stem,
                              timeout=_PATTERN_PROBE_S)
    except Exception:                             # noqa: BLE001
        return None


def apply_regex(stem: str, find: str, repl: str) -> str:
    """User find/replace. An invalid pattern must not kill a 10k-file
    import — fall back to the unchanged stem. SEC-7: a pathological
    pattern (nested quantifiers like `(a+)+`, or detector-evading
    overlap like `(a|a)*b`) can backtrack catastrophically on every
    filename; such patterns are rejected up front, and every execution
    runs under the regex module's hard C-level timeout."""
    if not find:
        return stem
    if len(find) > 512 or _NESTED_QUANT.search(find):
        return stem
    result = _sub_guarded(find, repl if repl is not None else "", stem)
    return stem if result is None else result


def _pad(n: int, width: int) -> str:
    return str(n).rjust(width, "0") if width > 0 else str(n)


def build_name(original: str, *,
               template: str = "",
               prefix: str = "",
               suffix: str = "",
               find: str = "",
               repl: str = "",
               style: str = "none",          # none | enum | random | guid
               enum_index: int = 0,
               enum_start: int = 1,
               enum_pad: int = 2,
               random_len: int = 6,
               csv_name: str = "",
               rng=None) -> str:
    """Return the new FILE NAME (stem + original extension preserved).

    style adds a token when the template doesn't contain one:
      enum   -> {n}     cardinal enumeration (start + index, padded)
      random -> {rand}  random alphanumeric of random_len chars
      guid   -> {guid}  uuid4 hex
    csv_name feeds {csv} (supplied CSV data, one name per imported file).
    """
    original = str(original or "")
    p = PurePath(original)
    ext = p.suffix.lstrip(".")              # no dot
    stem = p.stem if p.stem else "asset"
    stem = apply_regex(stem, find, repl)

    n = enum_start + enum_index
    rand_src = rng if rng is not None else _Random()
    rand_tok = _alnum(rand_src, random_len)
    guid_tok = uuid.uuid4().hex

    tpl = template.strip() if template else ""
    if tpl:
        out = tpl
        out = out.replace("{name}", stem)
        out = out.replace("{ext}", ext)
        out = out.replace("{n}", _pad(n, enum_pad))
        out = out.replace("{guid}", guid_tok)
        out = out.replace("{rand}", rand_tok)
        out = out.replace("{csv}", csv_name or stem)
    else:
        out = stem

    # style tokens the template didn't already carry
    if style == "enum" and "{n}" not in (tpl or ""):
        out = f"{out}{_pad(n, enum_pad)}"
    elif style == "random" and "{rand}" not in (tpl or ""):
        out = f"{out}{rand_tok}"
    elif style == "guid" and "{guid}" not in (tpl or ""):
        out = f"{out}-{guid_tok}"

    out = f"{prefix}{out}{suffix}" if (prefix or suffix) else out
    out = sanitize(out)
    if not out:
        out = "asset"
    if ext:
        out = f"{out}.{ext}"
    return out


def sanitize(name: str) -> str:
    """Filesystem-safe: strip separators/control chars, collapse dots,
    trim — never returns empty, never escapes a directory."""
    name = name.replace("/", "_").replace("\\", "_").replace("\x00", "")
    name = _FS_BAD.sub("_", name)
    name = _MULTI_DOT.sub(".", name)
    return name.strip(" .")[:120].strip(" .")


def uniquify(dest_dir, name: str) -> str:
    """`name` (with ext) without colliding with existing files — appends
    -2, -3, … before the extension."""
    from pathlib import Path
    dest = Path(dest_dir)
    if not (dest / name).exists():
        return name
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    i = 2
    while True:
        cand = f"{stem}-{i}{dot + ext if dot else ''}"
        if not (dest / cand).exists():
            return cand
        i += 1


def read_csv_names(path: str, column: str = "0",
                   has_header: bool = True) -> list[str]:
    """Supplied CSV data: column = header name, or 0-based index when
    numeric. With a numeric column the FIRST row is treated as the
    header by default (has_header=False to read it as data); a named
    column always locates its header row first. One name per row,
    consumed in import order (row 1 → file 1)."""
    import csv as _csv
    names: list[str] = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rows = _csv.reader(fh)
        first = next(rows, None)
        if first is None:
            return []
        if column and not column.isdigit():
            header = [h.strip().lower() for h in first]
            try:
                col = header.index(column.strip().lower())
            except ValueError:
                col = 0
            first = None               # header row consumed either way
        else:
            col = int(column or 0)
            if has_header:
                first = None           # header consumed
        if first is not None:
            names.append(_cell(first, col))
        for row in rows:
            names.append(_cell(row, col))
    return [n.strip() for n in names if n.strip()]


def _cell(row: list[str], col: int) -> str:
    return row[col] if 0 <= col < len(row) else ""


class _Random:
    """Lazy random source (kept injectable for deterministic tests)."""
    def __init__(self):
        self._impl = None

    def choice(self, seq):
        if self._impl is None:
            import random
            self._impl = random.SystemRandom()
        return self._impl.choice(seq)


_ALNUM = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _alnum(src, n: int) -> str:
    n = max(0, int(n))
    return "".join(src.choice(_ALNUM) for _ in range(n))
