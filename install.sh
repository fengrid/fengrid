#!/usr/bin/env bash
#
# install.sh — install & launch the Icon Browser (Linux and macOS)
#
# Installs to ~/icon-browser/ (or a custom location you choose) and places
# a launcher at ~/.local/bin/icon-browser that opens the real install path
# (see the launcher note below for why it is not a symlink).
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
#   --no-shell            skip handing off to an interactive shell at the end
#   --uninstall, --remove remove installs, launcher, and (on request) the
#                         PATH entry; asks before deleting anything
#   --automatic-updates   enable the weekly update check without prompting
#                         (installs ~/.local/bin/icon-browser-update and a
#                         marked crontab entry; the interactive install also
#                         offers this as a step)

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
DEFAULT_INSTALL_DIR="$HOME/icon-browser"
INSTALL_DIR="$DEFAULT_INSTALL_DIR"
BIN_DIR="$HOME/.local/bin"
BIN_LINK="$BIN_DIR/icon-browser"
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
for arg in "$@"; do
    case "$arg" in
        --no-shell)           NO_SHELL=true ;;
        --uninstall|--remove) UNINSTALL=true ;;
        --automatic-updates)  AUTO_UPDATES=true ;;
        *) die "Unknown option: $arg (supported: --uninstall/--remove, --automatic-updates, --no-shell)" ;;
    esac
done

# ----------------------------------------------------------------------------
# Uninstaller (--uninstall / --remove)
# ----------------------------------------------------------------------------
# Removes each recognized install location after per-directory confirmation,
# the launcher if it is ours, and optionally the PATH entry it added.
run_uninstall() {
    info "Icon Browser uninstaller"
    local CANDIDATES=() c answer T
    [ -d "$DEFAULT_INSTALL_DIR" ] && CANDIDATES+=("$DEFAULT_INSTALL_DIR")
    # retired locations from earlier releases
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

    if [ "${#CANDIDATES[@]}" -eq 0 ]; then
        ok "Nothing found to remove."
        return 0
    fi

    for c in "${CANDIDATES[@]}"; do
        if [ "$c" = "$SCRIPT_DIR" ]; then
            warn "$c is the repository this script runs from — skipped (remove it manually if you really want it gone)."
            continue
        fi
        if [ ! -f "$c/index.html" ] || [ ! -f "$c/$LIST_FILE" ]; then
            warn "$c does not look like an Icon Browser install (missing index.html/list.txt) — skipped for safety."
            continue
        fi
        printf "Remove %s (%s)? [y/N]: " "$c" "$(du -sh "$c" 2>/dev/null | cut -f1)"
        read -r answer
        case "$answer" in
            [yY]|[yY][eE][sS]) rm -rf "$c" && ok "Removed $c" ;;
            *) info "Kept $c" ;;
        esac
    done

    # Launcher — remove only what this script created.
    if [ -L "$BIN_LINK" ]; then
        T="$(readlink "$BIN_LINK")"
        case "$T" in
            */icon-browser/index.html|*/gtk4-icon-browser/index.html)
                rm -f "$BIN_LINK" && ok "Removed launcher symlink $BIN_LINK (pointed at $T)" ;;
            *) warn "$BIN_LINK is a symlink to $T — not ours, left in place." ;;
        esac
    elif [ -f "$BIN_LINK" ] && grep -q 'generated by install.sh' "$BIN_LINK" 2>/dev/null; then
        rm -f "$BIN_LINK" && ok "Removed launcher $BIN_LINK"
    elif [ -e "$BIN_LINK" ]; then
        warn "$BIN_LINK exists and is not our launcher — left in place."
    fi

    # PATH cleanup — recognizes both current and legacy marker comments.
    local RC
    for RC in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.zprofile"; do
        [ -f "$RC" ] || continue
        grep -Eq '^# (Icon Browser|GTK4 icon browser)$' "$RC" 2>/dev/null || continue
        printf "Remove the PATH entry install.sh added to %s? [y/N]: " "$RC"
        read -r answer
        case "$answer" in
            [yY]|[yY][eE][sS])
                sed -i '/^# Icon Browser$/,+1d; /^# GTK4 icon browser$/,+1d' "$RC"
                ok "Removed PATH entry from $RC (takes effect in new shells)" ;;
            *) info "Kept PATH entry in $RC" ;;
        esac
    done

    # automatic-update cron job — remove the marked entry and the updater
    # whenever either the marker or the updater appears in crontab
    if command -v crontab >/dev/null 2>&1 && crontab -l 2>/dev/null | grep -q 'icon-browser-update'; then
        printf "Remove the weekly auto-update cron job? [y/N]: "
        read -r answer
        case "$answer" in
            [yY]|[yY][eE][sS])
                crontab -l 2>/dev/null | grep -v '^# icon-browser weekly update$' \
                    | grep -vF 'icon-browser-update' | crontab -
                ok "Removed weekly auto-update job from crontab" ;;
            *) info "Kept auto-update cron job" ;;
        esac
    fi
    [ -e "$BIN_DIR/icon-browser-update" ] && rm -f "$BIN_DIR/icon-browser-update"

    ok "Uninstall complete."
}

if [ "$UNINSTALL" = true ]; then
    run_uninstall
    exit 0
fi

# ----------------------------------------------------------------------------
# 0. Choose the install location (default: ~/icon-browser)
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
cp "$SCRIPT_DIR/index.html" "$INSTALL_DIR/index.html" || die "Failed to copy index.html."
cp -r "$SCRIPT_DIR/fonts" "$INSTALL_DIR/fonts" || die "Failed to copy fonts/."
cp -r "$SCRIPT_DIR/server" "$INSTALL_DIR/server" || die "Failed to copy server/."
cp "$LIST_FILE" "$INSTALL_DIR/$LIST_FILE" || die "Failed to copy list.txt."
ok "Installed index.html + list.txt + fonts/ + server/"

# ----------------------------------------------------------------------------
# 3b. Local icon tree (self-contained previews)
# ----------------------------------------------------------------------------
# Firefox blocks cross-directory file:// images, so every icon is copied
# under icons/<theme>/... next to index.html; relative paths work in every
# browser and over http. macOS .icns files are converted to .png with the
# built-in `sips`; Linux .xpm files are converted with ImageMagick when
# available. list.txt entries for converted files are rewritten to the
# converted .png so the page's relative paths match exactly.
if [ "$N" -gt 1000 ]; then
    warn "You have $N icon files — copying them all takes a few minutes on large icon sets. Please wait; do not interrupt the install."
fi
info "Copying icon files into $INSTALL_DIR/icons/ ..."
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
            cp -L "$p" "$dest" 2>/dev/null || continue
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
            *)      cp -L "$p" "$INSTALL_DIR/icons/$rel" 2>/dev/null ;;
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
mv "$INSTALL_DIR/$LIST_FILE.new" "$INSTALL_DIR/$LIST_FILE"
SIZE=$(du -sh "$INSTALL_DIR/icons" | cut -f1)
ok "$COPIED icon files prepared in icons/ ($SIZE)"

# regenerate list.js from the (possibly rewritten) list
{
    printf 'window.ICON_LIST=['
    sed 's/^[[:space:]]*//; s/["\\]/\\&/g; s/^/"/; s/$/",/' "$INSTALL_DIR/$LIST_FILE" | tr -d '\n' | sed 's/,$//'
    printf '];\n'
} > "$INSTALL_DIR/list.js"

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
                    printf '\n# Icon Browser\nexport PATH="%s:$PATH"\n' "$BIN_DIR" >> "$RC"
                    ok "Added to $RC (takes effect in new shells)"
                fi
                ;;
        esac
        ;;
esac

# Launcher: a tiny script rather than a symlink to the HTML. Browsers keep
# the symlink's own URL, so page-relative assets (the copied icons/ tree,
# list.js) would resolve under ~/.local/bin/ and fail to load. The script
# opens the real, visible install path instead.
write_launcher() {
    # If BIN_LINK is a symlink, `> "$BIN_LINK"` would write THROUGH it into
    # the target — remove the link itself first. Only ever called on paths
    # already identified as ours.
    rm -f "$BIN_LINK"
    {
        printf '#!/usr/bin/env bash\n'
        printf '# icon-browser launcher (generated by install.sh)\n'
        if [ "$PLATFORM" = macos ]; then
            printf 'exec open "%s/index.html"\n' "$INSTALL_DIR"
        else
            printf 'exec xdg-open "%s/index.html"\n' "$INSTALL_DIR"
        fi
    } > "$BIN_LINK"
    chmod +x "$BIN_LINK"
}
if [ -f "$BIN_LINK" ] && [ ! -L "$BIN_LINK" ] && grep -q 'generated by install.sh' "$BIN_LINK" 2>/dev/null; then
    write_launcher && ok "Updated $BIN_LINK launcher -> $INSTALL_DIR"
elif [ -L "$BIN_LINK" ]; then
    TARGET="$(readlink "$BIN_LINK")"
    case "$TARGET" in
        */icon-browser/index.html|*/gtk4-icon-browser/index.html)
            write_launcher && ok "Replaced symlink with launcher script -> $INSTALL_DIR/index.html"
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
    write_launcher && ok "Created $BIN_LINK -> opens $INSTALL_DIR/index.html"
fi

# ----------------------------------------------------------------------------
# 5. Optional: share on the local network (QR code for phones)
# ----------------------------------------------------------------------------
printf "Serve the showcase on your local network (QR code for phones)? [y/N]: "
read -r answer
case "$answer" in
    [yY]|[yY][eE][sS])
        if command -v python3 >/dev/null 2>&1; then
            ( cd "$INSTALL_DIR/server" && nohup python3 serve.py --port 8642 >/dev/null 2>&1 & )
            sleep 1
            LANIP=$(python3 -c "import socket;s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.connect(('203.0.113.1',80));print(s.getsockname()[0])" 2>/dev/null || echo "127.0.0.1")
            ok "Webshare running — open http://$LANIP:8642/_connect and scan the QR with a phone."
            ok "Stop it later with:  pkill -f 'serve.py --port 8642'"
        else
            warn "python3 not found — install it, then run:  cd $INSTALL_DIR/server && python3 serve.py"
        fi
        ;;
    *) info "Skipping webshare (start later: cd $INSTALL_DIR/server && python3 serve.py)" ;;
esac

# ----------------------------------------------------------------------------
# 5b. Automatic weekly updates (also available via --automatic-updates)
# ----------------------------------------------------------------------------
# Installs update.sh as ~/.local/bin/icon-browser-update, records the install
# dir + icon roots in ~/.local/state/icon-browser/update.conf, and registers
# a marked cron entry (weekly). --uninstall removes both.
setup_automatic_updates() {
    if [ ! -f "$SCRIPT_DIR/update.sh" ]; then
        warn "update.sh missing from the repository — skipping automatic updates"
        return 1
    fi
    local CONF_DIR="$HOME/.local/state/icon-browser"
    mkdir -p "$CONF_DIR" "$BIN_DIR"
    cp "$SCRIPT_DIR/update.sh" "$BIN_DIR/icon-browser-update" && chmod +x "$BIN_DIR/icon-browser-update" \
        || { warn "Could not install the updater"; return 1; }
    SP="$DEFAULT_SCAN_PATH"
    for p in "${CUSTOM_PATHS[@]:-}"; do [ -n "$p" ] && SP="$SP $p"; done
    printf 'INSTALL_DIR="%s"\nSCAN_PATHS="%s"\n' "$INSTALL_DIR" "$SP" > "$CONF_DIR/update.conf"
    ok "Updater installed: $BIN_DIR/icon-browser-update (config: $CONF_DIR/update.conf)"
    if ! command -v crontab >/dev/null 2>&1; then
        warn "crontab not available — run the updater manually:  icon-browser-update"
        return 1
    fi
    if crontab -l 2>/dev/null | grep -q '^# icon-browser weekly update$'; then
        ok "Weekly auto-update cron job already present"
        return 0
    fi
    ( crontab -l 2>/dev/null; \
      printf '# icon-browser weekly update\n17 4 * * 1 %s/icon-browser-update --quiet >> "%s/.local/state/icon-browser/update.log" 2>&1\n' "$BIN_DIR" "$HOME" ) | crontab -
    ok "Weekly auto-update enabled (cron: Mondays 04:17 — checks GitHub releases, applies newer ones)"
}
if [ "$AUTO_UPDATES" = true ]; then
    setup_automatic_updates
else
    printf "Enable automatic weekly updates (weekly release check via cron)? [y/N]: "
    read -r answer
    case "$answer" in
        [yY]|[yY][eE][sS]) setup_automatic_updates ;;
        *) info "Skipping automatic updates (enable later: bash install.sh --automatic-updates, or run icon-browser-update)" ;;
    esac
fi

# ----------------------------------------------------------------------------
# 6. Launch and verify
# ----------------------------------------------------------------------------
info "Launching icon-browser ..."
LAUNCHED=false
if [ "$PLATFORM" = macos ]; then
    command -v open >/dev/null 2>&1 && { open "$INSTALL_DIR/index.html" >/dev/null 2>&1 && LAUNCHED=true; }
else
    command -v xdg-open >/dev/null 2>&1 && { xdg-open "$INSTALL_DIR/index.html" >/dev/null 2>&1 && LAUNCHED=true; }
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
    if pgrep -f "index.html" >/dev/null 2>&1; then
        ok "Icon browser launched — look for a new browser window/tab"
    else
        warn "Could not confirm the browser process; open manually:"
        warn "  $BIN_LINK   (or)   $INSTALL_DIR/index.html"
    fi
else
    die "Failed to launch: no opener or known browser found. Open $INSTALL_DIR/index.html manually."
fi

ok "Done. Quick launch any time:  icon-browser"

# ----------------------------------------------------------------------------
# 7. Hand off to an interactive shell
# ----------------------------------------------------------------------------
if [ "$NO_SHELL" = false ] && [ -t 0 ]; then
    info "Dropping you into an interactive shell (Ctrl-D to exit)"
    exec "${SHELL:-/bin/bash}"
fi