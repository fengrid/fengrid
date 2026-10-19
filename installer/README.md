# Windows installer (NSIS)

`fengrid.nsi` builds `fengrid-win64-setup.exe` — a single-file Windows
installer with a configuration GUI, built with [NSIS](https://nsis.sourceforge.io).
The installer never needs admin rights (user-profile paths, HKCU registry
only).

## What the installer asks

The configuration page (after the welcome/license pages) collects:

1. **Portable install** — when checked, everything is written to a folder
   next to the installer (`<installer drive>\fengrid` by default) with no
   registry entries, no PATH changes and no Start Menu shortcuts. The
   generated `fengrid.cmd` launcher resolves its own location via `%~dp0`,
   so the folder can be moved or copied to a thumbdrive and launched from
   any drive letter. A portable install has no Add/Remove-Programs entry —
   delete the folder to remove it.
2. **Add launcher to PATH** (standard installs only) — adds
   `%USERPROFILE%\.local\bin` to the user PATH (HKCU, `REG_EXPAND_SZ`,
   broadcast applied) and creates a Start Menu shortcut.
3. **Icon folders to scan** — an editable list (`Add folder…` /
   `Remove selected`) of folders containing `.png` / `.svg` / `.ico` files.
   At least one folder is required.

The install then copies the app (index.html, fonts/, server/), runs
`win-setup-helper.ps1` through Windows PowerShell to generate `list.txt` /
`list.js`, copy the scanned icons into `icons\` (same layout rules and
collision suffixes as `install.ps1`), and write the `fengrid.cmd` launcher.
The launcher starts the local web server (`server\serve.py`, loopback
bind, port 8642) and opens `http://127.0.0.1:8642/`, reusing a server that
is already up; `fengrid --file` opens the plain file, and machines without
Python degrade to the plain file automatically.

Standard installs register an uninstaller (`uninstall.exe`, also in
Add/Remove Programs) that stops a running fengrid server, removes the
files, the Start Menu shortcut, the PATH entry (only when the launcher is
ours) and the registry key. Portable installs simply get deleted.

## Building

```bash
bash installer/build.sh        # → dist/fengrid-win64-setup.exe
```

The build reads the app version from `APP_VERSION` in `index.html` and
passes it to makensis as `APPVER`.

### makensis on each platform

| Platform   | Install                                            |
|------------|----------------------------------------------------|
| Debian/Ubuntu | `sudo apt-get install nsis`                     |
| Windows    | `choco install nsis` or the nsis.sf.net installer  |
| macOS      | `brew install makensis`                            |

NSIS 3.x required (Unicode installer). Cross-compiling from Linux/macOS is
fully supported by NSIS — the built `.exe` is a Windows binary either way.

### CI

`.github/workflows/build-windows.yml` builds the installer on
`windows-latest` (Chocolatey NSIS) and uploads
`dist/fengrid-win64-setup.exe` as a workflow artifact.

## Files

| File | Purpose |
|------|---------|
| `fengrid.nsi` | installer script (NSIS, MUI2 + two custom nsDialogs pages) |
| `win-setup-helper.ps1` | install-time scan (list.txt/list.js/icons/launcher) and uninstall helper (stop server, PATH cleanup) — PowerShell 5.1-compatible |
| `fengrid.svg` / `fengrid.ico` | installer icon, generated from the app favicon |
| `build.sh` | version-aware build wrapper |

## Notes & limitations

- The `.exe` stub is 32-bit by NSIS design; it runs on and installs to
  x64 Windows (fengrid itself is bitness-independent static files — hence
  the `win64` artifact name reflecting the target platform).
- All user-typed/generated text files are written by PowerShell as UTF-8
  (no BOM) — NSIS `FileWrite` is ANSI and would mangle non-ASCII paths.
- PowerShell is used at install time because every Windows since 7 ships
  it; Python is only needed at *runtime* for the web server (optional —
  without it the launcher falls back to the plain file).
- Only the compile step is verified on non-Windows hosts; the GUI flow is
  exercised on Windows (see `.github/workflows/build-windows.yml`).
