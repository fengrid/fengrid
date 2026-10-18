# Quickstart

Get the icon browser running in about two minutes — on Linux, macOS or
Windows.

## 1. Get it

```bash
git clone https://github.com/nativeit/gtk4-icon-browser.git
cd gtk4-icon-browser
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

1. **Install location** — press Enter for `~/icon-browser/` (a visible path
   on purpose: sandboxed browsers like Snap/Flatpak packages can't read
   hidden directories like `~/.local`). Or type any custom path; hidden or
   root-owned paths get a second confirmation.
2. **Icon folders to scan** — Linux/macOS default to your system theme
   directories (`/usr/share/icons`, macOS CoreTypes); add any extra folders
   you keep icons in. On Windows you pick the folders (`.png`, `.svg`,
   `.ico`).
3. **PATH update** — allowed, if the launcher folder isn't already on PATH.

Then it copies the icons next to the page (a few minutes on very large icon
sets — macOS converts `.icns` with the built-in `sips`) and opens it in your
browser.

## 3. Use it

- Launch any time with `icon-browser` (or open
  `~/icon-browser/index.html` directly).
- Type `/` to search; hover or tap any icon for its details; use the corner
  button on a card to copy the icon's name.
- The **SIZE** slider snaps to standard icon sizes. Chips filter by source
  folder/theme; **CONTEXT** narrows by icon category (actions, status, …).
- On a phone the layout is fully responsive: chips swipe horizontally and
  tapping a card shows its details.

## Share it on your network (phones & tablets)

Say yes to the webshare prompt during install (or start it later):

```bash
cd ~/icon-browser/server && python3 serve.py
```

Then open `http://<your-ip>:8642/_connect` on a desktop browser and scan the
QR with your phone. The showcase makes no cross-origin requests (everything
is served same-origin), so it renders correctly on mobile without any CORS
setup.

## Add your own icons

Drop icon files into the `icons/` folder of your install — a subfolder
becomes the theme name (e.g. `icons/MySet/logo.png`). Then refresh the list:

```bash
icon-browser-refresh          # or: bash ~/icon-browser/refresh-icons.sh
```

Loose files in `icons/` itself are filed under a `Manual` theme, and
`.icns`/`.xpm` files are converted to PNG when a converter is available.
Re-running the command also prunes entries for files you've since deleted.
The weekly updater runs the same merge, so manual additions survive updates.

## Preferences are remembered

Theme (light/dark), preview size, sort order, and the selected theme chip
are stored in your browser's `localStorage` and restored on the next visit.

## Keep it updated

The installer can enable an automatic **weekly update check** (say yes to the
prompt, or run `bash install.sh --automatic-updates` later). It installs
`~/.local/bin/icon-browser-update`, registers a weekly cron job, and logs to
`~/.local/state/icon-browser/update.log`. Check manually any time:

```bash
icon-browser-update --check    # report only
icon-browser-update            # apply a newer release if one exists
```

## Uninstall

```bash
bash install.sh --uninstall                # Linux / macOS (or: --remove)
powershell -File install.ps1 -Uninstall    # Windows
```

Asks per location before deleting; removes the launcher only if it created
it; optionally strips the PATH entry it added. Directories that don't look
like an install are refused.