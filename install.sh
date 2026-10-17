#!/usr/bin/env bash
#
# install.sh — install & launch the GTK4 Icon Browser
#
# Installs to ~/gtk4-icon-browser/ (or a custom location you choose) and
# symlinks ~/.local/bin/gtk4-icon-browser -> .../index.html
#
# The default location is deliberately NOT hidden: browsers installed via
# Snap or Flatpak are commonly unable to access hidden directories such as
# ~/.local, which would break opening the page or loading its icons.
#
# The script itself never requires elevated privileges. The ONLY step that
# may touch the system with sudo/pkexec is the OPTIONAL icon-theme package
# install, which runs only after you explicitly agree.
#
# Usage: bash install.sh [--no-shell]
#   --no-shell   skip handing off to an interactive shell at the end

set -u

DEFAULT_INSTALL_DIR="$HOME/gtk4-icon-browser"
INSTALL_DIR="$DEFAULT_INSTALL_DIR"
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
# 0. Choose the install location (default: ~/gtk4-icon-browser)
# ----------------------------------------------------------------------------
# Snap/Flatpak-packaged browsers are sandboxed away from hidden directories,
# so the default install lives directly in the home directory. A custom
# location is allowed, but hidden or root-owned destinations get a second,
# explicit confirmation because of the access problems described below.
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
        confirm_risky_location "Hidden directory chosen: $INSTALL_DIR — Snap and Flatpak browsers usually CANNOT access hidden paths, so the browser may fail to open the page or load its icons." || CONFIRMED=false
    fi
    if [ "$CONFIRMED" = true ] && [ "$ROOT_OWNED" = true ]; then
        confirm_risky_location "Root-owned or unwritable location: $INSTALL_DIR — installing here requires elevated privileges, which this script intentionally avoids, so the install would likely fail." || CONFIRMED=false
    fi
    [ "$CONFIRMED" = true ] && break
    info "Pick a different location."
done
ok "Will install to: $INSTALL_DIR"

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
# 3. Install to the chosen location
# ----------------------------------------------------------------------------
info "Installing to $INSTALL_DIR ..."
mkdir -p "$INSTALL_DIR" || die "Cannot create $INSTALL_DIR (permission denied?)"
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

# Local icon tree: the page must be self-contained — Firefox blocks
# cross-directory file:// images, so copy every listed icon under
# icons/<theme>/... next to index.html (relative paths work everywhere).
if [ "$N" -gt 1000 ]; then
    warn "You have $N icon files — copying them all takes a few minutes on large icon sets. Please wait; do not interrupt the install."
fi
info "Copying icon files into $INSTALL_DIR/icons/ ..."
mkdir -p "$INSTALL_DIR/icons"
COPIED=0
while IFS= read -r p; do
    [ -f "$p" ] || continue
    case "$p" in
        */icons/*) rel="${p#*/icons/}" ;;
        *) d="$(dirname "$p")"; rel="$(basename "$d")/$(basename "$p")" ;;
    esac
    mkdir -p "$INSTALL_DIR/icons/$(dirname "$rel")"
    cp -L "$p" "$INSTALL_DIR/icons/$rel" 2>/dev/null && COPIED=$((COPIED + 1))
done < "$INSTALL_DIR/$LIST_FILE"
SIZE=$(du -sh "$INSTALL_DIR/icons" | cut -f1)
ok "$COPIED icons copied to icons/ ($SIZE)"

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
        printf '# gtk4-icon-browser launcher (generated by install.sh)\n'
        printf 'exec xdg-open "%s/index.html"\n' "$INSTALL_DIR"
    } > "$BIN_LINK"
    chmod +x "$BIN_LINK"
}
if [ -f "$BIN_LINK" ] && [ ! -L "$BIN_LINK" ] && grep -q 'generated by install.sh' "$BIN_LINK" 2>/dev/null; then
    write_launcher && ok "Updated $BIN_LINK launcher -> $INSTALL_DIR"
elif [ -L "$BIN_LINK" ]; then
    TARGET="$(readlink "$BIN_LINK")"
    case "$TARGET" in
        "$INSTALL_DIR/index.html"|"$HOME/.local/share/gtk4-icon-browser/index.html")
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

# Retired location: installs before the Snap/Flatpak fix lived in a hidden
# directory. Offer to clean it up once the new install is verified in place.
OLD_DIR="$HOME/.local/share/gtk4-icon-browser"
if [ "$INSTALL_DIR" != "$OLD_DIR" ] && [ -f "$OLD_DIR/index.html" ] && [ -f "$OLD_DIR/$LIST_FILE" ]; then
    printf "Found an older install at %s. Remove it? [y/N]: " "$OLD_DIR"
    read -r answer
    case "$answer" in
        [yY]|[yY][eE][sS]) rm -rf "$OLD_DIR" && ok "Removed $OLD_DIR" ;;
        *) info "Kept $OLD_DIR (remove manually if unwanted)" ;;
    esac
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
