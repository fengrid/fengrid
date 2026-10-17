# GTK4 Icon Browser

[![Release](https://img.shields.io/badge/release-v0.0.1-e8925a)](https://github.com/nativeit/gtk4-icon-browser/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-2a313b)](LICENSE.md)

A single-file, dependency-free showcase for the GTK icon themes installed on
your machine. Point it at a list of icon paths, get a filterable, searchable,
size-adjustable grid of every icon you have — with one-click copy of each
icon's name.

![GTK4 Icon Browser screenshot](docs/assets/screenshot.png)

## Why

Icon themes are documented poorly. When you're writing an app or a custom
theme, you mostly want to answer: *what's installed, what does it look like,
and what is it called?* This answers that with a plain HTML page — no build
step, no runtime, no server required.

## Features

- **Grid of every installed icon** — previews grouped by theme, with size
  variants deduplicated and the best variant chosen for each preview size
- **Size slider** — snaps to standard icon sizes (16 / 22 / 24 / 32 / 48 /
  64 / 96 / 128 / 256)
- **Search, filter, sort** — by name, theme (chips with counts), context
  (`actions`, `devices`, `status`, …), and name/theme/context ordering
- **Hover inspector** — name, theme, context, all available size variants,
  formats, and the full file path
- **Copy button on every card** — copies the icon's name (filename minus
  extension), plus a `/` keyboard shortcut to jump to search
- **Light & dark modes** — persisted between visits
- **Fully self-contained** — self-hosted subset fonts, no CDN, no JS
  framework; one HTML file plus its data

## Install

```bash
git clone https://github.com/nativeit/gtk4-icon-browser.git
cd gtk4-icon-browser
bash install.sh
```

The installer asks before doing anything irreversible, never needs `sudo`
for itself, installs to a visible `~/gtk4-icon-browser/` (Snap/Flatpak
browsers can't read hidden paths), places a launcher at
`~/.local/bin/gtk4-icon-browser`, and warns before copying very large icon
sets. Custom scan paths and custom install locations are supported — hidden
or root-owned destinations get an extra confirmation.

Uninstall any time:

```bash
bash install.sh --uninstall   # alias: --remove
```

See [QUICKSTART.md](QUICKSTART.md) for the two-minute version.

## Documentation

| Doc | Contents |
|-----|----------|
| [QUICKSTART.md](QUICKSTART.md) | install, launch, uninstall — the short path |
| [DEVELOPMENT.md](DEVELOPMENT.md) | project structure, technical details, versioning |
| [LICENSE.md](LICENSE.md) | MIT license + bundled font licenses |

## Status

This is a casual side project: it does what it says, and there's no real
plan to grow it beyond that. That said, contributions are welcome — see
[DEVELOPMENT.md](DEVELOPMENT.md) for how the project is organized.

## License

[MIT](LICENSE.md) — Native IT © 2026. Bundled fonts are licensed
separately (SIL OFL 1.1 / MIT) — see [LICENSE.md](LICENSE.md).
