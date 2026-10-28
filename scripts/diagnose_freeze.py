#!/usr/bin/env python3
"""Fengrid freeze/crash diagnostic collector.

Runs the Fengrid application, monitors its process tree (CPU, memory,
I/O, thread counts), gathers detailed system information and application
logs, and writes everything to a timestamped directory.

Usage:
    python3 scripts/diagnose_freeze.py [--seconds 120] [--app /path/to/fengrid]
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

HOME = Path.home()
DEFAULT_APP = HOME / "dev/projects/fengrid/qt/dist/fengrid/fengrid"
DATA_DIR = HOME / ".local/share/fengrid"


def run(cmd: str, timeout: float = 10) -> str:
    """Run a quick shell command; returns stdout, never raises."""
    try:
        return subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        ).stdout.strip()
    except Exception as exc:             # noqa: BLE001 - collector never dies
        return f"<error: {exc}>"


class Probe(threading.Thread):
    """Background sampler: appends one process-state line per second."""

    def __init__(self, pid: int, out_file: io.TextIOBase):
        super().__init__(daemon=True)
        self.pid = pid
        self.fh = out_file
        self.stop_flag = threading.Event()

    def _proc_line(self) -> str:
        try:
            stat = Path(f"/proc/{self.pid}/stat").read_text().split()
            # fields: 14 utime, 15 stime (clock ticks), 20 threads
            utime, stime, nthreads = int(stat[13]), int(stat[14]), stat[18]
            vm = Path(f"/proc/{self.pid}/statm").read_text().split()
            rss_pages = int(vm[1])
            rss_mb = rss_pages * 4 / 1024.0
            # cpu %: (utime+stime - last) / elapsed_ticks * 100
            return (f"t={time.time():.0f} cpu_ticks={utime + stime} "
                    f"threads={nthreads} rss={rss_mb:.1f}MB")
        except (OSError, ValueError, IndexError):
            return f"t={time.time():.0f} pid={self.pid} gone"

    def run(self) -> None:
        self.fh.write("time cpu_ticks threads rss_mb\n")
        while not self.stop_flag.is_set():
            self.fh.write(self._proc_line() + "\n")
            self.fh.flush()
            self.stop_flag.wait(1.0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=int, default=120)
    ap.add_argument("--app", type=Path, default=DEFAULT_APP)
    ap.add_argument("--data-dir", type=Path, default=DATA_DIR)
    args = ap.parse_args()

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    outdir = HOME / "fengrid-freeze-report" / stamp
    outdir.mkdir(parents=True, exist_ok=True)

    print(f"[diag] writing to {outdir}")

    # ------------------------------------------------ 1. static system info
    sys_info = outdir / "system.txt"
    sys_info.write_text(
        "\n".join([
            f"== uname ==\n{run('uname -a')}",
            f"== distro ==\n{run('cat /etc/os-release | head -4')}",
            f"== cpu ==\n{run('lscpu | head -20')}",
            f"== memory ==\n{run('free -h')}",
            f"== storage (data dir fs) ==\n{run(f'df -hT {args.data_dir}')}",
            f"== load ==\n{run('uptime')}",
            f"== qt env ==\n" + "\n".join(
                f"{k}={v}" for k, v in sorted(os.environ.items())
                if k.startswith(("QT_", "QSG_", "FENGRID"))
            ),
        ]),
        encoding="utf-8",
    )

    # ---------------------------------------- 2. existing crash/freeze logs
    logs_dir = outdir / "prior-logs"
    logs_dir.mkdir(exist_ok=True)
    if args.data_dir.exists():
        for f in sorted(args.data_dir.glob("*.log")):
            try:
                shutil.copy2(f, logs_dir / f.name)
            except OSError:
                pass

    # --------------------------------------------------- 3. run + probe app
    app_log = outdir / "app.log"
    if not args.app.exists():
        print(f"[diag] app not found at {args.app}; collecting static info only")
        return 0

    print(f"[diag] launching {args.app} for {args.seconds}s "
          f"(close the window to end early)")
    proc = subprocess.Popen(
        [str(args.app)],
        stdout=open(app_log, "ab"), stderr=subprocess.STDOUT,
        env={**os.environ,
             "QT_LOGGING_RULES": "qt.qml.*=true;qt.scenegraph*=true"},
    )
    prober = Probe(proc.pid, open(outdir / "process_probe.txt", "w"))
    prober.start()

    t0 = time.time()
    try:
        while time.time() - t0 < args.seconds:
            if proc.poll() is not None:
                print(f"[diag] app exited rc={proc.returncode} "
                      f"after {time.time() - t0:.0f}s")
                break
            time.sleep(1)
    except KeyboardInterrupt:
        print("[diag] interrupted")

    prober.stop_flag.set()
    prober.join(timeout=2)
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    # -------------------------------------------- 4. post-run error digest
    text = app_log.read_text(errors="replace")
    interesting = [
        l for l in text.splitlines()
        if any(w in l.lower() for w in
               ("error", "warning", "freeze", "traceback", "exception",
                "segfault", "crash"))
    ]
    (outdir / "errors.txt").write_text(
        "\n".join(interesting[-500:]) or "(no error/warning lines)",
        encoding="utf-8",
    )

    # ---------------------------------------------------------- 5. bundle
    bundle = str(outdir) + ".tar.gz"
    subprocess.run(["tar", "czf", bundle, "-C", str(outdir.parent),
                    str(outdir.name)], check=False)
    print(f"[diag] bundle: {bundle}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
