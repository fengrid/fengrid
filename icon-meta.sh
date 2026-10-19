#!/usr/bin/env bash
#
# icon-meta.sh — generate meta.js: real image specs for every local icon.
#
# Incremental and fingerprint-tracked: every scanned file is fingerprinted
# with its size + mtime — a cheap stand-in for a content hash. A file that
# has neither changed nor been replaced keeps its fingerprint, so identical
# files are never re-identified; only new/changed files are. Fingerprints
# and the JSON fragment they produced live in <install>/meta-state.tsv,
# and meta.js is regenerated from that ledger (which also prunes entries
# for files that no longer exist).
#
# Modes (--update-metadata semantics, shared with install.sh / scan-icons.sh
# / update.sh):
#   enabled (default)  compare fingerprints; identify only new/changed files
#   disabled           skip metadata work entirely, leave meta.js untouched
#   force              ignore fingerprints; re-identify every icon
#
# Per icon file, meta.js (window.ICON_META) carries:
#   b  file size in bytes            w/h  true pixel dimensions
#   cs colorspace (sRGB, Gray, …)    k    unique color count
#   m  1 when Bilevel/Grayscale (monochrome)
#
# SVG files are skipped on purpose: identify rasterizes them through slow
# delegates, and the page already knows a vector source from the filename.
# Interrupts (Ctrl-C) are safe — all output goes through temp files and
# meta.js/meta-state.tsv are replaced atomically only after a complete run.
#
# Usage: icon-meta.sh <install dir> [--quiet] [--force] [--mode enabled|disabled|force]
#        (run by install.sh after the icon copy, and by refresh-icons.sh)

set -u

INSTALL_DIR=""
MODE="enabled"
QUIET=false
while [ $# -gt 0 ]; do
    case "$1" in
        --dir)    INSTALL_DIR="$2"; shift ;;
        --quiet)  QUIET=true ;;
        --force)  MODE="force" ;;
        --mode)   MODE="$2"; shift ;;
        --mode=*) MODE="${1#--mode=}" ;;
        *)  if [ -z "$INSTALL_DIR" ]; then
                INSTALL_DIR="$1"            # positional: the install dir
            else
                echo "unknown option: $1" >&2; exit 1
            fi ;;
    esac
    shift
done
[ -n "$INSTALL_DIR" ] || { echo "usage: icon-meta.sh <install dir>" >&2; exit 1; }
case "$MODE" in enabled|disabled|force) ;; *) echo "bad mode: $MODE" >&2; exit 1 ;; esac
[ -f "$INSTALL_DIR/index.html" ] || { echo "no install found at $INSTALL_DIR" >&2; exit 1; }

say() { $QUIET || printf '%s\n' "$*"; }

if [ "$MODE" = disabled ]; then
    say "metadata update disabled — leaving meta.js unchanged"
    exit 0
fi
[ -d "$INSTALL_DIR/icons" ] || { say "no icons/ — nothing to inspect"; exit 0; }

IDENTIFY=""
for c in magick identify; do
    command -v "$c" >/dev/null 2>&1 || continue
    if [ "$c" = magick ]; then IDENTIFY="magick identify"; else IDENTIFY="$c"; fi
    break
done
[ -n "$IDENTIFY" ] || { say "ImageMagick not available — skipping metadata"; exit 0; }

# stat portability: GNU (linux) vs BSD (macOS) — prints "<size> <mtime>"
smt() {
    if stat --printf '%s %Y' "$1" 2>/dev/null; then return; fi
    stat -f '%z %m' "$1" 2>/dev/null
}

ICONS_DIR="$INSTALL_DIR/icons"
STATE="$INSTALL_DIR/meta-state.tsv"
NEW_STATE="$STATE.new"
NEW_META="$INSTALL_DIR/meta.js.new"

TMP_LIST=$(mktemp) || exit 1
TMP_TODO=$(mktemp) || exit 1
TMP_RAW=$(mktemp) || exit 1
TMP_NEWFRAG=$(mktemp) || exit 1
TMP_JOIN=$(mktemp) || exit 1
cleanup() { rm -f "$TMP_LIST" "$TMP_TODO" "$TMP_RAW" "$TMP_NEWFRAG" "$TMP_JOIN" 2>/dev/null; }
trap 'cleanup; exit 130' INT TERM

# 1. current rasters: key <TAB> size <TAB> mtime  (sorted, stable)
# key = path relative to icons/ (page/meta.js/ledger key). identify is handed
# the icons/-prefixed path at run time (it executes from the install dir).
# include symlinks (--icons link installs); `[ -f ]` drops dangling links
find "$ICONS_DIR" \( -type f -o -type l \) ! -name '*.svg' ! -name '*.svgz' | LC_ALL=C sort | \
while IFS= read -r f; do
    key="${f#"$ICONS_DIR"/}"
    fp=$(smt "$f") || continue
    [ -n "$fp" ] || continue
    printf '%s\t%s\t%s\n' "$key" "${fp%% *}" "${fp##* }"
done > "$TMP_LIST"

# 2. what needs identifying
STATE_IN="$STATE"
[ -f "$STATE" ] || STATE_IN="/dev/null"
if [ "$MODE" = force ]; then
    cut -f1 "$TMP_LIST" > "$TMP_TODO"
else
    # new/changed = fingerprint differs from (or is missing in) the ledger
    awk -F'\t' '
        FILENAME == ARGV[1] {
            if (NF >= 4) seen[$1] = $2 SUBSEP $3
            next
        }
        NF >= 3 {
            if (seen[$1] != ($2 SUBSEP $3)) print $1
        }' "$STATE_IN" "$TMP_LIST" > "$TMP_TODO"
fi

TOTAL=$(wc -l < "$TMP_LIST")
TODO=$(wc -l < "$TMP_TODO")
REMOVED=0
if [ -f "$STATE" ]; then
    REMOVED=$(awk -F'\t' '
        FILENAME == ARGV[1] { cur[$1] = 1; next }
        { if (NF >= 4 && !($1 in cur)) n++ }
        END { print n + 0 }' "$TMP_LIST" "$STATE")
fi

if [ "$MODE" = force ]; then
    say "identifying all $TOTAL icons (--update-metadata force) ..."
else
    say "icon metadata: $TOTAL files, $TODO new/changed, $((TOTAL - TODO)) unchanged (skipped), $REMOVED removed"
fi
if [ "$TODO" -gt 1000 ]; then
    say "warning: $TODO files to inspect — this may take a few minutes."
    say "         Press Ctrl-C to cancel safely; meta.js is only replaced after a complete run."
fi

# 3. identify only what changed; emit "key \t JSON-fragment" lines
USED=0
if [ "$TODO" -gt 0 ]; then
    (
        cd "$INSTALL_DIR" || exit 1
        sed 's|^|icons/|' "$TMP_TODO" | tr '\n' '\0' | \
        xargs -0 -n 200 $IDENTIFY -quiet -format '%i|%B|%w|%h|%[colorspace]|%k|%[type]\n'
    ) > "$TMP_RAW" 2>/dev/null

    awk -F'|' '
        NF >= 7 && $1 ~ /^icons\// && $2 ~ /^[0-9]+$/ && $3 ~ /^[0-9]+$/ && $4 ~ /^[0-9]+$/ {
            key = $1; sub(/^icons\//, "", key)
            esc = key; gsub(/\\/, "\\\\", esc); gsub(/"/, "\\\"", esc)
            cs = $5; gsub(/["\\]/, "", cs)
            m = ($7 ~ /Bilevel|Grayscale/ || $5 ~ /Gray/) ? 1 : 0
            printf "%s\t\"%s\":{\"b\":%d,\"w\":%d,\"h\":%d,\"cs\":\"%s\",\"k\":%d,\"m\":%d}\n",
                key, esc, $2, $3, $4, cs, $6, m
        }' "$TMP_RAW" > "$TMP_NEWFRAG"
    USED=$(grep -c . "$TMP_NEWFRAG" || true)
    rm -f "$TMP_RAW"
fi

# 4. rebuild ledger + meta.js from the merged fragment set (atomic later)
awk -F'\t' -v state_out="$NEW_STATE" -v join_out="$TMP_JOIN" '
    BEGIN { first = 1 }
    FILENAME == ARGV[2] { if (NF >= 2) fresh[$1] = $2; next }   # fresh fragments (this run)
    FILENAME == ARGV[3] { if (NF >= 4) prev[$1] = $4; next }    # old ledger fragments
    {   # ARGV[1]: current rel \t size \t mtime
        if (NF >= 3) { order[++n] = $1; sz[n] = $2; mt[n] = $3 }
    }
    END {
        for (i = 1; i <= n; i++) {
            rel = order[i]
            frag = (rel in fresh) ? fresh[rel] : prev[rel]
            if (frag == "") continue                            # identify failed — skip until next run
            printf "%s\t%s\t%s\t%s\n", rel, sz[i], mt[i], frag > state_out
            printf "%s%s", (first ? "" : ","), frag > join_out
            first = 0
        }
        printf "};\n" > join_out
    }
' "$TMP_LIST" "$TMP_NEWFRAG" "$STATE_IN"

{ printf 'window.ICON_META={'; cat "$TMP_JOIN"; } > "$NEW_META"

cleanup

if [ -s "$NEW_META" ] && [ -s "$NEW_STATE" ]; then
    mv "$NEW_META" "$INSTALL_DIR/meta.js"
    mv "$NEW_STATE" "$STATE"
    N=$(grep -o '"b":' "$INSTALL_DIR/meta.js" | wc -l)
    say "meta.js written: $N entries ($USED newly identified, $((N - USED)) reused)"
else
    rm -f "$NEW_META" "$NEW_STATE"
    say "metadata build failed — previous meta.js left in place"
    exit 1
fi
exit 0