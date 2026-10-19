#!/usr/bin/env bash
#
# build-linux.sh — build Fengrid (Qt 6) for linux-x64 | linux-arm64.
#
# Usage:
#   build-linux.sh <linux-x64|linux-arm64>
#   FENGRID_VARIANT=prod|dev   (default: prod; dev adds pytest/ruff to the env)
#   FENGRID_IN_CONTAINER=1     (set by docker/linux-*.Dockerfile: use the
#                               container's system python, skip the venv)
#   FENGRID_SMOKE=1            (after PyInstaller, launch the frozen binary
#                               offscreen and capture a screenshot — fails the
#                               build if it does not start)
#
# Native run validated 2026-10-19 (linux-x64 prod, onedir + tar.gz + offscreen
# smoke). The spec is REGENERATED on every run into
# build/pyinstaller/<target>-<variant>/ — never committed (host-absolute
# paths in a checked-in spec are a landmine; see .dockerignore *.spec).
set -euo pipefail

TARGET="${1:?usage: build-linux.sh <linux-x64|linux-arm64>}"
VARIANT="${FENGRID_VARIANT:-prod}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
QT_DIR="$ROOT/qt"
OUT_DIR="$QT_DIR/dist"
SPEC_DIR="$ROOT/build/pyinstaller/$TARGET-$VARIANT"

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

# data bundle: every entry is optional at build time — a missing tree logs a
# warning and is skipped instead of aborting the build halfway through
# PyInstaller (2026-10-19: branding/ is gitignored by design and the runtime
# mark ships from qt/resources instead; see qt/resources/branding/README.md)
data_entries=()
add_data() {
    local src="$1" dest="$2"
    if [ -e "$src" ]; then
        data_entries+=(--add-data "$src:$dest")
    else
        echo "warning: data tree missing, skipped: $src" >&2
    fi
}
add_data "$QT_DIR/qml" "qml"
add_data "$ROOT/fonts" "fonts"
add_data "$QT_DIR/resources" "resources"

mkdir -p "$SPEC_DIR"
python -m PyInstaller --noconfirm --clean \
    --specpath "$SPEC_DIR" \
    "${data_entries[@]}" \
    --name fengrid \
    --paths "$QT_DIR/src" \
    "$QT_DIR/src/fengrid/__main__.py"

# optional smoke test (FENGRID_SMOKE=1): turns "it compiled" into "it starts".
# Offscreen + software rendering + WebEngine sandbox flags — container-safe.
if [ "${FENGRID_SMOKE:-0}" = "1" ]; then
    SMOKE_DB="${TMPDIR:-/tmp}/fengrid-smoke-$$.db"
    SMOKE_SHOT="$OUT_DIR/smoke-${TARGET}-${VARIANT}.png"
    echo "smoke: launching frozen binary offscreen"
    QT_QPA_PLATFORM=offscreen \
    QT_QUICK_BACKEND=software \
    QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox --disable-gpu" \
    HOME="${TMPDIR:-/tmp}" \
    XDG_DATA_HOME="${TMPDIR:-/tmp}/fengrid-smoke-home" \
        "$OUT_DIR/fengrid/fengrid" \
        --screenshot "$SMOKE_SHOT" --shot-delay 1500 --no-scan --db "$SMOKE_DB" \
        || { echo "error: smoke test failed (binary did not start cleanly)" >&2; exit 1; }
    [ -s "$SMOKE_SHOT" ] || { echo "error: smoke screenshot is empty" >&2; exit 1; }
    echo "smoke: ok ($SMOKE_SHOT)"
fi

# optional AppImage packaging lands here once the skeleton is validated
# (linuxdeploy + the Qt runtime plugin; see docs/architecture/0001 §11).

tar -czf "$OUT_DIR/fengrid-${VARIANT}-${TARGET}.tar.gz" -C "$OUT_DIR" fengrid
echo "artifact: $OUT_DIR/fengrid-${VARIANT}-${TARGET}.tar.gz"
