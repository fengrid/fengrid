#!/usr/bin/env bash
#
# install.sh — install & launch the GTK4 Icon Browser
#
# Installs to ~/.local/share/gtk4-icon-browser/ and symlinks
# ~/.local/bin/gtk4-icon-browser -> .../index.html
#
# The script itself never requires elevated privileges. The ONLY step that
# may touch the system with sudo/pkexec is the OPTIONAL icon-theme package
# install, which runs only after you explicitly agree.
#
# Usage: bash install.sh [--no-shell]
#   --no-shell   skip handing off to an interactive shell at the end

set -u

INSTALL_DIR="$HOME/.local/share/gtk4-icon-browser"
BIN_DIR="$HOME/.local/bin"
BIN_LINK="$BIN_DIR/gtk4-icon-browser"
LIST_FILE="list.txt"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

CYAN='\033[0;36m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; OFF='\033[0m'
info()  { printf "${CYAN}::${OFF} %s\n" "$*"; }
ok()    { printf "${GREEN}::${OFF} %s\n" "$*"; }
warn()  { printf "${YELLOW}::${OFF} %s\n" "$*"; }
die()   { printf "${RED}::${OFF} %s\n" "$*" >&2; exit 1; }

NO_SHELL=false
[ "${1:-}" = "--no-shell" ] && NO_SHELL=true

# ----------------------------------------------------------------------------
# 1. Icon theme discovery
# ----------------------------------------------------------------------------
# NOTE: the original spec's find is unparenthesized:
#   find ... -name '*.png' -o -name '*.svg' -o -name '*.xpm'
# which parses as (png AND (-o svg)) OR xpm due to operator precedence and
# silently matches unintended files. We use the correct grouped form.
ICON_FIND() { find "$1" -type f \( -name '*.png' -o -name '*.svg' -o -name '*.xpm' \) 2>/dev/null; }

CUSTOM_PATHS=()

have_icons() {
    local n
    n=$(ICON_FIND /usr/share/icons | head -n 1)
    [ -n "$n" ]
}

if have_icons; then
    ok "Icon themes found in /usr/share/icons"
    # Ask about additional/alternative paths
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
    warn "No icon themes found under /usr/share/icons"
    printf "Install GTK icon themes with your package manager, or point me at a custom path.\n"
    printf "  [1] Install icon themes (uses sudo/pkexec — your call)\n"
    printf "  [2] Scan a custom path instead\n"
    printf "  [3] Abort\n"
    printf "Choice: "
    read -r choice
    case "$choice" in
        1)
            # Elevated privileges are used ONLY here, with explicit consent.
            PKG=""
            for c in apt-get dnf pacman zypper apk; do
                command -v "$c" >/dev/null 2>&1 && { PKG="$c"; break; }
            done
            [ -z "$PKG" ] && die "No supported package manager found (apt/dnf/pacman/zypper/apk)."
            case "$PKG" in
                apt-get) PKGS="adwaita-icon-theme hicolor-icon-theme" ;;
                dnf)     PKGS="adwaita-icon-theme hicolor-icon-theme" ;;
                pacman)  PKGS="adwaita-icon-theme hicolor-icon-theme" ;;
                zypper)  PKGS="adwaita-icon-theme hicolor-icon-theme" ;;
                apk)     PKGS="adwaita-icon-theme hicolor-icon-theme" ;;
            esac
            printf "This will run: sudo %s install %s\nProceed? [y/N]: " "$PKG" "$PKGS"
            read -r answer
            case "$answer" in
                [yY]|[yY][eE][sS])
                    sudo "$PKG" install $PKGS || die "Package install failed."
                    have_icons || die "Packages installed but /usr/share/icons is still empty."
                    ok "Icon themes installed"
                    ;;
                *) die "Declined package install. Run install.sh again to pick a custom path instead." ;;
            esac
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
# 2. Generate list.txt
# ----------------------------------------------------------------------------
info "Generating $LIST_FILE ..."
ICON_FIND /usr/share/icons > "$LIST_FILE"
for p in "${CUSTOM_PATHS[@]:-}"; do
    [ -n "$p" ] && ICON_FIND "$p" >> "$LIST_FILE"
done
N=$(wc -l < "$LIST_FILE")
[ "$N" -eq 0 ] && die "list.txt is empty — no icons found in any scanned path."
ok "$LIST_FILE written ($N icon files)"

# ----------------------------------------------------------------------------
# 3. Install to ~/.local/share/gtk4-icon-browser/
# ----------------------------------------------------------------------------
info "Installing to $INSTALL_DIR ..."
mkdir -p "$INSTALL_DIR"
cp "$SCRIPT_DIR/index.html" "$INSTALL_DIR/index.html" || die "Failed to copy index.html."
cp -r "$SCRIPT_DIR/fonts" "$INSTALL_DIR/fonts" || die "Failed to copy fonts/."
cp "$LIST_FILE" "$INSTALL_DIR/$LIST_FILE" || die "Failed to copy list.txt."
# list.js mirrors list.txt as a JS array: browsers block fetch() on file://,
# so the HTML page loads this <script src> fallback when opened directly.
{
    printf 'window.ICON_LIST=['
    sed 's/^[[:space:]]*//; s/["\\]/\\&/g; s/^/"/; s/$/",/' "$INSTALL_DIR/$LIST_FILE" | tr -d '\n' | sed 's/,$//'
    printf '];\n'
} > "$INSTALL_DIR/list.js"
ok "Installed index.html + list.txt + list.js"

# ----------------------------------------------------------------------------
# 4. Ensure ~/.local/bin exists, is on PATH, and holds the symlink
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
                for f in "$HOME/.bashrc" "$HOME/.zshrc"; do
                    [ -f "$f" ] && grep -q "$BIN_DIR" "$f" 2>/dev/null && { RC="$f"; break; }
                done
                if [ -n "$RC" ]; then
                    ok "$BIN_DIR already referenced in $RC"
                else
                    RC="${HOME}/.bashrc"
                    [ -f "$HOME/.zshrc" ] && [ "${SHELL##*/}" = "zsh" ] && RC="$HOME/.zshrc"
                    printf '\n# GTK4 icon browser\nexport PATH="%s:$PATH"\n' "$BIN_DIR" >> "$RC"
                    ok "Added to $RC (takes effect in new shells)"
                fi
                ;;
        esac
        ;;
esac

# Symlink the launcher
if [ -L "$BIN_LINK" ]; then
    TARGET="$(readlink "$BIN_LINK")"
    if [ "$TARGET" = "$INSTALL_DIR/index.html" ]; then
        ok "$BIN_LINK symlink already correct"
    else
        warn "$BIN_LINK exists but points to $TARGET"
        printf "Replace it? [y/N]: "
        read -r answer
        case "$answer" in
            [yY]|[yY][eE][sS]) ln -sfn "$INSTALL_DIR/index.html" "$BIN_LINK" && ok "Symlink updated" ;;
            *) warn "Leaving existing symlink in place" ;;
        esac
    fi
elif [ -e "$BIN_LINK" ]; then
    warn "$BIN_LINK exists and is not a symlink — not touching it."
    warn "Use it directly: open $INSTALL_DIR/index.html"
else
    ln -s "$INSTALL_DIR/index.html" "$BIN_LINK" && ok "Created $BIN_LINK -> $INSTALL_DIR/index.html"
fi

# ----------------------------------------------------------------------------
# 5. Launch and verify
# ----------------------------------------------------------------------------
info "Launching gtk4-icon-browser ..."
LAUNCHED=false
if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$INSTALL_DIR/index.html" >/dev/null 2>&1 && LAUNCHED=true
fi
if [ "$LAUNCHED" = false ]; then
    for b in firefox firefox-esr chromium chromium-browser google-chrome brave epiphany; do
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
    die "Failed to launch: no xdg-open or known browser found. Open $INSTALL_DIR/index.html manually."
fi

ok "Done. Quick launch any time:  gtk4-icon-browser"

# ----------------------------------------------------------------------------
# 6. Hand off to an interactive shell (spec: `exec ${SHELL} && gtk4-icon-browser`)
# ----------------------------------------------------------------------------
if [ "$NO_SHELL" = false ] && [ -t 0 ]; then
    info "Dropping you into an interactive shell (Ctrl-D to exit)"
    exec "${SHELL:-/bin/bash}"
fi
