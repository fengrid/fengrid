#!/usr/bin/env bash
#
# scan-icons.sh — discover icon folders in common system locations and let
# the user select which ones to add to the Fengrid scan list.
#
# Usage:
#   scan-icons.sh --list       print candidates as "path<TAB>count" and exit
#   scan-icons.sh --pick       interactive selection UI (menu on stderr,
#                              selected paths on stdout, one per line)
#   scan-icons.sh --update-metadata [enabled|disabled|force] [--dir <install dir>]
#                              after scanning, refresh the install's icon
#                              metadata ledger (meta.js): enabled (default)
#                              identifies only new/changed files, disabled
#                              skips metadata, force re-identifies every icon.
#                              The install dir defaults to ~/fengrid
#                              ($ICON_BROWSER_DIR or --dir override).
#
# Candidates cover common locations per platform:
#   Linux: /usr/share/icons, /usr/local/share/icons, ~/.icons,
#          ~/.local/share/icons, /usr/share/pixmaps, snap and flatpak mounts
#   macOS: CoreTypes bundle, ~/.icons, /usr/local/share/icons, plus any
#          /usr/share/icons that exists
# A candidate with no icon files is filtered out; candidates nested inside
# another candidate are folded into their parent (the parent covers them).

set -u

MODE="list"
META_MODE=""
META_DIR="${FENGRID_DIR:-${ICON_BROWSER_DIR:-$HOME/fengrid}}"
while [ $# -gt 0 ]; do
    case "$1" in
        --list) MODE="list" ;;
        --pick) MODE="pick" ;;
        --exclude) shift; EXCLUDES+=("${1%/}") ;;
        --dir) META_DIR="$2"; shift ;;
        --update-metadata)
            MODE="list"
            case "${2:-}" in enabled|disabled|force) META_MODE="$2"; shift ;; esac
            [ -n "$META_MODE" ] || META_MODE="enabled" ;;
        --update-metadata=*) MODE="list"; META_MODE="${1#--update-metadata=}" ;;
        *) echo "unknown option: $1 (use --list, --pick or --update-metadata)" >&2; exit 1 ;;
    esac
    shift
done
case "$META_MODE" in ""|enabled|disabled|force) ;; *) META_MODE="enabled" ;; esac
EXCLUDES=("${EXCLUDES[@]:-}")

# --- candidate roots --------------------------------------------------------
CANDS=()
add() {
    case "$1" in
        *\*) # glob pattern: expand to existing dirs
            for d in $1; do [ -d "$d" ] && CANDS+=("$d"); done ;;
        *) [ -d "$1" ] && CANDS+=("$1") ;;
    esac
}

case "$(uname -s)" in
    Darwin)
        add "/System/Library/CoreServices/CoreTypes.bundle/Contents/Resources"
        add "/usr/share/icons"
        add "/usr/local/share/icons"
        add "$HOME/.icons"
        add "$HOME/Library/Icons"
        ;;
    *)
        add "/usr/share/icons"
        add "/usr/local/share/icons"
        add "$HOME/.icons"
        add "$HOME/.local/share/icons"
        add "/usr/share/pixmaps"
        add "/snap/*/current/usr/share/icons"
        add "$HOME/.local/share/flatpak/app/*/current/active/files/share/icons"
        add "/var/lib/flatpak/app/*/current/active/files/share/icons"
        ;;
esac

# --- count icon files per candidate (with a timeout guard for slow mounts) --
count_icons() {
    if command -v timeout >/dev/null 2>&1; then
        timeout 20 find "$1" -type f \( -name '*.png' -o -name '*.svg' -o -name '*.ico' \
            -o -name '*.icns' -o -name '*.xpm' \) 2>/dev/null | wc -l
    else
        find "$1" -type f \( -name '*.png' -o -name '*.svg' -o -name '*.ico' \
            -o -name '*.icns' -o -name '*.xpm' \) 2>/dev/null | wc -l
    fi
}

FOUND=()
for c in "${CANDS[@]:-}"; do
    [ -n "$c" ] || continue
    # candidates covered by an excluded root (e.g. the installer's default
    # scan path) are not offered as "additional" folders
    EXCLUDED=false
    for x in "${EXCLUDES[@]}"; do
        [ -n "$x" ] || continue
        case "$c" in "$x"/*|"$x") EXCLUDED=true; break ;;
        esac
    done
    $EXCLUDED && continue
    # fold nested candidates into their parent: skip a path that is inside an
    # already-collected candidate. Guard on array length: "${FOUND[@]:-}"
    # expands to a single empty element on the first pass, and "$f"/* then
    # matches every absolute path as "/*".
    if [ "${#FOUND[@]}" -gt 0 ]; then
        NESTED=false
        for f in "${FOUND[@]}"; do
            case "$c" in "$f"/*) NESTED=true; break ;; esac
        done
        $NESTED && continue
    fi
    N=$(count_icons "$c")
    [ "$N" -gt 0 ] && FOUND+=("$c|$N")
done

if [ "${#FOUND[@]}" -eq 0 ]; then
    echo "No icon folders found in common locations." >&2
    exit 0
fi

if [ "$MODE" = "list" ]; then
    for e in "${FOUND[@]}"; do
        printf '%s\t%s\n' "${e%%|*}" "${e##*|}"
    done
    exit 0
fi

# --- interactive selection --------------------------------------------------
{
    echo "Icon folders found on this system:"
    i=1
    for e in "${FOUND[@]}"; do
        printf '  %d) %-60s (%s icon files)\n' "$i" "${e%%|*}" "${e##*|}"
        i=$((i + 1))
    done
} >&2

printf "Select numbers to add (space-separated, e.g. 1 2), 'a' for all, or Enter to skip: " >&2
read -r selection

# parse selection
SEL=()
case "$selection" in
    ""|" ") : ;;
    a|A|all|ALL) for e in "${FOUND[@]}"; do SEL+=("${e%%|*}"); done ;;
    *)
        for tok in $selection; do
            case "$tok" in
                *[!0-9]*) echo "  ignoring non-numeric token: $tok" >&2; continue ;;
            esac
            if [ "$tok" -ge 1 ] && [ "$tok" -le "${#FOUND[@]}" ]; then
                P="${FOUND[$((tok - 1))]%%|*}"
                # dedupe repeated picks
                DUP=false
                for s in "${SEL[@]:-}"; do [ "$s" = "$P" ] && DUP=true; done
                $DUP || SEL+=("$P")
            else
                echo "  ignoring out-of-range number: $tok" >&2
            fi
        done
        ;;
esac

for s in "${SEL[@]:-}"; do
    printf '%s\n' "$s"
done

# optional metadata refresh against the install (independent of scan results)
if [ -n "$META_MODE" ]; then
    if [ -f "$META_DIR/icon-meta.sh" ]; then
        bash "$META_DIR/icon-meta.sh" "$META_DIR" --mode "$META_MODE"
    elif [ -f "$(dirname "$0")/icon-meta.sh" ]; then
        bash "$(dirname "$0")/icon-meta.sh" "$META_DIR" --mode "$META_MODE"
    else
        echo "icon-meta.sh not found — install Fengrid first" >&2
        exit 1
    fi
fi
exit 0