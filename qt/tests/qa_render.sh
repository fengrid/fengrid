#!/usr/bin/env bash
# Headless QA gate for the Qt shell: unit tests plus offscreen renders of
# both themes; fails loudly on any QML TypeError, QColor assignment failure
# or QThread teardown warning. Run:  qt/tests/qa_render.sh
#
# Env overrides: FENGRID_QA_DATA (data dir with a prepared library.db),
# FENGRID_QA_DELAY (screenshot delay ms).
set -u
cd "$(dirname "$0")/.."   # qt/
PY=".venv/bin/python"
DATA="${FENGRID_QA_DATA:-/tmp/fengrid-qa}"
DELAY="${FENGRID_QA_DELAY:-5000}"
fail=0

echo "== pytest =="
"$PY" -m pytest -q || fail=1

for theme in dark light; do
    log="/tmp/fengrid-qa-$theme.log"
    png="/tmp/fengrid-qa-$theme.png"
    echo "== render($theme) =="
    QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software XDG_DATA_HOME="$DATA" \
        "$PY" -m fengrid --screenshot "$png" --theme "$theme" \
        --shot-delay "$DELAY" >"$log" 2>&1
    if [ ! -s "$png" ]; then
        echo "render($theme): no PNG produced"
        tail -n 5 "$log"
        fail=1
        continue
    fi
    n=$(grep -cE "TypeError|Unable to assign|QThread" "$log" || true)
    if [ "$n" -ne 0 ]; then
        echo "render($theme): $n QML/thread errors:"
        grep -E "TypeError|Unable to assign|QThread" "$log" \
            | sort | uniq -c | sort -rn | head -5
        fail=1
    else
        echo "render($theme): clean -> $png"
    fi
done
exit $fail
