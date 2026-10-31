#!/usr/bin/env bash
# fengrid runtime diagnostic collector (#61 follow-up)
#
# Collects system info, process/memory snapshots, and app logs into
# one timestamped directory for attaching back to the issue.
# Usage: bash scripts/diagnose_fengrid.sh [app_binary]
set -u
APP="${1:-$HOME/dev/projects/fengrid/qt/dist/fengrid/fengrid}"
OUT="$HOME/fengrid_diag_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUT"
log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$OUT/collector.log"; }

log "fengrid diagnostic collection starting -> $OUT"

# ------------------------------------------------------------- system info
{
  echo "=== uname ==="; uname -a
  echo "=== os-release ==="; cat /etc/os-release 2>/dev/null
  echo "=== cpu ==="; lscpu 2>/dev/null | head -20
  echo "=== mem ==="; free -h
  echo "=== disk (data dir fs) ==="; df -hT "$HOME/.local/share/fengrid" 2>/dev/null || df -hT "$HOME"
  echo "=== kernel cmdline ==="; cat /proc/cmdline 2>/dev/null
  echo "=== load ==="; cat /proc/loadavg
  echo "=== psi (cpu/io/mem pressure) ==="
  for f in cpu io memory; do echo "-- $f"; cat "/proc/pressure/$f" 2>/dev/null; done
  echo "=== gpu ==="; lspci 2>/dev/null | grep -iE 'vga|3d|display' || true
  echo "=== wayland/x11 ==="; echo "SESSION=$XDG_SESSION_TYPE DISPLAY=$DISPLAY WAYLAND_DISPLAY=$WAYLAND_DISPLAY"
} > "$OUT/system_info.txt" 2>&1
log "system_info.txt written"

# ------------------------------------------------------------- qt env
env | grep -E '^(QT_|QSG_|QML|LD_LIBRARY_PATH|FENGRID|XDG_)' > "$OUT/env.txt" 2>/dev/null || true

# ------------------------------------------------------------- app logs (pre-existing)
DATA="$HOME/.local/share/fengrid"
cp -v "$DATA/crash.log" "$OUT/" 2>/dev/null
cp -v "$DATA"/freeze-*.log "$OUT/" 2>/dev/null
ls -la "$DATA" > "$OUT/datadir_listing.txt" 2>&1

# ------------------------------------------------------------- db forensics (read-only copy)
if command -v sqlite3 >/dev/null 2>&1 && [ -f "$DATA/library.db" ]; then
  sqlite3 "file:$DATA/library.db?mode=ro" \
    "PRAGMA page_count; PRAGMA freelist_count;
     SELECT kind, enabled, COUNT(*) FROM source GROUP BY kind, enabled;
     SELECT COUNT(*) FROM asset;
     SELECT 'wal_bytes:' || (SELECT page_count*page_size FROM pragma_wal_checkpoint(PASSIVE)) ;" \
    > "$OUT/db_state.txt" 2>&1 || \
    sqlite3 "file:$DATA/library.db?mode=ro" ".dbinfo" > "$OUT/db_state.txt" 2>&1
  ls -la "$DATA/library.db"* >> "$OUT/db_state.txt" 2>&1
  log "db_state.txt written"
fi

# ------------------------------------------------------------- launch + monitor
if [ ! -x "$APP" ]; then
  log "ERROR: app binary not found at $APP — collecting static info only"
  log "done"; exit 0
fi

log "launching $APP (monitoring for 60s; close the window to end early)"
APP_LOG="$OUT/app.log"
"$APP" >"$APP_LOG" 2>&1 &
APP_PID=$!
echo "app_pid=$APP_PID" >> "$OUT/collector.log"

# per-second samples: CPU%, RSS, threads, io, plus any freeze warnings
for i in $(seq 1 60); do
  if ! kill -0 "$APP_PID" 2>/dev/null; then log "app exited after ${i}s"; break; fi
  {
    echo "--- t=${i}s $(date +%H:%M:%S) ---"
    ps -p "$APP_PID" -o pid,ppid,%cpu,%mem,rss,vsz,nlwp,stat,wchan:20,comm 2>/dev/null
    grep -E '^(VmRSS|VmSwap|Threads)' "/proc/$APP_PID/status" 2>/dev/null
    awk '/^(read_bytes|write_bytes|rchar|wchar)/' "/proc/$APP_PID/io" 2>/dev/null
  } >> "$OUT/process_timeline.tsv" 2>&1
  # freeze-*.log appearing means the watchdog fired — grab it immediately
  new=$(ls -t "$DATA"/freeze-*.log 2>/dev/null | head -1)
  [ -n "$new" ] && ! grep -q "$(basename "$new")" "$OUT/collector.log" 2>/dev/null \
    && { cp "$new" "$OUT/"; log "FREEZE DUMP captured: $new"; }
  sleep 1
done

# per-thread final state + open files (locks)
kill -0 "$APP_PID" 2>/dev/null && {
  for t in /proc/$APP_PID/task/*; do
    tid=$(basename "$t")
    comm=$(cat "$t/comm" 2>/dev/null); state=$(awk '{print $3}' "$t/stat" 2>/dev/null)
    wchan=$(cat "$t/wchan" 2>/dev/null); sysc=$(head -c 60 "$t/syscall" 2>/dev/null)
    echo "tid=$tid comm=$comm state=$state wchan=$wchan syscall=$sysc"
  done > "$OUT/threads_final.txt"
  ls -l /proc/$APP_PID/fd 2>/dev/null | grep -v 'pipe\|socket\|/dev/' >> "$OUT/open_files.txt" 2>&1
  log "threads_final.txt + open_files.txt written"
}

kill "$APP_PID" 2>/dev/null; wait "$APP_PID" 2>/dev/null
grep -iE 'error|warning|freeze|traceback' "$APP_LOG" > "$OUT/app_errors.txt" 2>/dev/null
log "collection complete — attach $OUT (tar it: tar czf $OUT.tar.gz -C $(dirname "$OUT") $(basename "$OUT"))"
