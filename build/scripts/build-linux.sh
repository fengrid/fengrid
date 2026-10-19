#!/usr/bin/env bash
#
# build-linux.sh — build Fengrid (Qt 6) for linux-x64 | linux-arm64.
#
# Usage:
#   build-linux.sh <linux-x64|linux-arm64>
#   FENGRID_VARIANT=prod|dev   (default: prod; dev adds pytest/ruff to the env)
#   FENGRID_IN_CONTAINER=1     (set by docker/linux-*.Dockerfile: use the
#                               container's system python, skip the venv)
#
# VALIDATED (2026-10-19): linux-x64 prod run green end-to-end — PyInstaller
# onedir + tar.gz artifact; the frozen binary smoke-tested offscreen
# (--screenshot: zero QML/thread errors; fonts + QML resolve from _MEIPASS).
#
set -euo pipefail

TARGET="${1:?usage: build-linux.sh <linux-x64|linux-arm64>}"
VARIANT="${FENGRID_VARIANT:-prod}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
QT_DIR="$ROOT/qt"
OUT_DIR="$QT_DIR/dist"

case "$TARGET" in
    linux-x64|linux-arm64) ;;
    *) echo "unknown target: $TARGET (use linux-x64 or linux-arm64)" >&2; exit 1 ;;
esac
case "$VARIANT" in
    prod|dev) ;;
    *) echo "unknown variant: $VARIANT (use prod or dev)" >&2; exit 1 ;;
esac

cd "$QT_DIR"

if [ "${FENGRID_IN_CONTAINER:-0}" != "1" ]; then
    # native run: isolated venv so CI/local builds don't pollute the host env
    python3 -m venv .venv
    # shellcheck disable=SC1091
    . .venv/bin/activate
fi

python -m pip install --upgrade pip wheel
REQS="$ROOT/build/requirements-build.txt"
[ "$VARIANT" = "dev" ] && REQS="$ROOT/build/requirements-dev.txt"
python -m pip install -r "$REQS"

# fail fast if the platform wheel story is broken (mirrors the probe in
# build-windows.ps1 for windows-arm64)
python -c "import PySide6" 2>/dev/null || {
    echo "ERROR: PySide6 import failed — check wheel availability for this platform" >&2
    exit 1
}
python -c "import PySide6; print('PySide6', PySide6.__version__)"

pyinstaller --noconfirm --clean \
    --name fengrid \
    --add-data "$QT_DIR/qml:qml" \
    --add-data "$ROOT/fonts:fonts" \
    --add-data "$ROOT/branding/assets:branding/assets" \
    --paths "$QT_DIR/src" \
    "$QT_DIR/src/fengrid/__main__.py"

# optional AppImage packaging lands here once the skeleton is validated
# (linuxdeploy + the Qt runtime plugin; see docs/architecture/0001 §11).

tar -czf "$OUT_DIR/fengrid-${VARIANT}-${TARGET}.tar.gz" -C "$OUT_DIR" fengrid
echo "artifact: $OUT_DIR/fengrid-${VARIANT}-${TARGET}.tar.gz"
