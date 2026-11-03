#!/usr/bin/env bash
# Comprehensive UI screenshot suite for the final visual inspection (#87):
# every pane and every dialog in both themes, plus the first-run screen
# and the light theme. Output: $FENGRID_SHOT_DIR (default /tmp/fengrid-shots)
#
# Env: FENGRID_SHOT_DIR — output dir. Uses the QA data dir with seeded
# content so panes are populated.
set -u
cd "$(dirname "$0")/.."   # qt/
PY=".venv/bin/python"
OUT="${FENGRID_SHOT_DIR:-/tmp/fengrid-shots}"
DATA="/tmp/fengrid-qa-base"
DELAY="${FENGRID_QA_DELAY:-1200}"
mkdir -p "$OUT"

shot() {
    local name="$1"; shift
    local theme="${1:-dark}"; shift
    QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software XDG_DATA_HOME="$DATA" \
        "$PY" -m fengrid --screenshot "$OUT/$name.png" --theme "$theme" \
        --shot-delay "$DELAY" --no-scan "$@" >"$OUT/$name.log" 2>&1
    if [ -s "$OUT/$name.png" ]; then
        echo "ok  $name"
    else
        echo "ERR $name"; tail -3 "$OUT/$name.log"
    fi
}

# --- panes (both themes) ---
for p in 0 1 2 3 4; do
    shot "pane-$p" dark --pane "$p"
    shot "pane-$p-light" light --pane "$p"
done

# --- dialogs ---
for d in libDialog smartDialog renameDialog subDialog fieldDialog \
         settings settings-general settings-storage settings-import \
         settings-sc menu storage commandBar paletteSettings splash; do
    shot "dlg-$d" dark --dialog "$d"
done

# --- first-run screen ---
shot "dlg-firstRun" dark --dialog firstRun
shot "dlg-firstRun-light" light --dialog firstRun

# --- fonts CSS export dialog (the browse button) ---
shot "dlg-fonts-css" dark --dialog fonts-css
shot "dlg-fonts-css-light" light --dialog fonts-css

# --- presets dialog ---
shot "dlg-presets" dark --dialog presets

# --- entity inspector tabs ---
shot "dlg-entity" dark --dialog entity
shot "dlg-entity-license" dark --dialog entity-license
shot "dlg-entity-sources" dark --dialog entity-sources

# --- inspector with a selected asset ---
shot "inspector-icon" dark --pane 0 --qa-select mark

# --- selected font with inspector ---
shot "inspector-font" dark --pane 1 --qa-select cantarell

# --- terminal designer on colors pane ---
shot "pane-2-terminal" dark --pane 2 --term

echo "done -> $OUT"
