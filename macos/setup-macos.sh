#!/usr/bin/env bash
#
# setup-macos.sh — one-time bootstrap for a native macOS build runner.
#
# macOS builds run natively (no Docker — see docker/README.md). This script
# prepares the runner: Homebrew Python (if missing) and a tooling check.
# Run once per runner, by hand.
#
set -euo pipefail

if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 not found — installing python@3.12 via Homebrew"
    command -v brew >/dev/null 2>&1 || {
        echo "ERROR: Homebrew not found either — install python3 manually" >&2
        exit 1
    }
    brew install python@3.12
fi

python3 --version
echo "checking auxiliary tooling (non-fatal warnings only):"
command -v git >/dev/null 2>&1   || echo "  WARNING: git missing" >&2
command -v codesign >/dev/null 2>&1 || echo "  note: codesign missing — only needed for signed builds"
echo "done. per-build python deps install into the venv created by build-macos.sh"
