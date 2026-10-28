# TODO — v1.0.0-rc1-testing

Low-priority follow-ups that do not warrant their own GitHub issue.
Tracked under GitHub issue «TODO for v1.0.0-rc1-testing».

## UI polish
- [x] Settings → Source control: unify button labels and widths
      ("Apply & push" label renders as "Apply_push" via qsTr; keep the
      ampersand from mnemonic parsing). — literal-string button label
- [x] Colors.qml SwTool backgrounds use hardcoded `#40000000`/
      `#25000000` overlays — moved to theme tokens (`scrim` /
      `scrim_soft`, theme-aware for light-theme parity).
- [x] ~~SideRail collapsible sections: persist `sectOpen` per session
      in prefs~~ — superseded by user decision: sections start
      collapsed each launch and reset on restart.
- [x] Fonts pane empty state: hint that Types/Families sections
      appear after the first font scan.
- [x] "1:0" layout-ratio chip in Code pane is cryptic — tooltip added
      ("Cursor position — line : column").
- [x] Editor placeholder contrast (Code pane) is low in dark theme —
      `ink_faint` lightened to #7E8B96 (4.87:1 on the editor surface).

## Code pane / preview
- [x] Debounce `updateMarkdown`/`refreshHighlight` (PERF-3) — 150 ms
      Timer landed.
- [ ] `[[ ref ]]` completion: slash-menu entries for slugs/GUIDs when
      typing `[[` in the snippet editor (currently the syntax is
      documented only in ISSUES/docs).

## Source control (follow-ups on top of the git feature)
- [x] Stash command — real `git stash` support landed (stash list,
      restore, three-way close prompt, commit e12d4d6).
- [ ] Library (library_view) repos: the bridge supports kind:"library"
      but no UI attaches library views to repos yet.
- [ ] Guided rebase UI: conflict file list is a toast; consider a
      dedicated dialog with per-file actions.
- [ ] Worktrees UI: `core.projects_git.add_worktree` exists with no QML
      entry point.

## REST API
- [ ] Webhooks/long-poll for data-asset updates (sensors currently poll
      `GET /points`); revisit after v1.0.
- [x] openapi.yaml: /assets/data, /links, /lookup paths documented.

## Housekeeping
- [x] `--dialog sc` QA affordance — `--dialog settings-sc` opens the
      Source-control category directly.
- [x] `defusedxml` pinned in pyproject (and SEC-4 fixed fail-secure).
- [x] CHANGELOG: ISSUES.md highlights folded into the Unreleased
      entry (Security / Performance / Accessibility).
