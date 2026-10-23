# ADR-0002 — Editor / IDE binding strategy (flexible parity)

- **Status:** accepted (2026-10-19)
- **Supersedes:** the implicit "full IDE-binding parity at v1" assumption in
  the rewrite plan
- **Driver:** user decision — "IDE-binding parity is flexible, just document
  the details"

## 1. Background

The 0.x Code pane (`code.html`) carries an emacs + vim keybinding layer over
its textareas (VIM toggle button / Ctrl+Alt+V) on top of the standard
copy/paste/undo surface. The rewrite plan originally assumed the Qt editor
would reproduce that layer at parity in v1.

## 2. Decision

Binding parity is explicitly **flexible**, not a v1 exit criterion:

- M0–M1 ship Qt-standard editing bindings only: standard text-editing keys,
  `Escape` to close/clear, `/` and Ctrl+F to focus search, shortcut-driven
  rescan and theme toggle. No vim/emacs emulation layer.
- The 0.x vim/emacs layer stays available in the legacy Code pane until the
  Qt editor replaces it (M3 of ADR-0001).
- When the Qt Code pane lands (M3, Qt WebEngine), the 0.x keybinding JS can
  be reused inside the embedded surface as-is; if the editor is instead a
  native `QPlainTextEdit`, parity arrives as a keymap *preset* setting
  (default / emacs / vim) rather than a hard-coded layer.

## 3. Parity contract (what "flexible" means)

| Capability            | 0.x                    | Qt v1 (M0–M1)   | Planned            |
|-----------------------|------------------------|-----------------|--------------------|
| Standard editing keys | yes                    | yes             | yes                |
| Regex syntax highlight| yes (highlighter only) | out of scope    | M3                 |
| vim modal editing     | toggle (Ctrl+Alt+V)    | no              | optional preset    |
| emacs bindings        | layer                  | no              | optional preset    |
| Custom keymaps        | no                     | no              | settings entry if requested |

## 4. Notes

- The 0.x binding layer is presentation-level only; it never touched the
  SQLite snippet store, so deferring it carries no data-migration risk.
- If a preset system is added, persist it through the settings table
  (`settings.set(con, "editor", "keymap")`) rather than QML state, so it
  survives restarts exactly like the theme preference does.
