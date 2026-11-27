"""Scan-time log-noise gate (issue #63).

Third-party identification libraries flood the terminal per file during
large scans: fontTools logs a head-table timestamp warning per font and a
missing-brotli ERROR per WOFF2 file, and PIL warns per palette PNG. The
gate lets each DISTINCT message through once, counts the repeats, and
prints one summary line per class when the scan ends — real signals stay
visible, the flood is gone.

Two channels are gated:
- ``logging`` records at or above WARNING that reach ``logging.lastResort``
  (the handler every unconfigured record ends up at; fontTools logs through
  child loggers, so a root-logger filter would never see them). The dedupe
  key normalizes digit runs so per-file values (timestamps, sizes) do not
  defeat it.
- ``warnings.showwarning`` (PIL's palette-transparency UserWarning and
  friends). Python's own "default" action already shows a same-location
  warning once per process; the counting replacement is belt-and-braces
  for paths that raise the filter (and gives the summary a count).

The gate is refcounted, so overlapping scans (icon + font worker) install
and uninstall it safely; summaries print when the LAST scan leaves.
"""

from __future__ import annotations

import logging
import re
import sys
import threading
import warnings
from typing import Literal, Self

_lock = threading.Lock()
_depth = 0
_handler_filter: _DedupeFilter | None = None
_saved_showwarning = None
_log_counts: dict[tuple[str, str], list] = {}   # (logger, normalized) -> [n, first]
_warn_counts: dict[tuple[str, str], list] = {}  # (category, normalized) -> [n, first]

_DIGITS = re.compile(r"\d+")


def _normalize(msg: str) -> str:
    return _DIGITS.sub("#", msg)


class _DedupeFilter(logging.Filter):
    # issue #138: fontTools' head-table notes ('created' timestamp seems
    # very low / out of range) are auto-corrections for font files with
    # bogus epoch fields — fontTools fixes the value and carries on.
    # Nothing for the user to act on, dozens per large library, so they
    # are dropped outright rather than shown once.
    _DROP = re.compile(
        r"'(?:created|modified)' timestamp"
        r" (?:seems very low|out of range)")

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if self._DROP.search(msg):
            return False
        key = (record.name, _normalize(msg))
        with _lock:
            entry = _log_counts.get(key)
            if entry is None:
                _log_counts[key] = [1, msg]
                return True
            entry[0] += 1
            return False


def _showwarning(message, category, filename, lineno, file=None, line=None):
    text = str(message)
    key = (category.__name__, _normalize(text))
    with _lock:
        entry = _warn_counts.get(key)
        if entry is None:
            _warn_counts[key] = [1, text]
            first = True
        else:
            entry[0] += 1
            first = False
    if first and _saved_showwarning is not None:
        _saved_showwarning(message, category, filename, lineno, file, line)


def _summaries() -> list[str]:
    lines = []
    for (name, _norm), (n, first) in sorted(_log_counts.items()):
        if n > 1:
            lines.append(f"[{name}] {first} (+{n - 1} more suppressed)")
    for (cat, _norm), (n, first) in sorted(_warn_counts.items()):
        if n > 1:
            lines.append(f"{cat}: {first} (+{n - 1} more suppressed)")
    return lines


class scan_noise_gate:
    """Suppress per-file third-party log/warning floods during a scan.

    Each distinct message prints once; repeats are summarized as
    "(+N more suppressed)" on exit. Wrap core.indexer.scan()/scan_fonts()
    — the only two entry points that identify thousands of files.
    """

    def __enter__(self) -> Self:
        global _depth, _handler_filter, _saved_showwarning
        with _lock:
            _depth += 1
            if _depth == 1:
                _handler_filter = _DedupeFilter()
                if logging.lastResort is not None:
                    logging.lastResort.addFilter(_handler_filter)
                _saved_showwarning = warnings.showwarning
                warnings.showwarning = _showwarning
        return self

    def __exit__(self, *exc) -> Literal[False]:
        global _depth, _handler_filter, _saved_showwarning
        with _lock:
            _depth -= 1
            if _depth == 0:
                if _handler_filter is not None:
                    if logging.lastResort is not None:
                        logging.lastResort.removeFilter(_handler_filter)
                    _handler_filter = None
                warnings.showwarning = _saved_showwarning
                _saved_showwarning = None
                for line in _summaries():
                    print(f"fengrid: {line}", file=sys.stderr)
                _log_counts.clear()
                _warn_counts.clear()
        return False