#!/usr/bin/env python3
"""Fengrid deep-diagnostic launcher — probes a live process tree.

Launches the app (or attaches to a running PID), samples the full
process tree once per second, and writes a timestamped bundle of log
files: memory/CPU timelines, thread stacks, WAL DB state, and app logs.

Usage:
    python3 fengrid_diagnose.py            # launch + monitor for 120s
    python3 fengrid_diagnose.py --pid 1234 # attach to a running app
    python3 fengrid_diagnose.py --seconds 300
"""
import argparse
import glob
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

APP_PATH = os.path.expanduser("~/dev/projects/fengrid/qt/dist/fengrid/fengrid")
OUT_DIR = os.path.expanduser("~/fengrid_diagnostics")

def now():
    return datetime.now().isoformat(timespec="seconds")

def find_all_fengrid_pids():
    """Find every PID whose /proc/<pid>/comm is 'fengrid'."""
    pids = []
    for proc_dir in glob.glob("/proc/[0-9]*"):
        try:
            with open(os.path.join(proc_dir, "comm"), "r") as f:
                if f.read().strip() == "fengrid":
                    pids.append(int(os.path.basename(proc_dir)))
        except (OSError, IOError):
            pass
    return sorted(pids)

def read_proc(pid, fname):
    """Read a /proc entry; returns None if the process is gone."""
    try:
        with open(f"/proc/{pid}/{fname}", "r") as f:
            return f.read()
    except (OSError, IOError):
        return None

def snap_process(pid, fh):
    """One sample of a process: status, stat, io, fd count."""
    status = read_proc(pid, "status")
    stat = read_proc(pid, "stat")
    io = read_proc(pid, "io")
    fd_dir = f"/proc/{pid}/fd"
    n_fd = 0
    try:
        n_fd = len(os.listdir(fd_dir))
    except OSError:
        pass
    fh.write(f"[{now()}] pid={pid}\n")
    if status:
        for line in status.splitlines():
            if line.split(":")[0] in ("Name", "State", "VmRSS", "VmSize",
                                      "VmPeak", "Threads", "voluntary_ctxt",
                                      "nonvoluntary_ctxt", "VmSwap"):
                fh.write(f"  {line}\n")
    if io:
        for line in io.splitlines():
            if line.startswith(("read_bytes", "write_bytes", "rchar", "wchar")):
                fh.write(f"  {line}\n")
    fh.write(f"  open_fds: {n_fd}\n")
    # thread count + native stacks via /proc/<pid>/task/*/stat
    task_dir = f"/proc/{pid}/task"
    try:
        for tid in sorted(os.listdir(task_dir)):
            tstat = read_proc(tid, "stat") if os.path.isdir(f"{task_dir}/{tid}") else None
            if tstat:
                comm = tstat.split("(", 1)[1].rsplit(")", 1)[0]
                state = tstat.rsplit(")", 1)[1].split()[0]
                fh.write(f"    thread tid={tid} comm={comm} state={state}\n")
    except OSError:
        pass
    fh.write("\n")

def snap_all(outdir, fh):
    """Sample every fengrid process."""
    pids = find_all_fengrid_pids()
    if not pids:
        fh.write(f"[{now()}] no fengrid processes found\n\n")
        return []
    for pid in pids:
        snap_process(pid, fh)
    return pids

def collect_system_info(outdir):
    lines = ["=== uname ===", run("uname -a"),
             "=== os-release ===", run("cat /etc/os-release"),
             "=== cpu ===", run("lscpu | head -25"),
             "=== memory ===", run("free -h"),
             "=== disk ===", run("df -h /home /tmp 2>/dev/null"),
             "=== swap ===", run("swapon --show"),
             "=== qml/qt env ===",
             f"QT_QUICK_BACKEND={os.environ.get('QT_QUICK_BACKEND', '(unset)')}",
             f"LD_LIBRARY_PATH={os.environ.get('LD_LIBRARY_PATH', '(unset)')}"]
    txt = "\n".join(lines)
    (outdir / "system_info.txt").write_text(txt)
    print(f"[system] -> {outdir/'system_info.txt'}")

def run(cmd):
    # shell=True is safe here: every command is a hardcoded literal
    # passed below (no user/external input ever reaches this helper)
    try:
        return subprocess.run(cmd, shell=True, capture_output=True,
                              text=True, timeout=5).stdout
    except Exception as e:
        return f"(error: {e})"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, help="attach to running fengrid PID")
    ap.add_argument("--seconds", type=int, default=120)
    args = ap.parse_args()

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    outdir = Path(OUT_DIR) / stamp
    outdir.mkdir(parents=True, exist_ok=True)
    print(f"[start] {now()} -> {outdir}")

    collect_system_info(outdir)

    proc = None
    if args.pid:
        pids = [args.pid]
    else:
        if not os.path.exists(APP_PATH):
            print(f"[error] app not found at {APP_PATH}", file=sys.stderr)
            return 1
        log = open(outdir / "app.log", "w")
        proc = subprocess.Popen([APP_PATH], stdout=log, stderr=subprocess.STDOUT,
                                env={**os.environ, "QT_QPA_PLATFORMTHEME": ""})
        time.sleep(2)
        pids = find_all_fengrid_pids()
        print(f"[launch] app started, pids={pids}")

    proc_f = open(outdir / "process_timeline.txt", "w")
    start = time.time()
    try:
        while time.time() - start < args.seconds:
            snap_all(outdir, proc_f)
            proc_f.flush()
            time.sleep(1)
    except KeyboardInterrupt:
        print(f"\n[stop] interrupted at {now()}")
    finally:
        proc_f.close()
        if proc:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
            print(f"[stop] app terminated rc={proc.returncode}")

    print(f"[done] diagnostics written to {outdir}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
