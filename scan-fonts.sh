#!/usr/bin/env bash
# scan-fonts.sh — scan configurable font folders and build the font showcase
# data files (fonts-list.txt + font-meta.js) for fengrid's font showcase.
#
# Usage:
#   bash scan-fonts.sh [--dir <install>] [folder1 folder2 ...]
#   bash scan-fonts.sh --add <folder>       (add a folder to the saved list)
#   bash scan-fonts.sh --list              (show the saved folder list)
#
# Fonts are copied into fonts/<Family>/<file> next to fonts.html so previews
# work over file:// and http alike. Metadata (family, style, weight, slant)
# comes from fc-scan; files fc-scan can't read fall back to the filename.

set -u
APP_DIR="${FG_DIR:-$(cd "$(dirname "$0")" && pwd)}"
STATE_DIR="${FG_STATE_DIR:-$HOME/.local/state/fengrid}"
DIRS_FILE="$STATE_DIR/font-dirs.conf"

CYAN='\033[0;36m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; OFF='\033[0m'
info()  { printf "${CYAN}::${OFF} %s\n" "$*"; }
ok()    { printf "${GREEN}::${OFF} %s\n" "$*"; }
warn()  { printf "${YELLOW}::${OFF} %s\n" "$*"; }

# show_progress <current> <total> [label] — in-place progress bar on stderr.
show_progress() {
    [ -t 2 ] || return 0
    local cur=$1 total=$2 label="${3:-}"
    [ "$total" -gt 0 ] 2>/dev/null || return 0
    local pct=$((cur * 100 / total))
    [ "$pct" -gt 100 ] && pct=100
    local width=28 filled i bar=""
    filled=$((pct * width / 100))
    for ((i = 0; i < filled; i++)); do bar+="█"; done
    for ((i = filled; i < width; i++)); do bar+="░"; done
    printf '\r  %s [%s] %3d%% (%d/%d)\033[K' "$label" "$bar" "$pct" "$cur" "$total" >&2
}
progress_done() { [ -t 2 ] && printf '\n' >&2; return 0; }

FONT_EXTS=(-name '*.ttf' -o -name '*.otf' -o -name '*.woff' -o -name '*.woff2' -o -name '*.ttc' -o -name '*.eot')

# --- helpers -----------------------------------------------------------------

sanitize_family() {
    # "DejaVu Sans" -> "DejaVuSans"; strip filesystem-hostile characters
    printf '%s' "$1" | tr -d '/' | tr -c 'A-Za-z0-9._ -' '-' | sed 's/ \+//g; s/^-\+//; s/-\+$//' | tr -d ' '
}

ensure_dirs_file() {
    mkdir -p "$STATE_DIR"
    [ -f "$DIRS_FILE" ] || printf '%s\n' \
        "$HOME/.local/share/fonts" \
        "$HOME/.fonts" \
        /usr/share/fonts > "$DIRS_FILE"
}

load_dirs() {
    ensure_dirs_file
    grep -v '^#' "$DIRS_FILE" | grep -v '^$' || true
}

add_dir() {
    ensure_dirs_file
    local d
    d="$(realpath "$1" 2>/dev/null || echo "$1")"
    if [ ! -d "$d" ]; then
        warn "not a directory: $d"
        return 1
    fi
    if grep -qxF "$d" "$DIRS_FILE" 2>/dev/null; then
        info "already in the list: $d"
        return 0
    fi
    printf '%s\n' "$d" >> "$DIRS_FILE"
    ok "added: $d"
}

# --- argument handling -------------------------------------------------------

MODE="scan"
CUSTOM_DIRS=()
while [ $# -gt 0 ]; do
    case "$1" in
        --dir)   APP_DIR="$2"; shift 2 ;;
        --add)   MODE="add"; add_dir "$2"; shift 2 ;;
        --list)  MODE="list" ;;
        --help|-h)
            sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
            exit 0 ;;
        *) CUSTOM_DIRS+=("$1") ;;
    esac
    shift
done

if [ "$MODE" = "list" ]; then
    echo "Configured font folders:"
    load_dirs | while read -r d; do echo "  $d"; done
    exit 0
fi

# --- scan --------------------------------------------------------------------

# collect candidate font files from the configured + custom dirs
TMP_LIST="$(mktemp)" || exit 1
trap 'rm -f "$TMP_LIST"' EXIT

DIRS=()
if [ ${#CUSTOM_DIRS[@]} -gt 0 ]; then
    DIRS=("${CUSTOM_DIRS[@]}")
else
    while IFS= read -r d; do DIRS+=("$d"); done < <(load_dirs)
fi

if [ ${#DIRS[@]} -eq 0 ]; then
    warn "no font folders configured — add one with:  $0 --add <folder>"
    exit 1
fi

FOUND=0
for d in "${DIRS[@]}"; do
    [ -d "$d" ] || { warn "skipping (not a directory): $d"; continue; }
    N=$(find "$d" -type f "${FONT_EXTS[@]}" 2>/dev/null | wc -l)
    info "scanning $d — $N font files"
    find "$d" -type f "${FONT_EXTS[@]}" 2>/dev/null >> "$TMP_LIST"
    FOUND=$((FOUND + N))
done

if [ "$FOUND" -eq 0 ]; then
    warn "no font files found in any configured folder"
    exit 1
fi
info "found $FOUND font files — copying + reading metadata ..."

# --- copy + metadata ---------------------------------------------------------

FONT_DIR="$APP_DIR/fonts"
mkdir -p "$FONT_DIR"
LIST_OUT="$APP_DIR/fonts-list.txt"
META_OUT="$APP_DIR/font-meta.js"

: > "$LIST_OUT"
printf 'window.FONT_META={};\n' > "$META_OUT"

COPIED=0
UNREADABLE=0
ITER=0
TOTAL_FILES=$(wc -l < "$TMP_LIST")

# fc-scan extracts metadata; run once per file (batch would be faster but
# the per-file parse keeps the mapping simple)
while IFS= read -r src; do
    ITER=$((ITER + 1))
    show_progress "$ITER" "$TOTAL_FILES" "fonts"
    [ -f "$src" ] || continue
    base=$(basename "$src")
    ext="${base##*.}"
    ext_lower=$(printf '%s' "$ext" | tr '[:upper:]' '[:lower:]')

    # ask fontconfig for family + style + weight + slant
    META=""
    if command -v fc-scan >/dev/null 2>&1; then
        META=$(fc-scan --format '%{family}|%{style}|%{weight}|%{slant}' "$src" 2>/dev/null | head -1)
    fi
    family="$(printf '%s' "$META" | cut -d'|' -f1 | sed 's/:.*//' )"
    style="$(printf '%s' "$META" | cut -d'|' -f2)"
    weight="$(printf '%s' "$META" | cut -d'|' -f3)"
    slant="$(printf '%s' "$META" | cut -d'|' -f4)"
    if [ -z "$family" ] || [ "$family" = "$META" ]; then
        # fc-scan failed or empty — fall back to the filename
        family="${base%.*}"
        style=""
        weight=""
        slant=""
        UNREADABLE=$((UNREADABLE + 1))
    fi

    # sanitize for a directory name
    dir_name=$(sanitize_family "$family")
    [ -n "$dir_name" ] || dir_name="unknown"

    dest_dir="$FONT_DIR/$dir_name"
    mkdir -p "$dest_dir"
    dest="$dest_dir/$base"

    # skip if the identical file is already there
    if [ -f "$dest" ] && cmp -s "$src" "$dest" 2>/dev/null; then
        :  # already copied
    else
        cp -L "$src" "$dest" 2>/dev/null || { warn "copy failed: $src"; continue; }
    fi

    echo "$dest" >> "$LIST_OUT"

    # append metadata to font-meta.js (built up in a temp then assembled)
    rel="fonts/$dir_name/$base"
    printf 'window.FONT_META[%s]={f:%s,s:%s,w:%s,l:%s};\n' \
        "\"$rel\"" "\"$family\"" "\"$style\"" "${weight:-0}" "${slant:-0}" \
        >> "$META_OUT.tmp"
    COPIED=$((COPIED + 1))
done < "$TMP_LIST"
progress_done

# assemble font-meta.js with the header
if [ -f "$META_OUT.tmp" ]; then
    printf 'window.FONT_META={};\n' > "$META_OUT"
    cat "$META_OUT.tmp" >> "$META_OUT"
    rm -f "$META_OUT.tmp"
fi

ok "Font showcase data ready: $COPIED fonts in $FONT_DIR"
[ "$UNREADABLE" -gt 0 ] && warn "$UNREADABLE files had no readable metadata (used filename as the family name)"
info "Open fonts.html to browse them."
