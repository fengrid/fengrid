#!/usr/bin/env bash
#
# build-linux.sh — build Fengrid (Qt 6) for linux-x64 | linux-arm64.
#
# Usage:
#   build-linux.sh [--clean] <linux-x64|linux-arm64>
#   --clean  remove previous artifacts (qt/dist, this target's spec dir)
#            before building, so the bundle cannot inherit stale state (#44)
#   FENGRID_VARIANT=prod|dev   (default prod; dev also installs the dev
#                               dependency-group — pytest/ruff — via uv)
#   FENGRID_SMOKE=1            (after PyInstaller, launch the frozen binary
#                               offscreen and capture a screenshot — fails the
#                               build if it does not start)
#
# Native run validated 2026-10-19 (linux-x64 prod, onedir + tar.gz + offscreen
# smoke). The spec is REGENERATED on every run into
# build/pyinstaller/<target>-<variant>/ — never committed (host-absolute
# paths in a checked-in spec are a landmine; see .dockerignore *.spec).
set -euo pipefail

CLEAN=0
ARGS=()
for arg in "$@"; do
    case "$arg" in
        --clean|-c) CLEAN=1 ;;
        *)          ARGS+=("$arg") ;;
    esac
done
TARGET="${ARGS[0]:-}"
[ -n "$TARGET" ] || { echo "usage: build-linux.sh [--clean] <linux-x64|linux-arm64>" >&2; exit 1; }
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

if [ "$CLEAN" = "1" ]; then
    echo "clean: removing previous artifacts ($OUT_DIR, $SPEC_DIR)"
    rm -rf "$OUT_DIR" "$SPEC_DIR"
fi

cd "$QT_DIR"

# Frozen build environment: qt/pyproject.toml + the committed uv.lock are the
# single source of truth. Prod installs the build group only; dev adds the dev
# group (pytest/ruff). uv sync creates/reuses qt/.venv — the same venv layout
# pip produced, so activation and every python/PyInstaller call below is
# unchanged. The old FENGRID_IN_CONTAINER split (container used system python)
# is gone: uv ships in the builder image, so in-container and native runs are
# identical.
if [ "$VARIANT" = "dev" ]; then
    uv sync --frozen --group build      # dev group is included by default
else
    uv sync --frozen --no-dev --group build
fi
# shellcheck disable=SC1091
. .venv/bin/activate

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

# build provenance (#43): stamp the commit this bundle was built from —
# the About screen reads it via fengrid.buildinfo. Docker runs have no
# .git inside the image; build-docker-linux.sh forwards the host commit
# as FENGRID_BUILD_COMMIT. The stamp file is gitignored.
commit="${FENGRID_BUILD_COMMIT:-}"
[ -z "$commit" ] && commit="$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || true)"
[ -z "$commit" ] && commit="unknown"
stamp="$QT_DIR/.build-commit"
printf '%s\n' "$commit" > "$stamp"
add_data "$stamp" "."

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

# Strip the HOST X/GL stack from the bundle (GLX crash fix, 2026-10-20).
# The build container's Mesa/glvnd/X11 libs get bundled by PyInstaller and
# shadow the end machine's copies at runtime: the system GLX vendor library
# (libGLX_mesa / libGLX_nvidia via glvnd) links libX11/libxcb by soname, the
# loader hands it the BUNDLED copies, and two Xlib instances in one process
# break vendor dispatch — every FBConfig query fails and Qt aborts with
# "qglx_findConfig: Failed to finding matching FBConfig … Could not
# initialize GLX" (SIGABRT on a real desktop). Same rule linuxdeployqt /
# AppImage guides enforce: X11/xcb/GL must come from the END machine, where
# a working stack is guaranteed on any box that can show a window. Qt
# resolves them from the system at runtime; the offscreen/software QA path
# never loads them, so the container-side smoke test below stays valid.
#
# KEPT: the Qt xcb helper libs (cursor/icccm/image/keysyms/render-util) —
# genuinely optional packages a desktop may lack, and not linked by GL
# vendor libs, so bundling them is safe. Everything else matching
# libX*/libxcb*/libGL*/xkb resolves from the system.
gl_stripped=0
while IFS= read -r -d '' f; do
    base="$(basename "$f")"
    case "$base" in
        libxcb-cursor*|libxcb-icccm*|libxcb-image*|libxcb-keysyms*|\
        libxcb-render-util*) continue ;;                    # keep helpers
    esac
    # auditwheel-hashed vendored copies (lib<name>-<8hex>.so…) carry a
    # NON-SYSTEM soname: they can never satisfy the end machine's DT_NEEDED
    # lookups, so they cannot shadow anything — the GLX failure needs the
    # UNHASHED copies (libX11.so.1 / libxcb.so.1 / libGL.so.1) in the
    # bundle, and those are still stripped below. Wheel extensions hard-link
    # their own hashed copies: Pillow 13's _imaging NEEDs
    # pillow.libs/libxcb-9065bb12.so.1.1.0, and stripping it made every
    # frozen build die at `from . import _imaging` (PIL/Image.py:94) with
    # ImportError before the app could open.
    if [[ "$base" =~ -[0-9a-f]{8}\.so ]]; then
        echo "gl-strip: keep hashed vendored $base" >&2
        continue
    fi
    rm -f "$f"
    gl_stripped=$((gl_stripped + 1))
    echo "gl-strip: $base" >&2
done < <(find "$OUT_DIR/fengrid" \( -type f -o -type l \) \( \
    -name 'libGL.so*' -o -name 'libEGL.so*' -o -name 'libGLESv2*' \
    -o -name 'libGLX.so*' -o -name 'libOpenGL.so*' -o -name 'libglapi.so*' \
    -o -name 'libgbm.so*' -o -name 'libdrm.so*' -o -name 'libnvidia-*' \
    -o -name 'libvulkan.so*' \
    -o -name 'libX11.so*' -o -name 'libX11-xcb.so*' -o -name 'libXau*' \
    -o -name 'libXdmcp*' -o -name 'libXext*' -o -name 'libXrender*' \
    -o -name 'libXcursor*' -o -name 'libXfixes*' -o -name 'libXi.so*' \
    -o -name 'libXinerama*' -o -name 'libXrandr*' -o -name 'libXcomposite*' \
    -o -name 'libXdamage*' -o -name 'libXss*' -o -name 'libXxf86vm*' \
    -o -name 'libXtst*' \
    -o -name 'libxcb.so*' -o -name 'libxcb-*' \
    -o -name 'libxkbcommon*' -o -name 'libxkbfile*' \) \
    -print0)
echo "gl-strip: removed $gl_stripped host X/GL libs"

# Dangling-symlink sweep: PyInstaller's pillow.libs tree vendors its own
# libXau/libxcb copies with SYMLINKS pointing at them from _internal/ top
# level. -type f stripped the real files but -type l is required for the
# links, otherwise the bundle ships dead references. Remove any symlink in
# the bundle whose target no longer exists (after the strip above).
while IFS= read -r -d '' f; do
    echo "gl-strip: dangling $(basename "$f")" >&2
    rm -f "$f"
done < <(find "$OUT_DIR/fengrid" -xtype l -print0)

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

# Normalize bundle permissions BEFORE packing: PySide6 ships (and
# QtWebEngine re-creates at runtime, as root during the smoke test) a
# drwx------ `PySide6/Qt/resources/locales` — a 0700 root:root dir the
# wrapper's --user extraction cannot read (`cp: Permission denied`),
# and any non-owner run on the end machine would hit the same wall.
# a+rX: others get read + dir traversal, exec bits stay where they were.
chmod -R a+rX "$OUT_DIR/fengrid"

# optional AppImage packaging lands here once the skeleton is validated
# (linuxdeploy + the Qt runtime plugin; see docs/architecture/0001 §11).

tar -czf "$OUT_DIR/fengrid-${VARIANT}-${TARGET}.tar.gz" -C "$OUT_DIR" fengrid
echo "artifact: $OUT_DIR/fengrid-${VARIANT}-${TARGET}.tar.gz"
