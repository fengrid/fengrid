# Quickstart

Get fengrid running in about two minutes — on Linux, macOS or
Windows.

## 1. Get it

```bash
git clone https://github.com/fengrid/fengrid.git
cd fengrid
```

## 2. Install

**Linux / macOS**

```bash
bash install.sh
```

**Windows (PowerShell)**

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1
```

You'll be asked:

1. **Install location** — press Enter for `~/fengrid/` (a visible path
   on purpose: sandboxed browsers like Snap/Flatpak packages can't read
   hidden directories like `~/.local`). Or type any custom path; hidden or
   root-owned paths get a second confirmation.
2. **Icon folders to scan** — Linux/macOS default to your system theme
   directories (`/usr/share/icons`, macOS CoreTypes); add any extra folders
   you keep icons in. On Windows you pick the folders (`.png`, `.svg`,
   `.ico`).
3. **PATH update** — allowed, if the launcher folder isn't already on PATH.
4. **LAN webshare** — default **yes** (exposes the showcase to your local
   network for QR sharing; answer `n` or rerun with `--no-webshare` to keep
   it local-only).
5. **Font folders** — default **yes**: scans `~/.local/share/fonts`,
   `~/.fonts`, and `/usr/share/fonts` for the font showcase (answer `n`
   or rerun with `--no-fonts` to skip; add custom font folders when
   prompted).

Then it copies the icons next to the page (a few minutes on very large icon
sets — macOS converts `.icns` with the built-in `sips`) and opens it in your
browser. To avoid the copies entirely, add `--icons link` (symlinks to the
originals — no duplicated disk) or `--icons hardlink` (same result on the
same filesystem without symlinks); plain copies remain the default and are
the most portable.

## 3. Use it

- Launch any time with `fengrid`. The launcher starts a **local-only**
  web server (loopback bind — not visible to other machines) and opens
  `http://127.0.0.1:8642/`, so the **refresh button** and **all export
  formats** always work. Prefer the plain file? `fengrid --file` opens
  `~/fengrid/index.html` directly (export is then browser-only for
  sizes/PNG/JPEG/WebP, and refresh needs the CLI).
- Type `/` to search; hover or tap any icon for its details; use the corner
  button on a card to copy the icon's name.
- The **SIZE** slider snaps to standard icon sizes. Chips filter by source
  folder/theme; dropdowns narrow by **CONTEXT**, file **TYPE** (svg/png/…),
  **TONE** (color/monochrome, from generated metadata), **TAGS** and
  **COLL** (collections).
- Hover details show the icon's dimensions, every available size variant,
  file size, colorspace and color count — plus **TAG** (add your own tags).
  The **download button** on each icon preview (top-left, opposite the copy
  button) opens a format/size menu for **EXPORT** (PNG/JPEG/WebP/ICO directly;
  PDF/GIF/TIFF/BMP and the original via "more…" — served over the local web
  server the conversions run through ImageMagick).
- Create your own tags and collections from the **tag button** in the title
  row or the **TAG** button in the details bar; they're saved in your browser
  and the search box matches them too.
- On a phone the layout is fully responsive: chips swipe horizontally,
  tapping a card shows its details, and the search/filter panel starts
  collapsed for a full-page grid — the sliders button in the title row
  expands it, and your choice is remembered.

## Share it on your network (phones & tablets)

The showcase already runs on a local web server — the `fengrid` launcher
starts it bound to the loopback interface. The install enables the LAN
webshare by default (decline with the prompt's `n`, rerun with
`--no-webshare`, or enable later):

```bash
cd ~/fengrid/server && python3 serve.py
```

Then open `http://<your-ip>:8642/_connect` on a desktop browser and scan the
QR with your phone. The showcase makes no cross-origin requests (everything
is served same-origin), so it renders correctly on mobile without any CORS
setup.

## Import icon sets

The **folder-plus button** in the title row imports icon sets four ways,
each landing in its own theme folder under `icons/` and scanned for
metadata automatically:

- **Folder** — pick a folder in your browser (uploaded through the local
  server), or type a server-local path (e.g. a system theme directory).
- **Archive** — select a `.zip` archive; it is unpacked safely and its
  icons are imported.
- **URL / git repo** — paste a URL to a git repository (shallow-cloned) or
  to an archive file (`.zip`, `.tar.gz`, `.tar.xz`, `.7z`, …), or a local
  archive path.
- **Browse sets** — 200+ open-source icon sets from
  [fengrid/icon-sets](https://github.com/fengrid/icon-sets), fetched live
  with license and author shown per set. Importing downloads the set's
  Iconify JSON and renders one SVG file per icon.

The import needs the local web server (the `fengrid` launcher starts it
automatically). SVGs that lack the `xmlns` namespace attribute are fixed
during import so they render correctly in `<img>` tags.

## Font showcase

The header's **Icons / Fonts / Code** switch opens `fonts.html` — the same grid
experience for the typefaces on your machine. Each card renders live
preview text in that font (customizable in the toolbar), with search,
sort by name/weight/style, and style/format filters. Tick checkboxes (or
Shift/Ctrl-click) to select fonts, then **Export CSS** (generates
`@font-face` rules) or **Export ZIP** (packages the font files + CSS +
README). Click a font name for the detail modal — the typeface at
multiple sizes, all installed variants of the same family, a full glyph
specimen, and metadata.

Scan font folders with:

```bash
bash scan-fonts.sh                     # scan the default folders
bash scan-fonts.sh --add ~/my/fonts    # add a folder to the list
bash scan-fonts.sh ~/custom/fonts      # scan a one-off folder
```

Supported: `.ttf`, `.otf`, `.woff`, `.woff2`, `.ttc`, `.eot`. Metadata
comes from `fc-scan` (fontconfig).

## Code playground

The **Code** tab opens `code.html` — a JSFiddle-style pane for writing
and testing snippets. Three tabbed editors (HTML / CSS / JS) with syntax
highlighting sit beside a live **Result** preview: press **Run ▸** or
Ctrl+Enter to render, and **Save** (or Ctrl+S) to store the snippet in a
local SQLite database (`snippets.db`, created on first save). The
sidebar lists saved snippets with search, a language filter,
recent/title/created sorting, and a clickable tag cloud; click a snippet
to reopen it. **Export HTML** downloads the current snippet as a
standalone file.

The editor speaks IDE: emacs-style commands (Ctrl-A/E line home/end,
Ctrl-K kill line, Ctrl-Y yank, Alt-B/F word motion, Ctrl-X Ctrl-S save)
work everywhere, and the **VIM** toggle (or Ctrl+Alt+V) enables modal
editing — motions `h j k l w b e 0 $ gg G`, operators `d c y` with
motions (`dd yy cc dw x D C`), `p P` paste, and `:w` to save, with the
current mode shown in the pane label.

The **Import** button brings snippets in from other tools: VSCode
`.code-snippets` / `.json` files (comments and trailing commas are
fine) and massCode's `db.sqlite`. Both are translated into fengrid's
snippet store — languages map onto the HTML/CSS/JS fields, tags carry
over, and re-importing skips what is already present. Leave the path
empty to scan the editors' default locations, or pick a file to upload.

## Colors

The **Colors** tab opens `colors.html` — a palette generator: five
swatches, a harmony selector (pleasing mix, analogous, complementary,
triadic, monochrome), and the spacebar to roll new colors (locked
swatches stay put). Click a swatch to edit it with HSL sliders or a hex
value; every swatch shows its contrast ratio against white and black
with WCAG badges. **Save palette** stores it in SQLite with a name and
tags; the sidebar lists saved palettes with search, sorting, and a tag
cloud. Exports: CSS custom properties, JSON, and palette board images
(SVG and 2× PNG) — rounded swatch cards with hex codes and
auto-generated color names, ready for READMEs and style guides.

## Projects

The **Projects** tab opens `projects.html` — collect anything the other
panes hold into a coordinated, exportable pack. Create a project, then
pick assets from the Icons / Fonts / Snippets / Palettes tabs (an asset
can live in any number of projects). The spec row tweaks the generated
output — CSS class prefix, icon size, background/ink/accent colors —
and the live preview updates as you type. **Save project** (Ctrl+S)
persists everything; **Export .zip** or **.tar.gz** builds an archive
with the selected files, generated `css/colors.css`, `css/fonts.css`,
`css/icons.css`, `js/icons.js`, a demo `index.html`, `palettes.json`,
`manifest.json`, and a README.

Each pane has its own brand-derived accent — Icons are teal, Fonts are
violet, Code is coral, Colors are rose, Projects are green — while the
lit-pane amber stays the shared interaction accent everywhere.

## Add your own icons

Drop icon files into the `icons/` folder of your install — a subfolder
becomes the theme name (e.g. `icons/MySet/logo.png`). With the default
`--icons copy` install these are ordinary files; with `--icons link` the
existing theme entries are symlinks to the system themes (drop new files
anywhere under `icons/` — new drops are always real files), and
`--icons hardlink` shows hardlinks. Then refresh the list:

```bash
fengrid-refresh          # or: bash ~/fengrid/refresh-icons.sh
```

Loose files in `icons/` itself are filed under a `Manual` theme, and
`.icns`/`.xpm` files are converted to PNG when a converter is available.
Re-running the command also prunes entries for files you've since deleted.
The weekly updater runs the same merge, so manual additions survive updates.

## Refresh & metadata

Metadata (dimensions, file size, colorspace, mono flag) is fingerprinted —
re-scans only re-inspect files that are new or changed. The **refresh
button** in the title row re-scans your `icons/` folder and refreshes
metadata through the web server; **Shift-click** forces a full re-identify.
From the shell, every script takes the same switch:

```bash
fengrid-refresh --update-metadata enabled   # only changed files (default)
fengrid-refresh --update-metadata disabled  # skip metadata entirely
fengrid-refresh --update-metadata force     # re-identify every icon
```

`install.sh` and `scan-icons.sh` accept the same option; installs run it
enabled by default and record the choice for the weekly updater. On large
icon sets the scripts warn before a long run, and Ctrl-C cancels safely —
`meta.js` is only replaced after a complete pass.

## Preferences are remembered

Theme (light/dark), preview size, sort order, and the selected theme chip
are stored in your browser's `localStorage` and restored on the next visit.

## Keep it updated

The installer can enable an automatic **weekly update check** (say yes to the
prompt, or run `bash install.sh --automatic-updates` later). It installs
`~/.local/bin/fengrid-update`, registers a weekly cron job, and logs to
`~/.local/state/fengrid/update.log`. Check manually any time:

```bash
fengrid-update --check    # report only
fengrid-update            # apply a newer release if one exists
```

## Uninstall

```bash
bash install.sh --uninstall                # Linux / macOS (or: --remove)
powershell -File install.ps1 -Uninstall    # Windows
```

Asks per location before deleting; removes the launcher only if it created
it; optionally strips the PATH entry it added. Directories that don't look
like an install are refused. It ends with a summary of everything it
removed, kept, or skipped, and confirms completion — if a running web
server is stopped during uninstall, your shell may print a `Terminated`
line for it; that refers to the server, not the script.