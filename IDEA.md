Create an HTML-based icon showcase that provides a stylish, modern, and highly functional grid that showcases the locally-installed `gtk4` icons located at the paths listed in `list.txt` (attached). This assumes the user has installed gtk4 themes/icons, the attached text file was generated using the Bash command `find /usr/share/icons -type f -name '*.png' -o -name '*.svg' -o -name '*.xpm' >> list.txt`, which is also used in an associated install script (see below specs) to determine the location/availability of the users' local options.

- Use `list.txt` to generate a dynamic table of icon previews based on the included paths/filenames.
- Be sure the layout is clean, consistent, uses proper padding/margins, maintains readability, and adjusts to various screen dimensions and/or layout options
- Include a slider at the top for increasing/decreasing the size of the icon previews (using standard icon sizes as increments)
- Use the font `Bebas Neue` with all-caps for all large headings. Labels and sub-headings should use the fixed-width font (defined below), but with increased character spacing.
- Use the fixed-width font `Iosevka` (fallback to the default `monospace`, `Roboto Mono` and `Courier New`) for all icon-specific text (names, specs, details, etc.) and buttons/UI elements.
- Use the variable width font `Inter` (fallback to the default `sans-serif`, `Helvetica` and `Arial`) for all paragraph/default text.
- Provide switchable light/dark modes.
- Use colored accents judiciously to improve UI/UX, to highlight important features, or to signify active options.
- Categorize the icons, and provide options for filtering, sorting, and/or searching.
- Allow the user to hover over an icon to see its specs/details. 
- Be sure the icon's name is featured so the user can easily reference it.
- Include a shortcut button in the corner to copy the icon's name to the clipboard (unless otherwise specified, assume the icon's name is the same as its filename without the extension).

## Install script (install.sh)

- Prompt the user for any package installs or permanent changes to their system; `sudo` is not required for the script's own actions (the optional icon-theme package install is the only elevated step, and only on explicit consent).
- Determine if the user has gtk themes/icons installed.
  - If not, prompt the user for either a custom path to scan with `find $CUSTOM_ICON_PATH -type f \( -name '*.png' -o -name '*.svg' -o -name '*.xpm' \) >> list.txt`, or permission to install the gtk themes/icons using their default package manager.
  - If so, ask the user if they would like to supply any additional/alternative paths to scan for icons.
  - Generate the list with `find /usr/share/icons -type f \( -name '*.png' -o -name '*.svg' -o -name '*.xpm' \) > list.txt && find $CUSTOM_ICON_PATH -type f \( -name '*.png' -o -name '*.svg' -o -name '*.xpm' \) >> list.txt` (parenthesized `-name` groups; the unparenthesized form mis-parses).
- Installation location:
  - By default, install to `~/gtk4-icon-browser/` (or `git clone $REPO_URL ~/gtk4-icon-browser`). The default location must NOT be hidden: browsers installed through Snap or Flatpak are commonly sandboxed away from hidden directories such as `~/.local`, and may be unable to open the page or load its icons.
  - Offer a custom install location. If the chosen path is hidden (any dot-prefixed component) or root-owned/unwritable, warn the user about these potential access/permission issues and ask them to confirm again before proceeding.
- Ensure the user's local `bin` directory is included in their $PATH; prompt the user for permission and add it if necessary.
- Install a small launcher script at `~/.local/bin/gtk4-icon-browser` that opens the *real* install path (`exec xdg-open ~/gtk4-icon-browser/index.html`). Do NOT symlink directly to the HTML file: browsers keep the symlink's own URL, so page-relative assets (the copied `icons/` tree, `list.js`) would resolve under `~/.local/bin/` and fail to load.
- Run `exec ${SHELL}` after launching and return an error if the HTML file doesn't launch successfully.
