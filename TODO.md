# TODO — v1.0.0-rc1-testing

Low-priority follow-ups that do not warrant their own GitHub issue.
Tracked under GitHub issue «TODO for v1.0.0-rc1-testing».

## UI polish
- [ ] Settings → Source control: unify button labels and widths
      ("Apply & push" label renders as "Apply_push" via qsTr; keep the
      ampersand from mnemonic parsing).
- [ ] Colors.qml SwTool backgrounds use hardcoded `#40000000`/
      `#25000000` overlays — move to theme tokens for light-theme parity.
- [ ] SideRail collapsible sections: persist `sectOpen` per session in
      prefs so users do not re-expand every launch.
- [ ] Fonts pane empty state: add a hint that Types/Families sections
      appear after the first font scan.
- [ ] "1:0" layout-ratio chip in Code pane is cryptic — add a tooltip.
- [ ] Editor placeholder contrast (Code pane) is low in dark theme.

## Code pane / preview
- [ ] Debounce `updateMarkdown`/`refreshHighlight` (see PERF-3 issue) —
      quick win: a 150 ms Timer is ~10 lines.
- [ ] `[[ ref ]]` completion: slash-menu entries for slugs/GUIDs when
      typing `[[` in the snippet editor (currently the syntax is
      documented only in ISSUES/docs).

## Source control (follow-ups on top of the git feature)
- [ ] Stash command (Main close prompt currently says "stash" but only
      quits — add an actual `git stash` action or reword the text).
- [ ] Library (library_view) repos: the bridge supports kind:"library"
      but no UI attaches library views to repos yet.
- [ ] Guided rebase UI: conflict file list is a toast; consider a
      dedicated dialog with per-file actions.
- [ ] Worktrees UI: `core.projects_git.add_worktree` exists with no QML
      entry point.

## REST API
- [ ] Webhooks/long-poll for data-asset updates (sensors currently poll
      `GET /points`); revisit after v1.0.
- [ ] openapi.yaml: add the new /assets/data, /links, /lookup paths
      (code is routed; spec lags).

## Housekeeping
- [ ] `--dialog sc` QA affordance does not open the Settings category
      directly (use `--dialog settings-sc`).
- [ ] Consider pinning `defusedxml` in requirements once SEC-4 is fixed.
- [ ]CHANGELOG: fold ISSUES.md highlights into the next release entry.
