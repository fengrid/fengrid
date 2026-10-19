#!/usr/bin/env bash
#
# install.sh — install & launch the Fengrid (Linux and macOS)
#
# Installs to ~/fengrid/ (or a custom location you choose) and places
# a launcher at ~/.local/bin/fengrid that starts the install's local web
# server (loopback) and opens http://127.0.0.1:8642/ — the default way to
# use fengrid. `fengrid --file` opens the plain file instead.
#
# Also available: install.ps1 (Windows PowerShell).
#
# The default location is NOT hidden: browsers installed via Snap, Flatpak
# or similar packaging are commonly unable to access hidden directories
# such as ~/.local, which would break opening the page or loading icons.
#
# The script itself never requires elevated privileges. The ONLY step that
# may touch the system with sudo/pkexec is the OPTIONAL icon-theme package
# install (Linux), which runs only after you explicitly agree.
#
# Usage: bash install.sh [--no-shell] [--uninstall] [--automatic-updates]
#                        [--update-metadata enabled|disabled|force]
#                        [--icons copy|link|hardlink]
#                        [--webshare|--no-webshare]
#   --no-shell            skip handing off to an interactive shell at the end
#   --uninstall, --remove remove installs, launcher, and (on request) the
#                         PATH entry; asks before deleting anything
#   --automatic-updates   enable the weekly update check without prompting
#                         (installs ~/.local/bin/fengrid-update and a
#                         marked crontab entry; the interactive install also
#                         offers this as a step)
#   --icons <mode>        how icon files get into icons/: copy (default,
#                         self-contained), link (per-file symlinks to the
#                         originals — saves disk, auto-reflects edits),
#                         hardlink (same fs only, fallback to copy)
#   --webshare            expose the showcase on the LAN (QR share) without
#                         prompting — also the default answer to the prompt
#   --no-webshare         keep the server local-only, skip the prompt
#   --update-metadata <mode>
#                         icon metadata handling (meta.js): enabled (default —
#                         on install every icon is new, so all are identified;
#                         later runs only identify changed files), disabled
#                         (skip metadata entirely), force (re-identify
#                         everything, e.g. after an ImageMagick upgrade).
#                         The chosen mode is recorded for the weekly updater.

set -u

# ----------------------------------------------------------------------------
# Platform detection (Linux / macOS; Windows uses install.ps1)
# ----------------------------------------------------------------------------
OS="$(uname -s)"
case "$OS" in
    Linux*) PLATFORM=linux ;;
    Darwin) PLATFORM=macos ;;
    *) echo "This platform ($OS) is not handled by install.sh — on Windows, use install.ps1." >&2; exit 1 ;;
esac

if [ "$PLATFORM" = macos ]; then
    DEFAULT_SCAN_PATH="/System/Library/CoreServices/CoreTypes.bundle/Contents/Resources"
else
    DEFAULT_SCAN_PATH="/usr/share/icons"
fi
DEFAULT_INSTALL_DIR="$HOME/fengrid"
INSTALL_DIR="$DEFAULT_INSTALL_DIR"
BIN_DIR="$HOME/.local/bin"
BIN_LINK="$BIN_DIR/fengrid"
LIST_FILE="list.txt"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

CYAN='\033[0;36m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; OFF='\033[0m'
info()  { printf "${CYAN}::${OFF} %s\n" "$*"; }
ok()    { printf "${GREEN}::${OFF} %s\n" "$*"; }
warn()  { printf "${YELLOW}::${OFF} %s\n" "$*"; }
die()   { printf "${RED}::${OFF} %s\n" "$*" >&2; exit 1; }

NO_SHELL=false
UNINSTALL=false
AUTO_UPDATES=false
WEB_SHARE="ask"       # --webshare / --no-webshare; "ask" = prompt, default yes
META_MODE="enabled"   # --update-metadata default: scan for changes on install
ICONS_MODE="copy"     # --icons default: copy (self-contained install)
while [ $# -gt 0 ]; do
    case "$1" in
        --no-shell)           NO_SHELL=true ;;
        --uninstall|--remove) UNINSTALL=true ;;
        --automatic-updates)  AUTO_UPDATES=true ;;
        --webshare)           WEB_SHARE=yes ;;
        --no-webshare)        WEB_SHARE=no ;;
        --icons)
            case "${2:-}" in copy|link|hardlink) ICONS_MODE="$2"; shift ;; esac ;;
        --icons=*)            ICONS_MODE="${1#--icons=}" ;;
        --update-metadata)
            case "${2:-}" in enabled|disabled|force) META_MODE="$2"; shift ;; esac ;;
        --update-metadata=*)  META_MODE="${1#--update-metadata=}" ;;
        *) die "Unknown option: $1 (supported: --uninstall/--remove, --automatic-updates, --no-shell, --icons copy|link|hardlink, --webshare/--no-webshare, --update-metadata [enabled|disabled|force])" ;;
    esac
    shift
done
case "$META_MODE" in enabled|disabled|force) ;; *) META_MODE="enabled" ;; esac
case "$ICONS_MODE" in copy|link|hardlink) ;; *) warn "Unknown --icons '$ICONS_MODE' — using copy"; ICONS_MODE="copy" ;; esac

# ----------------------------------------------------------------------------
# Uninstaller (--uninstall / --remove)
# ----------------------------------------------------------------------------
# Removes each recognized install location after per-directory confirmation,
# the launcher if it is ours, and optionally the PATH entry it added.
# Every action is recorded and echoed back in a final summary, so the
# script's last word is always a clear completion report — not the shell's
# "Terminated" job notification for a stopped web server.
run_uninstall() {
    info "Fengrid uninstaller"
    local CANDIDATES=() c answer T
    local R_DIRS=() K_DIRS=() S_DIRS=() R_PATH=() K_PATH=()
    local R_MISC=() K_MISC=() SERVERS_STOPPED=0 SERVERS_LEFT=0
    local LAUNCHER="" CRON="none configured"

    [ -d "$DEFAULT_INSTALL_DIR" ] && CANDIDATES+=("$DEFAULT_INSTALL_DIR")
    # retired locations from earlier releases
    [ -d "$HOME/icon-browser" ] && CANDIDATES+=("$HOME/icon-browser")  # pre-rebrand installs
    [ -d "$HOME/gtk4-icon-browser" ] && CANDIDATES+=("$HOME/gtk4-icon-browser")
    [ -d "$HOME/.local/share/gtk4-icon-browser" ] && CANDIDATES+=("$HOME/.local/share/gtk4-icon-browser")
    printf "Custom install location to remove? (path, or Enter to skip): "
    read -r answer
    case "$answer" in
        "~")   answer="$HOME" ;;
        "~/"*) answer="$HOME/${answer:2}" ;;
    esac
    [ -n "$answer" ] && [ "${answer:0:1}" != "/" ] && answer="$PWD/$answer"
    [ -n "$answer" ] && CANDIDATES+=("${answer%/}")

    # No install dirs? Still sweep launchers/helpers/PATH/cron — a broken or
    # partially-removed install can leave those behind.
    if [ "${#CANDIDATES[@]}" -eq 0 ]; then
        ok "No install directories found — sweeping leftover launchers, helpers, and PATH entries."
    fi

    for c in "${CANDIDATES[@]}"; do
        if [ "$c" = "$SCRIPT_DIR" ]; then
            warn "$c is the repository this script runs from — skipped (remove it manually if you really want it gone)."
            S_DIRS+=("$c (repository — skipped)")
            continue
        fi
        if [ ! -f "$c/index.html" ] || [ ! -f "$c/$LIST_FILE" ]; then
            warn "$c does not look like a Fengrid install (missing index.html/list.txt) — skipped for safety."
            S_DIRS+=("$c (not an install — skipped)")
            continue
        fi
        printf "Remove %s (%s)? [y/N]: " "$c" "$(du -sh "$c" 2>/dev/null | cut -f1)"
        read -r answer
        case "$answer" in
            [yY]|[yY][eE][sS])
                rm -rf "$c" && { ok "Removed $c"; R_DIRS+=("$c"); } ;;
            *) info "Kept $c"; K_DIRS+=("$c") ;;
        esac
    done

    # Launcher(s) — remove only what this script created. Checks the current
    # launcher name and the pre-rebrand `icon-browser` name so older installs
    # are cleaned up too.
    local LNAME L
    for LNAME in fengrid icon-browser gtk4-icon-browser; do
        L="$BIN_DIR/$LNAME"
        if [ -L "$L" ]; then
            T="$(readlink "$L")"
            case "$T" in
                */fengrid/index.html|*/icon-browser/index.html|*/gtk4-icon-browser/index.html)
                    rm -f "$L" && { ok "Removed launcher symlink $L (pointed at $T)"; LAUNCHER="removed symlink ($L)"; R_MISC+=("launcher symlink ($L)"); } ;;
                *) warn "$L is a symlink to $T — not ours, left in place." ;;
            esac
        elif [ -f "$L" ] && grep -q 'generated by install.sh' "$L" 2>/dev/null; then
            rm -f "$L" && { ok "Removed launcher $L"; LAUNCHER="removed ($L)"; R_MISC+=("launcher ($L)"); }
        elif [ -e "$L" ]; then
            warn "$L exists and is not our launcher — left in place."
            [ "$LNAME" = fengrid ] && LAUNCHER="left in place (not ours)"
        fi
    done

    # PATH cleanup — recognizes both current and legacy marker comments.
    local RC
    for RC in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.zprofile"; do
        [ -f "$RC" ] || continue
        grep -Eq '^# (Fengrid|Icon Browser|GTK4 icon browser)$' "$RC" 2>/dev/null || continue
        printf "Remove the PATH entry install.sh added to %s? [y/N]: " "$RC"
        read -r answer
        case "$answer" in
            [yY]|[yY][eE][sS])
                sed -i '/^# Fengrid$/,+1d; /^# Icon Browser$/,+1d; /^# GTK4 icon browser$/,+1d' "$RC"
                ok "Removed PATH entry from $RC (takes effect in new shells)"
                R_PATH+=("$RC") ;;
            *) info "Kept PATH entry in $RC"; K_PATH+=("$RC") ;;
        esac
    done

    # automatic-update cron job — remove the marked entry and the updater
    # whenever either the marker or the updater appears in crontab
    if command -v crontab >/dev/null 2>&1 && crontab -l 2>/dev/null | grep -Eq '(fengrid|icon-browser)-update'; then
        printf "Remove the weekly auto-update cron job? [y/N]: "
        read -r answer
        case "$answer" in
            [yY]|[yY][eE][sS])
                crontab -l 2>/dev/null | grep -vE '^# (fengrid|icon-browser) weekly update$' \
                    | grep -vE '(fengrid|icon-browser)-update' | crontab -
                ok "Removed weekly auto-update job from crontab"
                CRON="removed" ;;
            *) info "Kept auto-update cron job"; CRON="kept" ;;
        esac
    fi
    if [ -e "$BIN_DIR/fengrid-update" ]; then
        rm -f "$BIN_DIR/fengrid-update"
        ok "Removed updater $BIN_DIR/fengrid-update"
        R_MISC+=("updater ($BIN_DIR/fengrid-update)")
    fi
    if [ -e "$BIN_DIR/icon-browser-update" ]; then
        rm -f "$BIN_DIR/icon-browser-update"
        ok "Removed legacy updater $BIN_DIR/icon-browser-update"
        R_MISC+=("legacy updater ($BIN_DIR/icon-browser-update)")
    fi
    if [ -f "$BIN_DIR/fengrid-refresh" ] && grep -q 'refresh-icons.sh' "$BIN_DIR/fengrid-refresh" 2>/dev/null; then
        rm -f "$BIN_DIR/fengrid-refresh" && { ok "Removed $BIN_DIR/fengrid-refresh"; R_MISC+=("refresh helper ($BIN_DIR/fengrid-refresh)"); }
    fi
    if [ -f "$BIN_DIR/icon-browser-refresh" ] && grep -q 'refresh-icons.sh' "$BIN_DIR/icon-browser-refresh" 2>/dev/null; then
        rm -f "$BIN_DIR/icon-browser-refresh" && { ok "Removed legacy helper $BIN_DIR/icon-browser-refresh"; R_MISC+=("legacy refresh helper ($BIN_DIR/icon-browser-refresh)"); }
    fi

    # stop any running web server (serve.py) belonging to an install being
    # removed — it may be a backgrounded launch from install.sh's webshare
    # step, or a manual run. Only instances tied to candidate dirs are killed,
    # so an unrelated serve.py on another port survives.
    if command -v pgrep >/dev/null 2>&1 && [ "${#CANDIDATES[@]}" -gt 0 ]; then
        PIDS=$(pgrep -f 'serve\.py' 2>/dev/null || true)
        for pid in $PIDS; do
            [ "$pid" = "$$" ] && continue
            CMD=$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)
            case "$CMD" in
                *serve.py*) ;;
                *) continue ;;
            esac
            # only real server processes: their command line STARTS with a
            # python interpreter. A shell whose command text merely mentions
            # serve.py (e.g. this very terminal's compound command) must not
            # be matched and killed.
            EXE="${CMD%% *}"
            case "$EXE" in
                *python*) ;;
                *) continue ;;
            esac
            CWD=$(readlink "/proc/$pid/cwd" 2>/dev/null || true)
            # kernel appends " (deleted)" when the dir was removed while the
            # process still runs (uninstall removes the dir, then we get here)
            CWD=${CWD% (deleted)}
            CWD=${CWD%* (deleted)}
            MATCHED=""
            for c in "${CANDIDATES[@]}"; do
                if echo "$CMD" | grep -qF "$c"; then MATCHED="$c"; break; fi
                case "$CWD" in
                    "$c"/*|"$c") MATCHED="$c"; break ;;
                esac
            done
            if [ -n "$MATCHED" ]; then
                if kill "$pid" 2>/dev/null; then
                    # poll briefly so the death is confirmed before the
                    # summary prints (and the shell's "Terminated" job
                    # notification, if any, lands before our last word)
                    local n=0 alive=1
                    while [ "$n" -lt 10 ]; do
                        kill -0 "$pid" 2>/dev/null || { alive=0; break; }
                        sleep 0.2; n=$((n + 1))
                    done
                    if [ "$alive" -eq 0 ]; then
                        ok "Stopped web server for $MATCHED (pid $pid)"
                    else
                        warn "Web server (pid $pid) did not exit within 2s — it may still be running"
                    fi
                    SERVERS_STOPPED=$((SERVERS_STOPPED + 1))
                else
                    warn "Could not stop web server (pid $pid)"
                fi
            else
                info "Web server pid $pid is not from an install being removed — left running"
                SERVERS_LEFT=$((SERVERS_LEFT + 1))
            fi
        done
    else
        info "No running web server instances found (or pgrep unavailable)"
    fi

    # --- final summary: the definitive last word of the uninstall --------
    printf '\n'
    ok "──────────────── Uninstall summary ────────────────"
    if [ "${#R_DIRS[@]}" -gt 0 ]; then
        for c in "${R_DIRS[@]}"; do info "  removed install:      $c"; done
    fi
    if [ "${#K_DIRS[@]}" -gt 0 ]; then
        for c in "${K_DIRS[@]}"; do info "  kept install:         $c (declined)"; done
    fi
    if [ "${#S_DIRS[@]}" -gt 0 ]; then
        for c in "${S_DIRS[@]}"; do info "  skipped:              $c"; done
    fi
    [ -n "$LAUNCHER" ] && info "  launcher:             $LAUNCHER"
    if [ "${#R_PATH[@]}" -gt 0 ]; then
        for c in "${R_PATH[@]}"; do info "  removed PATH entry:   $c"; done
    fi
    if [ "${#K_PATH[@]}" -gt 0 ]; then
        for c in "${K_PATH[@]}"; do info "  kept PATH entry:      $c (declined)"; done
    fi
    info "  auto-update cron job: $CRON"
    if [ "${#R_MISC[@]}" -gt 0 ]; then
        for c in "${R_MISC[@]}"; do info "  removed helper:       $c"; done
    fi
    if [ "$SERVERS_STOPPED" -gt 0 ]; then
        info "  web servers stopped:  $SERVERS_STOPPED"
    fi
    if [ "$SERVERS_LEFT" -gt 0 ]; then
        info "  unrelated web servers left running: $SERVERS_LEFT"
    fi
    ok "───────────────────────────────────────────────────"
    ok "Uninstall completed successfully."
    if [ "$SERVERS_STOPPED" -gt 0 ]; then
        printf "${YELLOW}::${OFF} Note: if your shell printed \"Terminated\", that was its\n"
        printf "${YELLOW}::${OFF} notification for the stopped web server above — not\n"
        printf "${YELLOW}::${OFF} this script exiting early.\n"
    fi
}

if [ "$UNINSTALL" = true ]; then
    run_uninstall
    exit 0
fi

# ----------------------------------------------------------------------------
# 0. Choose the install location (default: ~/fengrid)
# ----------------------------------------------------------------------------
confirm_risky_location() {
    warn "$1"
    printf "Install there anyway? [y/N]: "
    read -r answer
    case "$answer" in
        [yY]|[yY][eE][sS]) return 0 ;;
        *) return 1 ;;
    esac
}

while :; do
    printf "Install location? [Enter = %s, or type a custom path]: " "$DEFAULT_INSTALL_DIR"
    read -r answer
    INSTALL_DIR="${answer:-$DEFAULT_INSTALL_DIR}"
    # Expand a leading ~/ (bare ~ or ~/...; leave ~user alone), absolutize
    # relative paths so the launcher stays valid, strip trailing /. Uses
    # substring ops — a `~` inside an expansion pattern would itself undergo
    # tilde expansion (${s#~/} removes "$HOME/", not "~/") and silently break.
    case "$INSTALL_DIR" in
        "~")   INSTALL_DIR="$HOME" ;;
        "~/"*) INSTALL_DIR="$HOME/${INSTALL_DIR:2}" ;;
    esac
    [ "${INSTALL_DIR:0:1}" != "/" ] && INSTALL_DIR="$PWD/$INSTALL_DIR"
    INSTALL_DIR="${INSTALL_DIR%/}"
    [ -z "$INSTALL_DIR" ] && INSTALL_DIR="/"

    # Hidden? Any dot-prefixed component anywhere in the path.
    HIDDEN=false
    REST="$INSTALL_DIR"
    while [ -n "$REST" ]; do
        COMPONENT="${REST%%/*}"
        case "$COMPONENT" in
            .*) HIDDEN=true; break ;;
        esac
        [ "$REST" = "${REST#*/}" ] && REST="" || REST="${REST#*/}"
    done

    # Root-owned/unwritable? Inspect the directory, or its nearest existing
    # ancestor, WITHOUT creating anything — a declined location must not
    # leave stray directories behind.
    ROOT_OWNED=false
    CHECK_DIR="$INSTALL_DIR"
    while [ ! -e "$CHECK_DIR" ] && [ "$CHECK_DIR" != "/" ]; do
        CHECK_DIR="$(dirname "$CHECK_DIR")"
    done
    if [ ! -w "$CHECK_DIR" ]; then
        ROOT_OWNED=true
    else
        DIR_OWNER="$(stat -c '%U' "$CHECK_DIR" 2>/dev/null || stat -f '%Su' "$CHECK_DIR" 2>/dev/null)"
        [ "$DIR_OWNER" = "root" ] && [ "$(id -u)" -ne 0 ] && ROOT_OWNED=true
    fi

    CONFIRMED=true
    if [ "$HIDDEN" = true ]; then
        confirm_risky_location "Hidden directory chosen: $INSTALL_DIR — Snap, Flatpak and other sandboxed browsers usually CANNOT access hidden paths, so the browser may fail to open the page or load its icons." || CONFIRMED=false
    fi
    if [ "$CONFIRMED" = true ] && [ "$ROOT_OWNED" = true ]; then
        confirm_risky_location "Root-owned or unwritable location: $INSTALL_DIR — installing here requires elevated privileges, which this script intentionally avoids, so the install would likely fail." || CONFIRMED=false
    fi
    [ "$CONFIRMED" = true ] && break
    info "Pick a different location."
done
ok "Will install to: $INSTALL_DIR"

# ----------------------------------------------------------------------------
# 1. Icon source discovery (any theme, any folder)
# ----------------------------------------------------------------------------
# NOTE: the find invocations use parenthesized -name groups; the
# unparenthesized form parses wrongly due to -o precedence.
if [ "$PLATFORM" = macos ]; then
    # .icns files are converted to .png in the copy step (built-in `sips`)
    ICON_FIND() { find "$1" -type f \( -name '*.png' -o -name '*.svg' -o -name '*.icns' \) 2>/dev/null; }
    CONVERT_CMD=""
else
    ICON_FIND() { find "$1" -type f \( -name '*.png' -o -name '*.svg' -o -name '*.xpm' \) 2>/dev/null; }
    # .xpm needs an image converter to be previewable in a browser
    CONVERT_CMD=""
    for c in magick convert; do
        command -v "$c" >/dev/null 2>&1 && { CONVERT_CMD="$c"; break; }
    done
fi

CUSTOM_PATHS=()

have_icons() {
    local n
    n=$(ICON_FIND "$DEFAULT_SCAN_PATH" | head -n 1)
    [ -n "$n" ]
}

if have_icons; then
    ok "Icon source found at $DEFAULT_SCAN_PATH"
    printf "Add more icon folders to scan?\n"
    printf "  [1] Scan common system locations and pick (recommended)\n"
    printf "  [2] Enter paths manually\n"
    printf "  [Enter] Skip — the default source is enough\n"
    printf "Choice: "
    read -r choice
    case "$choice" in
        1)
            if [ -f "$SCRIPT_DIR/scan-icons.sh" ]; then
                # scanner: menu on stderr, selected paths on stdout; the
                # default scan root is excluded (already scanned)
                while IFS= read -r p; do
                    [ -n "$p" ] || continue
                    CUSTOM_PATHS+=("$p")
                    ok "Will scan: $p"
                done < <(bash "$SCRIPT_DIR/scan-icons.sh" --pick --exclude "$DEFAULT_SCAN_PATH")
                [ "${#CUSTOM_PATHS[@]}" -gt 0 ] || info "No additional folders selected"
            else
                warn "scan-icons.sh not found — enter paths manually instead"
                while true; do
                    printf "Add an additional icon path to scan? (path, or Enter to skip): "
                    read -r answer
                    [ -z "$answer" ] && break
                    if [ -d "$answer" ]; then
                        CUSTOM_PATHS+=("$answer")
                        ok "Will scan: $answer"
                    else
                        warn "Not a directory: $answer — skipped"
                    fi
                done
            fi
            ;;
        2)
            while true; do
                printf "Add an additional icon path to scan? (path, or Enter to skip): "
                read -r answer
                [ -z "$answer" ] && break
                if [ -d "$answer" ]; then
                    CUSTOM_PATHS+=("$answer")
                    ok "Will scan: $answer"
                else
                    warn "Not a directory: $answer — skipped"
                fi
            done
            ;;
        *) info "Skipping additional icon folders" ;;
    esac
else
    warn "No icons found under $DEFAULT_SCAN_PATH"
    printf "Install an icon theme collection with your package manager, or point me at a custom path.\n"
    printf "  [1] Install icon themes (Linux only; uses sudo/pkexec — your call)\n"
    printf "  [2] Scan a custom path instead\n"
    printf "  [3] Abort\n"
    printf "Choice: "
    read -r choice
    case "$choice" in
        1)
            # Elevated privileges are used ONLY here, with explicit consent.
            if [ "$PLATFORM" != linux ]; then
                warn "Package-manager install is only wired up on Linux — scan a custom path instead."
            else
                PKG=""
                for c in apt-get dnf pacman zypper apk; do
                    command -v "$c" >/dev/null 2>&1 && { PKG="$c"; break; }
                done
                [ -z "$PKG" ] && die "No supported package manager found (apt/dnf/pacman/zypper/apk)."
                PKGS="adwaita-icon-theme hicolor-icon-theme"
                printf "This will run: sudo %s install %s\nProceed? [y/N]: " "$PKG" "$PKGS"
                read -r answer
                case "$answer" in
                    [yY]|[yY][eE][sS])
                        sudo "$PKG" install $PKGS || die "Package install failed."
                        have_icons || die "Packages installed but $DEFAULT_SCAN_PATH is still empty."
                        ok "Icon themes installed"
                        ;;
                    *) die "Declined package install. Run install.sh again to pick a custom path instead." ;;
                esac
            fi
            ;;
        2)
            printf "Custom icon path to scan: "
            read -r answer
            [ -d "$answer" ] || die "Not a directory: $answer"
            CUSTOM_PATHS+=("$answer")
            ok "Will scan: $answer"
            ;;
        *) die "Aborted." ;;
    esac
fi

# ----------------------------------------------------------------------------
# 2. Generate list.txt (+ the list.js file:// fallback)
# ----------------------------------------------------------------------------
info "Generating $LIST_FILE ..."
ICON_FIND "$DEFAULT_SCAN_PATH" > "$LIST_FILE"
for p in "${CUSTOM_PATHS[@]:-}"; do
    [ -n "$p" ] && ICON_FIND "$p" >> "$LIST_FILE"
done
# overlapping scan roots can list the same file twice — dedupe in order
awk '!seen[$0]++' "$LIST_FILE" > "$LIST_FILE.tmp" && mv "$LIST_FILE.tmp" "$LIST_FILE"
# Without an image converter, .xpm files cannot be previewed — drop them.
if [ "$PLATFORM" = linux ] && [ -z "$CONVERT_CMD" ] && grep -q '\.xpm$' "$LIST_FILE"; then
    XMPC=$(grep -c '\.xpm$' "$LIST_FILE")
    warn "No ImageMagick found — dropping $XMPC .xpm icons (browsers cannot render XPM)."
    grep -v '\.xpm$' "$LIST_FILE" > "$LIST_FILE.tmp" && mv "$LIST_FILE.tmp" "$LIST_FILE"
fi
N=$(wc -l < "$LIST_FILE")
[ "$N" -eq 0 ] && die "list.txt is empty — no icons found in any scanned path."
ok "$LIST_FILE written ($N icon files)"

# ----------------------------------------------------------------------------
# 3. Install to the chosen location
# ----------------------------------------------------------------------------
info "Installing to $INSTALL_DIR ..."
mkdir -p "$INSTALL_DIR" || die "Cannot create $INSTALL_DIR (permission denied?)"
# NOTE: copy the directory CONTENTS (trailing /.), not the directory itself —
# `cp -r server dest/server` nests a fresh copy under an existing dest/server
# instead of updating the files in place.
mkdir -p "$INSTALL_DIR/fonts" "$INSTALL_DIR/server"
cp "$SCRIPT_DIR/index.html" "$INSTALL_DIR/index.html" || die "Failed to copy index.html."
cp -r "$SCRIPT_DIR/fonts/." "$INSTALL_DIR/fonts/" || die "Failed to copy fonts/."
cp -r "$SCRIPT_DIR/server/." "$INSTALL_DIR/server/" || die "Failed to copy server/."
cp "$SCRIPT_DIR/refresh-icons.sh" "$INSTALL_DIR/refresh-icons.sh" || die "Failed to copy refresh-icons.sh."
cp "$SCRIPT_DIR/icon-meta.sh" "$INSTALL_DIR/icon-meta.sh" || die "Failed to copy icon-meta.sh."
cp "$LIST_FILE" "$INSTALL_DIR/$LIST_FILE" || die "Failed to copy list.txt."
ok "Installed index.html + list.txt + fonts/ + server/ + refresh-icons.sh + icon-meta.sh"

# ----------------------------------------------------------------------------
# 3b. Local icon tree (self-contained previews)
# ----------------------------------------------------------------------------
# Firefox blocks cross-directory file:// images, so every icon must be
# reachable under icons/<theme>/... next to index.html; relative paths work
# in every browser and over http. Three ways to get them there (--icons):
#   copy     plain copies — fully self-contained (default)
#   link     per-file SYMLINKS to the originals — no duplicated disk, edits
#            to the originals show up immediately; uninstall never follows
#            them, so removing the app cannot touch system icon themes
#   hardlink second links to the same inode — no extra disk on the same
#            filesystem, silently falls back to a copy across devices
# macOS .icns files are converted to .png with the built-in `sips`; Linux
# .xpm files are converted with ImageMagick when available — conversions
# are always real files in icons/. list.txt entries for converted files are
# rewritten to the converted .png so the page's relative paths match.
store_file() {  # src dest — places $1 at $2 according to $ICONS_MODE
    case "$ICONS_MODE" in
        link)     ln -sfn "$1" "$2" 2>/dev/null ;;
        hardlink) ln -f "$1" "$2" 2>/dev/null || cp -L "$1" "$2" 2>/dev/null ;;
        *)        cp -L "$1" "$2" 2>/dev/null ;;
    esac
}
if [ "$N" -gt 1000 ] && [ "$ICONS_MODE" = copy ]; then
    warn "You have $N icon files — copying them all takes a few minutes on large icon sets. Please wait; do not interrupt the install."
fi
case "$ICONS_MODE" in
    link)     info "Linking icon files into $INSTALL_DIR/icons/ (symlinks to originals) ..." ;;
    hardlink) info "Hardlinking icon files into $INSTALL_DIR/icons/ ..." ;;
    *)        info "Copying icon files into $INSTALL_DIR/icons/ ..." ;;
esac
mkdir -p "$INSTALL_DIR/icons"
COPIED=0
: > "$INSTALL_DIR/$LIST_FILE.new"
while IFS= read -r p; do
    [ -f "$p" ] || continue
    case "$p" in
        */icons/*) rel="${p#*/icons/}" ;;
        *) d="$(dirname "$p")"; rel="$(basename "$d")/$(basename "$p")" ;;
    esac
    case "$p" in
        *.icns)
            command -v sips >/dev/null 2>&1 || continue
            rel="${rel%.*}.png"
            dest="$INSTALL_DIR/icons/$rel"
            mkdir -p "$(dirname "$dest")"
            sips -s format png --resampleHeight 256 "$p" --out "$dest" >/dev/null 2>&1 || continue
            ;;
        *.xpm)
            [ -n "$CONVERT_CMD" ] || continue
            rel="${rel%.*}.png"
            dest="$INSTALL_DIR/icons/$rel"
            mkdir -p "$(dirname "$dest")"
            "$CONVERT_CMD" "$p" "$dest" >/dev/null 2>&1 || continue
            ;;
        *)
            dest="$INSTALL_DIR/icons/$rel"
            mkdir -p "$(dirname "$dest")"
            store_file "$p" "$dest" || continue
            ;;
    esac
    # collision guard: same rel from different scan roots
    if [ -e "$dest" ] && ! cmp -s "$p" "$dest" 2>/dev/null; then
        i=1
        while [ -e "$INSTALL_DIR/icons/${rel%.*}-$i.${rel##*.}" ]; do i=$((i + 1)); done
        rel="${rel%.*}-$i.${rel##*.}"
        case "$p" in
            *.icns) sips -s format png --resampleHeight 256 "$p" --out "$INSTALL_DIR/icons/$rel" >/dev/null 2>&1 ;;
            *.xpm)  "$CONVERT_CMD" "$p" "$INSTALL_DIR/icons/$rel" >/dev/null 2>&1 ;;
            *)      store_file "$p" "$INSTALL_DIR/icons/$rel" ;;
        esac
    fi
    # the list entry becomes the local png for converted formats, else the
    # original path (its "/icons/"-relative suffix is what the page uses)
    case "$rel" in
        *.png) case "$p" in *.icns|*.xpm) echo "$INSTALL_DIR/icons/$rel" ;; *) echo "$p" ;; esac ;;
        *) echo "$p" ;;
    esac
    COPIED=$((COPIED + 1))
done < "$INSTALL_DIR/$LIST_FILE" > "$INSTALL_DIR/$LIST_FILE.new"
case "$ICONS_MODE" in
    link)     ok "Icon tree linked: $COPIED symlinks under icons/ (targets untouched; removing the install removes only the links)" ;;
    hardlink) ok "Icon tree hardlinked: $COPIED files share inodes with the originals (cross-device entries were copied)" ;;
    *)        ok "Icon tree copied: $COPIED files self-contained under icons/" ;;
esac
mv "$INSTALL_DIR/$LIST_FILE.new" "$INSTALL_DIR/$LIST_FILE"
SIZE=$(du -sh "$INSTALL_DIR/icons" | cut -f1)
ok "$COPIED icon files prepared in icons/ ($SIZE)"

# regenerate list.js from the (possibly rewritten) list
{
    printf 'window.ICON_LIST=['
    sed 's/^[[:space:]]*//; s/["\\]/\\&/g; s/^/"/; s/$/",/' "$INSTALL_DIR/$LIST_FILE" | tr -d '\n' | sed 's/,$//'
    printf '];\n'
} > "$INSTALL_DIR/list.js"

# image metadata (real dimensions, file size, colorspace, mono flag) for the
# inspector's specs, tone filter and color view — best effort, never fatal.
# --update-metadata controls it: enabled (default) identifies only new and
# changed files, disabled skips metadata entirely, force re-identifies all.
if command -v identify >/dev/null 2>&1 || command -v magick >/dev/null 2>&1; then
    if [ "$META_MODE" = disabled ]; then
        info "Skipping image metadata (--update-metadata disabled)."
    else
        info "Inspecting image files for metadata (meta.js, mode: $META_MODE) ..."
        bash "$SCRIPT_DIR/icon-meta.sh" "$INSTALL_DIR" --mode "$META_MODE"
    fi
else
    info "ImageMagick not found — skipping metadata (the page falls back to filename-derived specs). Install imagemagick and re-run install.sh or fengrid-refresh to add richer specs."
fi

# ----------------------------------------------------------------------------
# 4. Ensure ~/.local/bin exists, is on PATH, and holds the launcher
# ----------------------------------------------------------------------------
mkdir -p "$BIN_DIR"

case ":$PATH:" in
    *":$BIN_DIR:"*) ok "$BIN_DIR is already on PATH" ;;
    *)
        warn "$BIN_DIR is not on your PATH"
        printf "Add it to your shell profile? [Y/n]: "
        read -r answer
        case "$answer" in
            [nN]|[nN][oO]) warn "Skipping PATH update — the command won't resolve until you add it manually." ;;
            *)
                RC=""
                for f in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.zprofile"; do
                    [ -f "$f" ] && grep -q "$BIN_DIR" "$f" 2>/dev/null && { RC="$f"; break; }
                done
                if [ -n "$RC" ]; then
                    ok "$BIN_DIR already referenced in $RC"
                else
                    if [ "$PLATFORM" = macos ]; then
                        RC="${HOME}/.zprofile"   # login shells on macOS
                        [ -f "$RC" ] || touch "$RC"
                    else
                        RC="${HOME}/.bashrc"
                        [ -f "$HOME/.zshrc" ] && [ "${SHELL##*/}" = "zsh" ] && RC="$HOME/.zshrc"
                    fi
                    printf '\n# Fengrid\nexport PATH="%s:$PATH"\n' "$BIN_DIR" >> "$RC"
                    ok "Added to $RC (takes effect in new shells)"
                fi
                ;;
        esac
        ;;
esac

# Launcher: a tiny script rather than a symlink to the HTML. Browsers keep
# the symlink's own URL, so page-relative assets (the icons/ tree, list.js)
# would resolve under ~/.local/bin/ and fail to load. The script targets the
# real, visible install path — and by default starts its local web server
# (loopback bind) and opens the http:// address, so refresh, format
# conversion and shared QR webshare all work out of the box.
write_launcher() {
    # If BIN_LINK is a symlink, `> "$BIN_LINK"` would write THROUGH it into
    # the target — remove the link itself first. Only ever called on paths
    # already identified as ours.
    rm -f "$BIN_LINK"
    {
        printf '#!/usr/bin/env bash\n'
        printf '# fengrid launcher (generated by install.sh)\n'
        printf '# Opens fengrid through its local web server so refresh and\n'
        printf '# format conversion always work. `fengrid --file` opens the\n'
        printf '# plain file instead (export is then browser-only, no refresh).\n'
        cat <<'LAUNCHER_BODY'
APP_DIR="@INSTALL_DIR@"
PORT=8642
opener() {
    if [ "$(uname -s)" = Darwin ]; then exec open "$1"; else exec xdg-open "$1"; fi
}
case "$1" in
    --file|--no-server) opener "$APP_DIR/index.html" ;;
esac
if command -v python3 >/dev/null 2>&1; then
    probe() { python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:$PORT/server-state.js', timeout=1)" 2>/dev/null; }
    if probe; then
        # a server is already up on the port (e.g. the LAN webshare) —
        # reuse it instead of restarting, so it keeps serving what it serves
        opener "http://127.0.0.1:$PORT/"
    fi
    mkdir -p "${HOME}/.local/state/fengrid"
    # local-only server (loopback bind, not the LAN webshare); restarts
    # cleanly thanks to --kill-existing, logs to the state dir
    ( cd "$APP_DIR/server" && nohup python3 serve.py \
        --dir "$APP_DIR" --port "$PORT" --host 127.0.0.1 --kill-existing \
        >>"${HOME}/.local/state/fengrid/server.log" 2>&1 & )
    i=0
    while ! probe; do
        i=$((i + 1)); [ "$i" -ge 6 ] && break; sleep 0.5
    done
    if [ "$i" -lt 6 ]; then
        opener "http://127.0.0.1:$PORT/"
    fi
fi
opener "$APP_DIR/index.html"
LAUNCHER_BODY
    } > "$BIN_LINK"
    # bake the real install dir into the heredoc (portable sed/awk; the
    # replacement is escaped for sed's & and \ specials)
    esc=$(printf '%s' "$INSTALL_DIR" | sed 's/[&\\/]/\\&/g')
    awk -v r="$esc" '{ gsub(/@INSTALL_DIR@/, r); print }' "$BIN_LINK" > "$BIN_LINK.tmp" \
        && mv "$BIN_LINK.tmp" "$BIN_LINK"
    chmod +x "$BIN_LINK"
}
if [ -f "$BIN_LINK" ] && [ ! -L "$BIN_LINK" ] && grep -q 'generated by install.sh' "$BIN_LINK" 2>/dev/null; then
    write_launcher && ok "Updated $BIN_LINK launcher -> local server + http://127.0.0.1:8642/"
elif [ -L "$BIN_LINK" ]; then
    TARGET="$(readlink "$BIN_LINK")"
    case "$TARGET" in
        */fengrid/index.html|*/icon-browser/index.html|*/gtk4-icon-browser/index.html)
            write_launcher && ok "Replaced symlink with launcher script -> local server + http://127.0.0.1:8642/"
            ;;
        *)
            warn "$BIN_LINK is a symlink to $TARGET — not ours, not touching it."
            warn "Remove it manually and re-run install.sh to install the launcher."
            ;;
    esac
elif [ -e "$BIN_LINK" ]; then
    warn "$BIN_LINK exists and is not our launcher — not touching it."
    warn "Open $INSTALL_DIR/index.html directly, or remove $BIN_LINK and re-run."
else
    write_launcher && ok "Created $BIN_LINK -> starts the local server and opens http://127.0.0.1:8642/"
fi

# refresh helper — updates list.txt/list.js after manual icon drops into
# icons/ (see refresh-icons.sh); the weekly updater also uses it to keep
# manual additions across re-scans
if [ -f "$SCRIPT_DIR/refresh-icons.sh" ]; then
    cp "$SCRIPT_DIR/refresh-icons.sh" "$BIN_DIR/fengrid-refresh" \
        && chmod +x "$BIN_DIR/fengrid-refresh" \
        && ok "Refresh helper installed: $BIN_DIR/fengrid-refresh"
fi

# ----------------------------------------------------------------------------
# 5. Optional: expose the showcase on the local network (QR code for phones)
# ----------------------------------------------------------------------------
# The showcase itself runs on a local web server by default: the fengrid
# launcher starts serve.py bound to the loopback interface and opens
# http://127.0.0.1:8642/. The opt-in below only EXPOSES that server to the
# local network; a later \`fengrid\` launch reuses whatever is running on
# the port, so no restart is needed.
if [ "$WEB_SHARE" = ask ]; then
    printf "Expose the showcase on your local network (QR code for phones)? [Y/n]: "
    read -r answer
    case "$answer" in
        [nN]|[nN][oO]) WEB_SHARE=no ;;
        *)             WEB_SHARE=yes ;;
    esac
fi
case "$WEB_SHARE" in
    yes)
        if command -v python3 >/dev/null 2>&1; then
            ( cd "$INSTALL_DIR/server" && nohup python3 serve.py --port 8642 >/dev/null 2>&1 & )
            sleep 1
            if python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8642/server-state.js', timeout=2)" 2>/dev/null; then
                LANIP=$(python3 -c "import socket;s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.connect(('203.0.113.1',80));print(s.getsockname()[0])" 2>/dev/null || echo "127.0.0.1")
                ok "LAN webshare running — open http://$LANIP:8642/_connect and scan the QR with a phone."
                ok "Only share on networks you trust; the server is bound to all interfaces."
                ok "Stop it later with:  pkill -f 'serve.py --port 8642'"
            else
                warn "LAN webshare did not come up on port 8642 (busy or blocked) — the launcher's local-only server is unaffected."
            fi
        else
            warn "python3 not found — install it, then run:  cd $INSTALL_DIR/server && python3 serve.py"
        fi
        ;;
    *) info "Keeping the server local-only (LAN share later: cd $INSTALL_DIR/server && python3 serve.py)" ;;
esac

# ----------------------------------------------------------------------------
# 5b. Automatic weekly updates (also available via --automatic-updates)
# ----------------------------------------------------------------------------
# Installs update.sh as ~/.local/bin/fengrid-update, records the install
# dir + icon roots in ~/.local/state/fengrid/update.conf, and registers
# a marked cron entry (weekly). --uninstall removes both.
setup_automatic_updates() {
    if [ ! -f "$SCRIPT_DIR/update.sh" ]; then
        warn "update.sh missing from the repository — skipping automatic updates"
        return 1
    fi
    local CONF_DIR="$HOME/.local/state/fengrid"
    mkdir -p "$CONF_DIR" "$BIN_DIR"
    cp "$SCRIPT_DIR/update.sh" "$BIN_DIR/fengrid-update" && chmod +x "$BIN_DIR/fengrid-update" \
        || { warn "Could not install the updater"; return 1; }
    SP="$DEFAULT_SCAN_PATH"
    for p in "${CUSTOM_PATHS[@]:-}"; do [ -n "$p" ] && SP="$SP $p"; done
    printf 'INSTALL_DIR="%s"\nSCAN_PATHS="%s"\nUPDATE_META_MODE="%s"\n' \
        "$INSTALL_DIR" "$SP" "$META_MODE" > "$CONF_DIR/update.conf"
    ok "Updater installed: $BIN_DIR/fengrid-update (config: $CONF_DIR/update.conf)"
    if ! command -v crontab >/dev/null 2>&1; then
        warn "crontab not available — run the updater manually:  fengrid-update"
        return 1
    fi
    if crontab -l 2>/dev/null | grep -q '^# fengrid weekly update$'; then
        ok "Weekly auto-update cron job already present"
        return 0
    fi
    ( crontab -l 2>/dev/null; \
      printf '# fengrid weekly update\n17 4 * * 1 %s/fengrid-update --quiet >> "%s/.local/state/fengrid/update.log" 2>&1\n' "$BIN_DIR" "$HOME" ) | crontab -
    ok "Weekly auto-update enabled (cron: Mondays 04:17 — checks GitHub releases, applies newer ones)"
}
if [ "$AUTO_UPDATES" = true ]; then
    setup_automatic_updates
else
    printf "Enable automatic weekly updates (weekly release check via cron)? [y/N]: "
    read -r answer
    case "$answer" in
        [yY]|[yY][eE][sS]) setup_automatic_updates ;;
        *) info "Skipping automatic updates (enable later: bash install.sh --automatic-updates, or run fengrid-update)" ;;
    esac
fi

# ----------------------------------------------------------------------------
# 6. Launch and verify
# ----------------------------------------------------------------------------
info "Launching fengrid ..."
LAUNCHED=false
# the launcher starts a local-only server (loopback) and opens the http://
# address, so refresh and format conversion work out of the box
if [ -f "$BIN_LINK" ] && grep -q 'generated by install.sh' "$BIN_LINK" 2>/dev/null; then
    "$BIN_LINK" >/dev/null 2>&1 && LAUNCHED=true
fi
if [ "$LAUNCHED" = false ]; then
    for b in firefox firefox-esr chromium chromium-browser google-chrome brave epiphany safari; do
        if command -v "$b" >/dev/null 2>&1; then
            "$b" "$INSTALL_DIR/index.html" >/dev/null 2>&1 &
            LAUNCHED=true
            break
        fi
    done
fi

if [ "$LAUNCHED" = true ]; then
    sleep 2
    if python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8642/server-state.js', timeout=2)" >/dev/null 2>&1 \
       || pgrep -f "index.html" >/dev/null 2>&1; then
        ok "Fengrid launched at http://127.0.0.1:8642/ — look for a new browser window/tab"
    else
        ok "Fengrid launched — look for a new browser window/tab"
    fi
else
    die "Failed to launch: no opener or known browser found. Open $INSTALL_DIR/index.html manually."
fi

ok "Done. Quick launch any time:  fengrid"

# ----------------------------------------------------------------------------
# 7. Hand off to an interactive shell
# ----------------------------------------------------------------------------
if [ "$NO_SHELL" = false ] && [ -t 0 ]; then
    info "Dropping you into an interactive shell (Ctrl-D to exit)"
    exec "${SHELL:-/bin/bash}"
fi