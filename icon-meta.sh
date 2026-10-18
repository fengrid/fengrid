#!/usr/bin/env bash
#
# icon-meta.sh — generate meta.js: real image specs for every local icon.
#
# Runs ImageMagick `identify` across the install's icons/ tree and writes
# <install>/meta.js (window.ICON_META) with, per icon file:
#   b  file size in bytes          w/h  true pixel dimensions
#   cs colorspace (sRGB, Gray, …)  k    unique color count
#   m  1 when the image is monochrome (Bilevel/Grayscale)
#
# Files identify cannot read (e.g. SVG when no SVG delegate is installed)
# simply get no entry — the page then falls back to what the filename and
# folder layout reveal. Everything here is best-effort and never fatal.
#
# Usage: icon-meta.sh <install dir> [--quiet]
#        (run by install.sh after the icon copy, and by refresh-icons.sh)

set -u

INSTALL_DIR="${1:-}"; shift || true
QUIET=false
[ "${1:-}" = "--quiet" ] && QUIET=true
[ -n "$INSTALL_DIR" ] || { echo "usage: icon-meta.sh <install dir>" >&2; exit 1; }
[ -f "$INSTALL_DIR/index.html" ] || { echo "no install found at $INSTALL_DIR" >&2; exit 1; }
[ -d "$INSTALL_DIR/icons" ] || { $QUIET || echo "no icons/ — nothing to inspect"; exit 0; }

IDENTIFY=""
for c in magick identify; do
    command -v "$c" >/dev/null 2>&1 || continue
    if [ "$c" = magick ]; then IDENTIFY="magick identify"; else IDENTIFY="$c"; fi
    break
done
[ -n "$IDENTIFY" ] || { $QUIET || echo "ImageMagick not available — skipping metadata"; exit 0; }

LISTF=$(mktemp) || exit 1
OUTF=$(mktemp) || exit 1
trap 'rm -f "$LISTF" "$OUTF"' EXIT

# stable order, NUL-safe discovery via plain find (paths may contain spaces;
# the @list file handles them as long as they contain no newlines).
# SVG files are skipped: identify rasterizes them through slow delegates and
# the page already knows a vector source from the filename.
find "$INSTALL_DIR/icons" -type f ! -name '*.svg' ! -name '*.svgz' | \
    sed "s|^$INSTALL_DIR/||" | sort > "$LISTF"

# shellcheck disable=SC2086
( cd "$INSTALL_DIR" && tr '\n' '\0' < "$LISTF" | \
    xargs -0 -n 200 $IDENTIFY -quiet -format '%i|%B|%w|%h|%[colorspace]|%k|%[type]\n' ) \
    > "$OUTF" 2>/dev/null

awk -F'|' '
BEGIN { printf "window.ICON_META={"; first = 1 }
NF >= 7 && $1 ~ /^icons\// && $2 ~ /^[0-9]+$/ && $3 ~ /^[0-9]+$/ && $4 ~ /^[0-9]+$/ {
    key = $1; sub(/^icons\//, "", key)
    gsub(/\\/, "\\\\", key); gsub(/"/, "\\\"", key)
    cs = $5; gsub(/"/, "", cs); gsub(/\\/, "", cs)
    m = ($7 ~ /Bilevel|Grayscale/ || $5 ~ /Gray/) ? 1 : 0
    printf "%s\"%s\":{\"b\":%d,\"w\":%d,\"h\":%d,\"cs\":\"%s\",\"k\":%d,\"m\":%d}",
        (first ? "" : ","), key, $2, $3, $4, cs, $6, m
    first = 0
}
END { print "};" }
' "$OUTF" > "$INSTALL_DIR/meta.js.tmp"

if [ -s "$INSTALL_DIR/meta.js.tmp" ]; then
    mv "$INSTALL_DIR/meta.js.tmp" "$INSTALL_DIR/meta.js"
    N=$(grep -o '"b":' "$INSTALL_DIR/meta.js" | wc -l)
    $QUIET || echo "icon metadata written: $N entries (meta.js)"
else
    rm -f "$INSTALL_DIR/meta.js.tmp"
    $QUIET || echo "identify produced no usable metadata"
fi