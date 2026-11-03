#!/usr/bin/env python3
"""Fengrid deep-diagnostic launcher (#61 follow-up).

Runs the app from the dist bundle, probes its processes and memory
operations while it starts up and settles, collects detailed system
information, and writes everything to one attachable log bundle.

Usage:
    python3 scripts/monitor_fengrid.py [path-to-binary] [--seconds N]

Defaults to ~/dev/projects/fengrid/qt/dist/fengrid/fengrid, 30 seconds.
Requires: python3. psutil is used when available for per-process
memory/threads/fd counts; without it the script degrades to /proc reads.
"""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

# Where to write the bundle
OUT_DIR = Path(os.environ.get("FENGRID_DIAG_OUT", "/tmp/fengrid-diag"))
DEFAULT_BIN = os.path.expanduser("~/dev/projects/fengrid/qt/dist/fengrid/fengrid")

def collect_system_info(out: Path):
    """Snapshot OS / hardware / kernel state that affects startup."""
    f = (out / "01-system.txt").open("w")
    for cmd in (
        ["uname", "-a"],
        ["cat", "/etc/os-release"],
        ["free", "-h"],
        ["df", "-h", str(Path.home())],
        ["cat", "/proc/sys/vm/swappiness"],
        ["cat", "/proc/loadavg"],
        ["nproc"],
    ):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            f.write(f"$ {subprocess.list2cmdline(cmd)}\n{r.stdout}{r.stderr}\n")
        except Exception as e:
            f.write(f"$ {cmd} — ERROR {e}\n")
    # Qt / GUI env — relevant to engine.load and QML warnings
    f.write(f"\nDISPLAY={os.environ.get('DISPLAY', '')}\n")
    f.write(f"WAYLAND_DISPLAY={os.environ.get('WAYLAND_DISPLAY', '')}\n")
    f.write(f"XDG_SESSION_TYPE={os.environ.get('XDG_SESSION_TYPE', '')}\n")
    f.write(f"QT_QPA_PLATFORM={os.environ.get('QT_QPA_PLATFORM', '')}\n")
    f.write(f"PYTHONPATH={os.environ.get('PYTHONPATH', '')}\n")
    f.close()

def collect_running_state(pid: int, out: Path, sample: int = 1):
    """Probe a live PID: memory, threads, fds, and the process tree."""
    f = (out / "03-process.log").open("a")
    f.write(f"\n=== probe @ {time.strftime('%H:%M:%S')} pid={pid} ===\n")
    psutil = None
    try:
        import psutil  # noqa: F401
    except ImportError:
        pass
    if psutil:
        try:
            p = psutil.Process(pid)
            with p.oneshot():
                mi = p.memory_info()
                f.write(f"rss={mi.rss/1024:.0f} KiB  vms={mi.vms/1024:.0f} KiB"
                        f"  threads={p.num_threads()}"
                        f"  fds={p.num_fds()}\n")
                f.write(f"cpu_times={p.cpu_times()}\n")
                f.write(f"status={p.status()}\n")
            for child in p.children(recursive=True):
                try:
                    cm = child.memory_info()
                    f.write(f"  child pid={child.pid} name={child.name()}"
                            f" rss={cm.rss/1024:.0f} KiB\n")
                except psutil.Error:
                    pass
        except psutil.Error as e:
            f.write(f"process gone: {e}\n")
    else:
        # /proc fallback — no psutil available
        try:
            with open(f"/proc/{pid}/status") as fh:
                status = fh.read()
            for key in ("VmRSS", "VmSize", "Threads", "VmSwap"):
                for line in status.splitlines():
                    if line.startswith(key):
                        f.write(line + "\n")
        except OSError as e:
            f.write(f"process gone: {e}\n")
    f.close()
    time.sleep(sample)

def run_app(bin_path: str, seconds: int, out: Path):
    env = dict(os.environ)
    # Ensure the app logs verbosely — capture everything it prints
    env.setdefault("QT_LOGGING_RULES", "*=true")
    env.setdefault("FENGRID_DEBUG", "1")

    log = (out / "02-app.log").open("wb")
    proc = subprocess.Popen(
        [bin_path],
        stdout=log, stderr=subprocess.STDOUT,
        cwd=str(Path(bin_path).parent),
        env=env,
    )
    print(f"[monitor] started pid={proc.pid} — sampling for {seconds}s")
    t0 = time.time()
    while time.time() - t0 < seconds:
        collect_running_state(proc.pid, out)
        if proc.poll() is not None:
            print(f"[monitor] app exited early rc={proc.returncode}")
            break
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    log.close()
    print(f"[monitor] app stopped rc={proc.returncode}")

def main():
    ap = argparse.ArgumentParser(description="Fengrid deep diagnostic")
    ap.add_argument("bin", nargs="?", default=DEFAULT_BIN)
    ap.add_argument("--seconds", type=int, default=30)
    ap.add_argument("--out", default=str(OUT_DIR))
    args = ap.parse_args()
    if not os.path.isfile(args.bin):
        print(f"[monitor] ERROR: binary not found: {args.bin}", file=sys.stderr)
        return 2
    # Popen(cwd=...) resolves the executable against the new cwd, so a
    # relative bin path like "qt/dist/fengrid/fengrid" would be looked up
    # at qt/dist/fengrid/qt/dist/fengrid/fengrid and fail. Resolve first.
    args.bin = os.path.abspath(args.bin)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    collect_system_info(out)
    # wipe old per-run logs, keep 01-system (refreshed anyway)
    for name in ("02-app.log", "03-process.log"):
        (out / name).unlink(missing_ok=True)
    run_app(args.bin, args.seconds, out)
    # bundle: make one tar.gz for attaching
    bundle = out / "fengrid-diag.tar.gz"
    subprocess.run(["tar", "-czf", str(bundle), "-C", str(out),
                    "01-system.txt", "02-app.log", "03-process.log"])
    print(f"[monitor] bundle: {bundle}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
