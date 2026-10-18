#!/usr/bin/env bash
#
# update.sh — check GitHub for a newer Icon Browser release and apply it.
#
# Designed to run unattended from cron (the installer can register a weekly
# job with --automatic-updates); also safe to run by hand.
#
# What it does:
#   1. reads the current APP_VERSION from the installed index.html
#   2. asks the repo for the newest git tag (git ls-remote — no API, no rate
#      limits, no credentials)
#   3. if a newer release tag exists: downloads its source tarball, replaces
#      the application files (index.html, fonts/, server/) in the install
#      directory, and re-scans the configured icon paths to refresh
#      list.txt/list.js/icons — user data (the icon list and its scan
#      config) is preserved from ~/.local/state/icon-browser/update.conf
#
# Tracks release tags on `main` only — a dev build (version like
# v0.1.0-dev) is never "updated" backwards to an older release.
#
# Usage: update.sh [--check] [--force] [--quiet] [--dir <install dir>]
#   --check    report only, do not install
#   --force    apply the latest release even if not newer
#   --quiet    no stdout (cron default behaviour is silent; all output also
#              goes to ~/.local/state/icon-browser/update.log)
#   Exit codes: 0 = ok/current, 1 = failure, 2 = update applied

set -u

REPO_BASE="https://github.com/nativeit/gtk4-icon-browser"
STATE_DIR="${ICON_BROWSER_STATE_DIR:-$HOME/.local/state/icon-browser}"
LOG="$STATE_DIR/update.log"
CONF="$STATE_DIR/update.conf"
INSTALL_DIR="${ICON_BROWSER_DIR:-$HOME/icon-browser}"
PLATFORM="$(uname -s | tr '[:upper:]' '[:lower:]')"
case "$PLATFORM" in linux*|darwin*) ;; *) PLATFORM=linux ;; esac

CHECK=false; FORCE=false; QUIET=false
while [ $# -gt 0 ]; do
    case "$1" in
        --check) CHECK=true ;;
        --force) FORCE=true ;;
        --quiet) QUIET=true ;;
        --dir)   INSTALL_DIR="$2"; shift ;;
        *) echo "unknown option: $1" >&2; exit 1 ;;
    esac
    shift
done

mkdir -p "$STATE_DIR"

log()  { printf '%s :: %s\n' "$(date '+%F %T')" "$*" >> "$LOG"; }
say()  { $QUIET || printf '%s\n' "$*"; }
fail() { log "ERROR: $*"; say "update failed: $*" >&2; exit 1; }

[ -f "$INSTALL_DIR/index.html" ] || fail "no install found at $INSTALL_DIR"
[ -x "$(command -v curl 2>/dev/null)" ] || command -v wget >/dev/null 2>&1 || fail "neither curl nor wget available"

current=$(sed -n "s/.*APP_VERSION = '\([^']*\)'.*/\1/p" "$INSTALL_DIR/index.html" | head -1)
[ -n "$current" ] || fail "could not read APP_VERSION from $INSTALL_DIR/index.html"

fetch() { # fetch <url> <outfile>
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL --max-time 60 "$1" -o "$2"
    else
        wget -q -T 60 "$1" -O "$2"
    fi
}

latest=$(git ls-remote --tags "$REPO_BASE.git" 'refs/tags/v*' 2>/dev/null \
    | awk '{print $2}' | sed 's|refs/tags/||' | grep -v '\^{}$' \
    | sort -V | tail -1)
[ -n "$latest" ] && command -v git >/dev/null 2>&1 || fail "no network/git, or no tags found"
log "check: current=$current latest=$latest"

newer_than_current=$(printf '%s\n%s\n' "$latest" "$current" | sort -V | tail -1)
is_newer=false
[ "$latest" != "$current" ] && [ "$newer_than_current" = "$latest" ] && is_newer=true

if [ "$FORCE" != true ]; then
    if [ "$latest" = "$current" ]; then
        log "up to date ($current)"; say "already up to date ($current)"; exit 0
    fi
    if [ "$is_newer" != true ]; then
        log "local ($current) is newer than latest release ($latest) — skipping (dev build?)"
        [ "$QUIET" = false ] && printf 'local %s is newer than latest release %s — skipping.\n' "$current" "$latest"
        exit 0
    fi
fi

if [ "$CHECK" = true ]; then
    log "check-only: update available $latest"; say "update available: $latest (run without --check to apply)"; exit 0
fi

say "updating: $current -> $latest"

# --- download & apply -------------------------------------------------------
TMP=$(mktemp -d) || fail "mktemp failed"
trap 'rm -rf "$TMP"' EXIT
fetch "$REPO_BASE/archive/$latest.tar.gz" "$TMP/src.tar.gz" || fail "download failed"
tar -xzf "$TMP/src.tar.gz" -C "$TMP" || fail "extract failed"
SRC=$(find "$TMP" -maxdepth 1 -type d -name 'gtk4-icon-browser-*' | head -1)
[ -n "$SRC" ] || fail "unexpected tarball layout"

cp "$SRC/index.html" "$INSTALL_DIR/index.html" || fail "copy index.html failed"
[ -d "$SRC/fonts" ] && rm -rf "$INSTALL_DIR/fonts" && cp -r "$SRC/fonts" "$INSTALL_DIR/fonts"
[ -d "$SRC/server" ] && rm -rf "$INSTALL_DIR/server" && cp -r "$SRC/server" "$INSTALL_DIR/server"

# --- refresh the icon list with the user's configured scan paths ------------
if [ -f "$CONF" ]; then
    # shellcheck disable=SC1090
    . "$CONF"
    [ -n "${SCAN_PATHS:-}" ] || SCAN_PATHS="/usr/share/icons /System/Library/CoreServices/CoreTypes.bundle/Contents/Resources"
    LIST="$INSTALL_DIR/list.txt"
    : > "$LIST"
    for p in $SCAN_PATHS; do
        [ -d "$p" ] && find "$p" -type f \( -name '*.png' -o -name '*.svg' -o -name '*.icns' -o -name '*.xpm' \) >> "$LIST"
    done
    N=$(wc -l < "$LIST")
    if [ "$N" -eq 0 ]; then
        log "warning: icon refresh found 0 files, list untouched"
        echo "window.ICON_LIST=[];" > "$INSTALL_DIR/list.js"
    else
        CONVERT_CMD=""
        command -v magick >/dev/null 2>&1 && CONVERT_CMD=magick
        command -v convert >/dev/null 2>&1 && [ -z "$CONVERT_CMD" ] && CONVERT_CMD=convert
        : > "$LIST.new"
        mkdir -p "$INSTALL_DIR/icons"
        while IFS= read -r p; do
            [ -f "$p" ] || continue
            case "$p" in
                */icons/*) rel="${p#*/icons/}" ;;
                *) d="$(dirname "$p")"; rel="$(basename "$d")/$(basename "$p")" ;;
            esac
            case "$p" in
                *.icns)
                    command -v sips >/dev/null 2>&1 || continue
                    rel="${rel%.*}.png"; dest="$INSTALL_DIR/icons/$rel"
                    mkdir -p "$(dirname "$dest")"
                    sips -s format png --resampleHeight 256 "$p" --out "$dest" >/dev/null 2>&1 || continue
                    echo "$INSTALL_DIR/icons/$rel"
                    ;;
                *.xpm)
                    [ -n "$CONVERT_CMD" ] || continue
                    rel="${rel%.*}.png"; dest="$INSTALL_DIR/icons/$rel"
                    mkdir -p "$(dirname "$dest")"
                    "$CONVERT_CMD" "$p" "$dest" >/dev/null 2>&1 || continue
                    echo "$INSTALL_DIR/icons/$rel"
                    ;;
                *)
                    dest="$INSTALL_DIR/icons/$rel"
                    mkdir -p "$(dirname "$dest")"
                    cp -L "$p" "$dest" 2>/dev/null || continue
                    echo "$p"
                    ;;
            esac
        done < "$LIST" > "$LIST.new"
        mv "$LIST.new" "$LIST"
        # keep icons the user dropped into icons/ (refresh-icons.sh merges
        # them in and regenerates list.js); fall back to a plain regeneration
        REFRESH=""
        [ -x "$HOME/.local/bin/icon-browser-refresh" ] && REFRESH="$HOME/.local/bin/icon-browser-refresh"
        if [ -n "$REFRESH" ]; then
            "$REFRESH" --merge-list "$LIST" --dir "$INSTALL_DIR" --quiet || true
            log "refreshed $N icons from configured paths (manual icons/ additions merged)"
        else
            {
                printf 'window.ICON_LIST=['
                sed 's/^[[:space:]]*//; s/["\\]/\\&/g; s/^/"/; s/$/",/' "$LIST" | tr -d '\n' | sed 's/,$//'
                printf '];\n'
            } > "$INSTALL_DIR/list.js"
            log "refreshed $N icons from configured paths"
        fi
    fi
else
    log "no update.conf — kept existing list.txt/list.js/icons"
fi

log "updated $current -> $latest"
say "updated: $current -> $latest"
exit 2