#!/usr/bin/env bash
#
# build-macos.sh — build Fengrid (Qt 6) for macos-x64 | macos-arm64.
#
# Runs NATIVELY on a macOS runner. macOS cannot be built inside Docker:
# Apple's EULA prohibits macOS system images on non-Apple hardware and no
# macOS base images exist (see docker/macos-*.Dockerfile stubs and
# docker/README.md).
#
# Usage:
#   build-macos.sh <macos-x64|macos-arm64>
#   FENGRID_VARIANT=prod|dev   (default: prod)
#   MAC_CODESIGN_ID            (optional: codesign the bundle when set;
#                               notarization is a manual/post step — see
#                               macos/README.md)
#
# DRAFT (2026-10-18): not yet executed.
set -euo pipefail

TARGET="${1:?usage: build-macos.sh <macos-x64|macos-arm64>}"
VARIANT="${FENGRID_VARIANT:-prod}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
QT_DIR="$ROOT/qt"
OUT_DIR="$QT_DIR/dist"

case "$TARGET" in
    macos-x64|macos-arm64) ;;
    *) echo "unknown target: $TARGET (use macos-x64 or macos-arm64)" >&2; exit 1 ;;
esac
case "$VARIANT" in
    prod|dev) ;;
    *) echo "unknown variant: $VARIANT (use prod or dev)" >&2; exit 1 ;;
esac

cd "$QT_DIR"

if [ "${FENGRID_IN_CONTAINER:-0}" != "1" ]; then
    python3 -m venv .venv
    # shellcheck disable=SC1091
    . .venv/bin/activate
fi

python -m pip install --upgrade pip wheel
REQS="$ROOT/build/requirements-build.txt"
[ "$VARIANT" = "dev" ] && REQS="$ROOT/build/requirements-dev.txt"
python -m pip install -r "$REQS"
python -c "import PySide6; print('PySide6', PySide6.__version__)"

pyinstaller --noconfirm --clean \
    --name fengrid \
    --add-data "$QT_DIR/qml:qml" \
    --add-data "$ROOT/fonts:fonts" \
    --paths "$QT_DIR/src" \
    "$QT_DIR/src/fengrid/__main__.py"

# signing: wire the Developer ID Application identity when credentials exist;
# notarization (notarytool) is documented in macos/README.md as the follow-up.
if [ -n "${MAC_CODESIGN_ID:-}" ]; then
    codesign --deep --force --options runtime \
        --sign "$MAC_CODESIGN_ID" "$OUT_DIR/fengrid" \
        || echo "WARNING: codesign failed — shipping unsigned (Gatekeeper will warn)" >&2
fi

zip -q -r "$OUT_DIR/fengrid-${VARIANT}-${TARGET}.zip" fengrid -x '*.DS_Store'
echo "artifact: $OUT_DIR/fengrid-${VARIANT}-${TARGET}.zip"
