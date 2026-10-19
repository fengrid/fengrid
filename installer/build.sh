#!/usr/bin/env bash
# build.sh — build the Windows installer binary with NSIS.
#
# Works on Linux, macOS, WSL and Windows (wherever makensis exists).
# Reads the app version from index.html (APP_VERSION) and passes it into
# the installer script. Output: dist/fengrid-win64-setup.exe
#
# Installing makensis:
#   Debian/Ubuntu:  sudo apt-get install nsis
#   Windows:        choco install nsis   (or the nsis.sf.net installer)
#   macOS:          brew install makensis
set -euo pipefail
cd "$(dirname "$0")/.."   # repo root

VER=$(sed -n "s/.*APP_VERSION = '\([^']*\)'.*/\1/p" index.html | head -1)
[ -n "$VER" ] || { echo "error: could not read APP_VERSION from index.html" >&2; exit 1; }
command -v makensis >/dev/null 2>&1 || {
    echo "error: makensis not found — install NSIS (see installer/README.md)" >&2; exit 1;
}

mkdir -p dist
rm -f dist/fengrid-win64-setup.exe
makensis -DAPPVER="$VER" installer/fengrid.nsi
echo
echo "Built dist/fengrid-win64-setup.exe (${VER})"
