# Quickstart

Get the icon browser running in about two minutes.

## 1. Get it

```bash
git clone https://github.com/nativeit/gtk4-icon-browser.git
cd gtk4-icon-browser
```

## 2. Install

```bash
bash install.sh
```

You'll be asked:

1. **Install location** — press Enter for `~/gtk4-icon-browser/` (a visible
   path on purpose: Snap/Flatpak browsers can't read hidden directories like
   `~/.local`). Or type any custom path; hidden or root-owned paths get a
   second confirmation.
2. **Extra icon paths to scan** — Enter to skip; you probably want the
   default `/usr/share/icons`.
3. **PATH update** — allowed, if `~/.local/bin` isn't already on your PATH.

Then it copies the icons next to the page (a few minutes on very large icon
sets) and tries to open it in your browser.

## 3. Use it

- Launch any time with `gtk4-icon-browser` (or open
  `~/gtk4-icon-browser/index.html` directly).
- Type `/` to search; hover any icon for its details; click the corner
  button on a card to copy the icon's name.
- The **SIZE** slider snaps to standard icon sizes. Theme chips filter by
  icon theme; **CONTEXT** narrows by icon context (actions, status, …).

## Preferences are remembered

Theme (light/dark), preview size, sort order, and the selected theme chip
are stored in your browser's `localStorage` and restored on the next visit.

## Uninstall

```bash
bash install.sh --uninstall    # or: --remove
```

Asks per location before deleting; removes the launcher only if it created
it; optionally strips the PATH entry it added. Directories that don't look
like an install are refused.

## Headless / remote machines

There's no browser to launch there — open
`~/gtk4-icon-browser/index.html` by any other means, or serve it:

```bash
cd ~/gtk4-icon-browser && python3 -m http.server 8642
```

Then visit `http://<host>:8642/`.
