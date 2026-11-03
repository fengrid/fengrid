#!/usr/bin/env bash
# ==============================================================================
# Fengrid Freeze & Performance Diagnostic Script
# ==============================================================================
# This script runs the Fengrid application while collecting extensive system
# and application-level diagnostics. It is designed to be run when the
# application is experiencing freezes, crashes, or extreme slowness.
#
# Output: A timestamped directory containing log files and a compressed archive
#         ready to be attached to a debugging session.
# ==============================================================================

set -u

APP_BIN="${APP_BIN:-$HOME/dev/projects/fengrid/qt/dist/fengrid/fengrid}"
OUT_BASE="$HOME/fengrid-diagnostics"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
OUT_DIR="$OUT_BASE/run-$TIMESTAMP"
LOG_MAIN="$OUT_DIR/app-output.log"
LOG_SYS="$OUT_DIR/system-info.log"
LOG_TRACE="$OUT_DIR/strace.log"
LOG_PROCS="$OUT_DIR/process-monitor.log"
LOG_EVENT="$OUT_DIR/event-tracer.log"

mkdir -p "$OUT_DIR"

if [ ! -x "$APP_BIN" ]; then
    echo "ERROR: Fengrid binary not found or not executable at: $APP_BIN" | tee "$OUT_DIR/error.log"
    exit 1
fi

echo "=============================================================" | tee "$LOG_EVENT"
echo "Fengrid Diagnostic Session started at: $(date)" | tee "$LOG_EVENT"
echo "Output directory: $OUT_DIR" | tee "$LOG_EVENT"
echo "=============================================================" | tee "$LOG_EVENT"

# 1. Capture system info before launch
{
    echo "### uname -a ###"
    uname -a
    echo "### OS Release ###"
    cat /etc/os-release 2>/dev/null
    echo "### CPU Info ###"
    lscpu 2>/dev/null | head -n 25
    echo "### Memory ###"
    free -h
    echo "### Swap ###"
    swapon --show 2>/dev/null
    echo "### Disk (app partition) ###"
    df -h "$APP_BIN"
    echo "### Environment (relevant) ###"
    env | grep -Ei 'QT|XDG|DISPLAY|WAYLAND|FENGRID' || echo "(none found)"
    echo "### Dmesg (last 50 lines) ###"
    dmesg | tail -n 50 2>/dev/null
    echo "### GPU/Vulkan Info ###"
    if command -v vulkaninfo > /dev/null; then
        vulkaninfo --summary 2>/dev/null | head -n 30
    else
        echo "vulkaninfo not found."
    fi
    if command -v glxinfo > /dev/null; then
        glxinfo -B 2>/dev/null | head -n 20
    else
        echo "glxinfo not found."
    fi
} > "$LOG_SYS" 2>&1

# 2. Start the application. strace if available (catch syscalls to see file locks / hangs)
echo "[diag] Launching Fengrid..." | tee -a "$LOG_EVENT"
if command -v strace > /dev/null; then
    echo "[diag] Using strace." | tee -a "$LOG_EVENT"
    strace -f -tt -T -e trace=open,openat,read,write,poll,ppoll,select,epoll_wait,futex,ioctl,fsync,fdatasync,msync,close \
        -o "$LOG_TRACE" \
        "$APP_BIN" > "$LOG_MAIN" 2>&1 &
else
    echo "[diag] WARNING: strace not found. Running without syscall tracing." | tee -a "$LOG_EVENT"
    "$APP_BIN" > "$LOG_MAIN" 2>&1 &
fi
APP_PID=$!
echo "[diag] App PID: $APP_PID" | tee -a "$LOG_EVENT"

# 3. Monitor process memory/CPU in a loop (every 2 seconds)
echo "[diag] Monitoring process tree (every 2s) -> $LOG_PROCS" | tee -a "$LOG_EVENT"
while kill -0 "$APP_PID" 2>/dev/null; do
    echo "--- $(date '+%H:%M:%S.%3N') ---" >> "$LOG_PROCS"
    ps -p "$APP_PID" -o pid,ppid,%cpu,%mem,rss,vsz,nlwp,state,wchan:30,cmd >> "$LOG_PROCS" 2>/dev/null || break
    # find children (threads or subprocesses)
    ps --ppid "$APP_PID" -o pid,%cpu,%mem,rss,nlwp,state,wchan:30,cmd >> "$LOG_PROCS" 2>/dev/null
    sleep 2
done

# 4. Wait for app to exit
wait "$APP_PID" 2>/dev/null
APP_STATUS=$?
echo "[diag] App exited with status: $APP_STATUS at $(date)" | tee -a "$LOG_EVENT"

# 5. Capture post-mortem system info
{
    echo "### App Exit Code ###"
    echo "$APP_STATUS"
    echo "### Dmesg post-run (last 30 lines) ###"
    dmesg | tail -n 30 2>/dev/null
} > "$OUT_DIR/postmortem.log" 2>&1

# 6. Archive everything
ARCHIVE="$OUT_BASE/fengrid-diag-$TIMESTAMP.tar.gz"
echo "[diag] Creating archive: $ARCHIVE" | tee -a "$LOG_EVENT"
tar -czf "$ARCHIVE" -C "$OUT_BASE" "run-$TIMESTAMP"

echo "=============================================================" | tee -a "$LOG_EVENT"
echo "[diag] DONE. Please attach: $ARCHIVE" | tee -a "$LOG_EVENT"
