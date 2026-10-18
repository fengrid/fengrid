#!/usr/bin/env bash
#
# refresh-icons.sh — reconcile the icon list with the icons/ folder.
#
# Run this after manually copying icon files into <install>/icons/ so they
# appear in the showcase. It:
#   1. relocates loose files from the icons/ root into icons/Manual/
#      (the page parser expects every icon to live in a theme subfolder)
#   2. converts non-browser-renderable formats when possible:
#      .icns -> .png via macOS `sips`, .xpm -> .png via ImageMagick
#   3. adds every file found under icons/ to the list
#   4. prunes list entries pointing at icons/ files that no longer exist
#   5. regenerates list.js (the file:// fallback payload)
#
# System/theme icons from the original scan (paths outside icons/) are kept.
#
# Usage:
#   refresh-icons.sh [--dir <install dir>] [--quiet]
#   refresh-icons.sh --merge-list <list file> [--dir <install dir>] [--quiet]
#       --merge-list merges the icons/ contents into an existing list file
#       and regenerates list.js; used by the weekly updater after it
#       re-scans the configured icon roots (so manual additions survive).
#
# The install dir defaults to ~/icon-browser (override with --dir or
# $ICON_BROWSER_DIR). Reload the showcase page after refreshing.
#
# --update-metadata [enabled|disabled|force]
#     metadata mode passed to icon-meta.sh (enabled by default: only
#     new/changed files are re-identified; force re-identifies everything).

set -u

INSTALL_DIR="${ICON_BROWSER_DIR:-$HOME/icon-browser}"
MERGE_LIST=""
QUIET=false
META_MODE="enabled"
while [ $# -gt 0 ]; do
    case "$1" in
        --dir)            INSTALL_DIR="$2"; shift ;;
        --merge-list)     MERGE_LIST="$2"; shift ;;
        --quiet)          QUIET=true ;;
        --update-metadata)
            case "${2:-}" in enabled|disabled|force) META_MODE="$2"; shift ;; esac ;;
        --update-metadata=*)
            META_MODE="${1#--update-metadata=}";;
        *) echo "unknown option: $1" >&2; exit 1 ;;
    esac
    shift
done
case "$META_MODE" in enabled|disabled|force) ;; *) META_MODE="enabled" ;; esac

say() { $QUIET || printf '%s\n' "$*"; }

[ -f "$INSTALL_DIR/index.html" ] || { echo "no install found at $INSTALL_DIR" >&2; exit 1; }
ICONS_DIR="$INSTALL_DIR/icons"
LIST_FILE="$INSTALL_DIR/list.txt"
[ -f "$LIST_FILE" ] || { echo "no $LIST_FILE — run install.sh first" >&2; exit 1; }
BASE_LIST="${MERGE_LIST:-$LIST_FILE}"
[ -f "$BASE_LIST" ] || { echo "no $BASE_LIST" >&2; exit 1; }

# --- converters -------------------------------------------------------------
CONVERT_CMD=""
for c in magick convert; do
    command -v "$c" >/dev/null 2>&1 && { CONVERT_CMD="$c"; break; }
done
HAVE_SIPS=false
command -v sips >/dev/null 2>&1 && HAVE_SIPS=true

# --- 1. relocate loose files from the icons/ root into icons/Manual/ --------
if [ -d "$ICONS_DIR" ]; then
    for f in "$ICONS_DIR"/*; do
        [ -f "$f" ] || continue
        mkdir -p "$ICONS_DIR/Manual"
        mv "$f" "$ICONS_DIR/Manual/" && say "moved $(basename "$f") into Manual/"
    done
fi
[ -d "$ICONS_DIR" ] || { say "icons/ folder does not exist — nothing to do"; exit 0; }

# --- 2. collect every previewable file currently under icons/ ---------------
# find runs to a temp file first: a `while read < <(find ...)` process
# substitution would run in a subshell and lose the conversion counters
FILES=$(mktemp) || exit 1
find "$ICONS_DIR" -type f > "$FILES"

MANUAL=$(mktemp) || exit 1
MANUAL_CONVERSIONS=0
SKIP_UNRENDERABLE=0
while IFS= read -r f; do
    [ -f "$f" ] || continue
    case "$f" in
        *.icns)
            if $HAVE_SIPS; then
                dest="${f%.*}.png"
                sips -s format png --resampleHeight 256 "$f" --out "$dest" >/dev/null 2>&1 && {
                    printf '%s\n' "$dest"; MANUAL_CONVERSIONS=$((MANUAL_CONVERSIONS + 1))
                } || SKIP_UNRENDERABLE=$((SKIP_UNRENDERABLE + 1))
            else
                SKIP_UNRENDERABLE=$((SKIP_UNRENDERABLE + 1))
            fi
            ;;
        *.xpm)
            if [ -n "$CONVERT_CMD" ]; then
                dest="${f%.*}.png"
                "$CONVERT_CMD" "$f" "$dest" >/dev/null 2>&1 && {
                    printf '%s\n' "$dest"; MANUAL_CONVERSIONS=$((MANUAL_CONVERSIONS + 1))
                } || SKIP_UNRENDERABLE=$((SKIP_UNRENDERABLE + 1))
            else
                SKIP_UNRENDERABLE=$((SKIP_UNRENDERABLE + 1))
            fi
            ;;
        *.png|*.svg|*.ico|*.jpg|*.jpeg|*.gif|*.webp|*.bmp)
            printf '%s\n' "$f"
            ;;
        *)
            SKIP_UNRENDERABLE=$((SKIP_UNRENDERABLE + 1))
            ;;
    esac
done < "$FILES" > "$MANUAL"

# --- 3. merge: keep non-icons/ entries from the base list, append manual ----
MERGED=$(mktemp) || exit 1
awk -v pre="$ICONS_DIR/" 'index($0, pre) != 1' "$BASE_LIST" > "$MERGED"

# only keep icons/ files whose relative path (after /icons/) is not already
# covered by a scanned entry — the installer lists theme icons via their
# system paths, and the page renders those from the local icons/ copy, so
# re-listing the copies would just duplicate them in the grid
NEW_MANUAL=$(mktemp) || exit 1
NEW_COUNT=0
COVERED=0
while IFS= read -r f; do
    rel="${f#"${ICONS_DIR}/"}"
    [ "$rel" != "$f" ] || continue
    if grep -qF -- "/$rel" "$MERGED"; then
        COVERED=$((COVERED + 1))
    else
        printf '%s\n' "$f" >> "$NEW_MANUAL"
        NEW_COUNT=$((NEW_COUNT + 1))
    fi
done < "$MANUAL"

cat "$NEW_MANUAL" >> "$MERGED"
awk '!seen[$0]++' "$MERGED" > "$MERGED.final"

# --- 4. write back + regenerate list.js -------------------------------------
if [ -n "$MERGE_LIST" ]; then
    DEST="$MERGE_LIST"
else
    DEST="$LIST_FILE"
fi
{
    printf 'window.ICON_LIST=['
    sed 's/^[[:space:]]*//; s/["\\]/\\&/g; s/^/"/; s/$/",/' "$MERGED.final" | tr -d '\n' | sed 's/,$//'
    printf '];\n'
} > "$INSTALL_DIR/list.js"
mv "$MERGED.final" "$DEST"
rm -f "$FILES" "$MANUAL" "$NEW_MANUAL" "$MERGED" "$MERGED.final"

TOTAL=$(wc -l < "$INSTALL_DIR/list.txt")
say "icon list refreshed: $TOTAL entries total, $NEW_COUNT new from icons/"
[ "$COVERED" -gt 0 ] && say "  ($COVERED files in icons/ already covered by the scan)"
[ "$MANUAL_CONVERSIONS" -gt 0 ] && say "  ($MANUAL_CONVERSIONS converted to png)"
[ "$SKIP_UNRENDERABLE" -gt 0 ] && say "  ($SKIP_UNRENDERABLE files skipped — format not browser-renderable and no converter available)"
say "reload the showcase page to see the updated grid."

# rebuild meta.js so the new files get real specs in the details bar
if [ "$META_MODE" != disabled ]; then
    for META in "$INSTALL_DIR/icon-meta.sh" "$(dirname "$0")/icon-meta.sh"; do
        if [ -f "$META" ]; then
            bash "$META" "$INSTALL_DIR" --quiet --mode "$META_MODE"
            break
        fi
    done
fi
exit 0