#!/usr/bin/env python3
"""#61 startup-freeze diagnostic — run ON THE AFFECTED MACHINE.

Everything the faulthandler dumps can't see lives in C++ (Qt scene graph,
fontconfig, WebEngine/Chromium, GL drivers). This script launches fengrid
as its own child (so ptrace is permitted without sudo under Yama), then
collects during the run:

  01-system.txt     OS/CPU/GPU/display/fontconfig env, ldd of the binary
  02-db.txt         DB forensics on a COPY (counts, pragmas, timed queries,
                    EXPLAIN QUERY PLAN for the sources_summary SQL)
  03-run.log        timestamped fengrid stdout+stderr
  04-samples.tsv    0.5s samples: CPU ticks, page faults, I/O counters,
                    RSS/PSS, PSI
  05-threads.txt    2s snapshots: per-thread name/state/CPU/wchan/syscall/
                    kernel stack + process-tree scan
  06-pyspy-dump-N   py-spy --native stacks every 10s (C++ frames visible!)
  07-flamegraph.svg py-spy record --native --idle over the whole run
  08-gdb-bt.txt     gdb thread-apply-all backtraces (fallback if py-spy is
                    missing, or triggered by a freeze)
  09-syscalls.txt   strace -c syscall histogram (--strace, opt-in)
  10-app-logs/      copies of crash.log + freeze-*.log after the run

Usage:
  ~/dev/projects/fengrid/scripts/diagnose-freeze.py
  (defaults: --duration 90 — kills fengrid after 90s; use 0 to run until
   you close the window yourself. Close any running fengrid first.)

Requires nothing but Python 3.8+; py-spy / gdb / strace / glxinfo are used
if present and their absence is recorded.
"""
from __future__ import annotations

import argparse
import io as _io
import os
import re
import shutil
import signal
import sqlite3
import stat as statmod
import subprocess
import sys
import tarfile
import threading
import time
from datetime import datetime
from pathlib import Path

CLK_TCK = os.sysconf("SC_CLK_TCK") or 100


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def run_cmd(cmd: list, timeout: float = 15.0) -> str:
    """Run a command, return its stdout, or a failure note. Never raises."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           errors="replace", timeout=timeout)
        out = (p.stdout or "") + (p.stderr or "")
        return out.strip() if p.returncode == 0 else \
            f"(exit {p.returncode}) {out.strip()[:500]}"
    except FileNotFoundError:
        return "(not installed)"
    except subprocess.TimeoutExpired:
        return "(timeout)"
    except Exception as e:                                   # noqa: BLE001
        return f"(error: {e})"


# --------------------------------------------------------------- procfs

def _stat_fields(pid_or_tid: "int | str"):
    """/proc/<pid>/stat → dict after the ') ' split (field 3 = state)."""
    try:
        raw = Path(f"/proc/{pid_or_tid}/stat").read_text()
    except (OSError, ValueError):
        return None
    try:
        rest = raw[raw.rindex(") ") + 2:]
        f = rest.split()
        # f[0]=state(3) f[7]=minflt(10) f[9]=majflt(12) f[11]=utime(14)
        # f[12]=stime(15) f[17]=threads(20)
        return {
            "state": f[0],
            "minflt": int(f[7]),
            "majflt": int(f[9]),
            "utime": int(f[11]) / CLK_TCK,
            "stime": int(f[12]) / CLK_TCK,
            "threads": int(f[17]),
        }
    except (ValueError, IndexError):
        return None


def _read_kv(path: str) -> dict:
    out = {}
    try:
        for line in Path(path).read_text(errors="replace").splitlines():
            k, _, v = line.partition(":")
            if _:
                out[k.strip()] = v.strip()
    except OSError:
        pass
    return out


def _read_int_block(path: str, keys: tuple) -> dict:
    """Single read of a file like /proc/<pid>/io → {key: int}."""
    out = {}
    try:
        for line in Path(path).read_text(errors="replace").splitlines():
            k, _, v = line.partition(":")
            k = k.strip()
            if k in keys:
                out[k] = int(v.strip())
    except (OSError, ValueError):
        pass
    return out


def _smaps_rollup(pid: int) -> dict:
    return _read_kv(f"/proc/{pid}/smaps_rollup")


def _psi(kind: str) -> str:
    """'full avg10' (io/mem) or 'some avg10' (cpu) → e.g. '0.12'."""
    try:
        for line in Path(f"/proc/pressure/{kind}").read_text().splitlines():
            k, rest = line.split(" ", 1)
            for tok in rest.split():
                if tok.startswith(f"avg10="):
                    return tok.split("=", 1)[1]
    except OSError:
        pass
    return ""


def _mount_fs(path: "str | os.PathLike") -> tuple:
    """(fstype, mountpoint) for the longest mount containing path."""
    real = os.path.realpath(os.fspath(path))
    best = ("", "")
    try:
        for line in Path("/proc/self/mountinfo").read_text().splitlines():
            p = line.split()
            if len(p) < 10:
                continue
            mp, fstype = p[4], p[9]
            if real == mp or real.startswith(mp.rstrip("/") + "/"):
                if len(mp) > len(best[1]):
                    best = (fstype, mp)
    except OSError:
        pass
    return best


def _children(pid: int) -> list:
    out = []
    try:
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            try:
                # /proc/<pid>/stat field 4 = ppid (rest[1] after the ') ' split)
                raw = Path(f"/proc/{entry}/stat").read_text()
                rest = raw[raw.rindex(") ") + 2:].split()
                if int(rest[1]) == pid:                    # rest[1]=ppid(4)
                    comm = raw[:raw.rindex(") ")].split("(")[-1]
                    out.append((int(entry), comm))
            except (OSError, ValueError, IndexError):
                continue
    except OSError:
        pass
    return out


def _thread_rows(pid: int) -> list:
    rows = []
    try:
        tids = sorted(os.listdir(f"/proc/{pid}/task"), key=int)
    except OSError:
        return rows
    for tid in tids:
        st = _stat_fields(f"{pid}/task/{tid}")
        if st is None:
            continue
        comm = ""
        try:
            comm = Path(f"/proc/{pid}/task/{tid}/comm").read_text().strip()
        except OSError:
            pass
        wchan = _slurp(f"/proc/{pid}/task/{tid}/wchan")[:40]
        sysc = _slurp(f"/proc/{pid}/task/{tid}/syscall").split()
        sysc = " ".join(sysc[:4]) if sysc else ""
        stack = _slurp(f"/proc/{pid}/task/{tid}/stack", cap=15)
        rows.append((tid, comm, st, wchan, sysc, stack))
    return rows


def _slurp(path: str, cap: int = 0) -> str:
    try:
        t = Path(path).read_text(errors="replace").strip()
        return "\n".join(t.splitlines()[:cap]) if cap else t
    except OSError:
        return ""


# --------------------------------------------------------------- sections

def write_system_info(out: Path, bin_path: Path, data_dir: Path) -> dict:
    W = lambda s: (out / "01-system.txt").open("a", encoding="utf-8").write(s + "\n\n")
    (out / "01-system.txt").write_text("")
    info = {}
    W(f"# fengrid system info — {datetime.now().isoformat()}")
    W("## uname\n" + " ".join(os.uname()))
    info["session"] = os.environ.get("XDG_SESSION_TYPE", "?")
    info["display"] = ("wayland" if os.environ.get("WAYLAND_DISPLAY")
                       else "x11" if os.environ.get("DISPLAY") else "none")
    W(f"## session type={info['session']} display={info['display']}")

    with open("/proc/cpuinfo", errors="replace") as f:
        model = next((l for l in f if "model name" in l), "?").strip()
    mem = _read_kv("/proc/meminfo")
    W(f"## cpu/mem\n{model}\nMemTotal: {mem.get('MemTotal', '?')} kB  "
      f"MemAvailable: {mem.get('MemAvailable', '?')} kB")

    W("## mounts (data dir / binary / cwd)\n"
      f"data dir: {_mount_fs(data_dir)}\nbinary:   {_mount_fs(bin_path)}")
    try:
        st = os.statvfs(str(data_dir))
        W(f"data-dir fs free: {st.f_bavail * st.f_frsize // (1 << 20)} MiB")
    except OSError:
        pass

    # GPU / GL stack — Qt Quick picks a backend here; a stalled driver
    # probe is invisible to faulthandler but kills engine.load.
    for name, cmd in (("glxinfo -B", ["glxinfo", "-B"]),
                      ("eglinfo", ["eglinfo"]),
                      ("vulkaninfo --summary", ["vulkaninfo", "--summary"])):
        W(f"## {name}\n{run_cmd(cmd, timeout=20)}")
    for drv in sorted(Path("/sys/class/drm").glob("card*/device/driver")):
        W(f"## drm driver {drv.parent.name} -> {drv.name}")
    if Path("/proc/driver/nvidia/version").exists():
        W("## nvidia\n" + Path("/proc/driver/nvidia/version").read_text().strip())

    # Fonts — a stale fontconfig cache rebuilds inside the first
    # QFontDatabase query during engine.load and burns minutes in C++.
    W(f"## fonts: fc-list count\n{run_cmd(['sh', '-c', 'fc-list | wc -l'], 30)}")
    W("## fc-cache -v (dirs + mtimes)\n" + run_cmd(["fc-cache", "-v"], 30))
    fc_cache = Path.home() / ".cache/fontconfig"
    if fc_cache.is_dir():
        files = sorted(fc_cache.glob("*"), key=os.path.getmtime)
        age_s = time.time() - os.path.getmtime(files[-1]) if files else -1
        W(f"fontconfig cache: {len(files)} files, newest {age_s/3600:.1f}h old")

    # Binary: type + shared libs (which libGL/libQt actually loads)
    try:
        head = bin_path.open("rb").read(4)
        W(f"## binary {bin_path} ({bin_path.stat().st_size} bytes), "
          f"magic={head!r}")
        if head == b"\x7fELF":
            W("## ldd\n" + run_cmd(["ldd", str(bin_path)], 20))
    except OSError:
        pass

    # Env that shapes Qt behavior — copy what matters, verbatim.
    keys = [k for k in os.environ if re.match(
        r"^(QT_|QTWEBENGINE|FENGRID|LIBGL|MESA|GALLIUM|XDG_SESSION|"
        r"WAYLAND|DISPLAY|LC_|LANG|EGL|SDL)", k)]
    W("## environment\n" + "\n".join(
        f"{k}={os.environ[k]}" for k in sorted(keys)))
    W("## yama ptrace_scope\n" + _slurp("/proc/sys/kernel/yama/ptrace_scope")
      + "  (0=any same-user process can be traced; script launches fengrid"
      " as a child, so tracing is allowed regardless)")

    # dmesg tail — GPU driver oopses / OOM show up here (best effort).
    W("## dmesg tail\n" + run_cmd(["dmesg", "--time-format", "iso",
                                   "|", "tail"], 10).replace("|", ""))
    return info


def db_forensics(out: Path, db_path: Path) -> None:
    rep = []
    if not db_path.exists():
        rep.append(f"DB not found: {db_path}")
    else:
        wal = db_path.with_suffix(db_path.suffix + "-wal")
        st = db_path.stat()
        rep.append(f"db {db_path} size={st.st_size} mtime={st.st_mtime:.0f}")
        if wal.exists():
            rep.append(f"wal {wal.name} size={wal.stat().st_size}")
        copy = out / "library-copy.db"
        try:
            src = sqlite3.connect(
                f"file:{db_path}?mode=ro", uri=True, timeout=5)
            dst = sqlite3.connect(str(copy))
            src.backup(dst)          # backup API: WAL-safe, no locks held
            src.close()
            con = dst
            for pragma in ("page_count", "page_size", "freelist_count"):
                rep.append(f"PRAGMA {pragma} = "
                           f"{con.execute(f'PRAGMA {pragma}').fetchone()[0]}")
            for table in ("asset", "source", "scan_state"):
                try:
                    n = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    rep.append(f"COUNT {table} = {n}")
                except sqlite3.Error as e:
                    rep.append(f"COUNT {table} failed: {e}")
            queries = [
                ("sources_summary-agg",
                 "SELECT source_id, COUNT(*) FROM asset GROUP BY source_id"),
                ("sources_summary-list",
                 "SELECT id, kind, path, label, enabled FROM source"
                 " ORDER BY kind, label"),
            ]
            for label, q in queries:
                rep.append(f"EQP {label}:\n  " + "\n  ".join(
                    r[3] for r in con.execute("EXPLAIN QUERY PLAN " + q)))
                t0 = time.perf_counter()
                con.execute(q).fetchall()
                rep.append(f"TIMED {label} = "
                           f"{time.perf_counter() - t0:.4f}s (warm copy)")
            con.close()
        except sqlite3.Error as e:
            rep.append(f"sqlite error: {e}")
    (out / "02-db.txt").write_text(
        f"# DB forensics — {datetime.now().isoformat()}\n" + "\n".join(rep)
        + "\n", encoding="utf-8")
    log("02-db.txt written")


def collect_env_probe(bin_path: Path) -> str:
    lines = [f"# run info — {datetime.now().isoformat()}",
             f"binary: {bin_path}"]
    pyspy = shutil.which("py-spy")
    lines += [f"py-spy: {pyspy or 'MISSING — pip install py-spy for native stacks'}",
              f"gdb: {shutil.which('gdb') or 'missing'}",
              f"strace: {shutil.which('strace') or 'missing'}"]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------- run loop

def main() -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--bin", default="~/dev/projects/fengrid/qt/dist/fengrid/fengrid")
    ap.add_argument("--data-dir",
                    default=os.path.join(os.environ.get("XDG_DATA_HOME",
                       os.path.expanduser("~/.local/share")), "fengrid"))
    ap.add_argument("--out", default=None, help="output dir (default ~/fengrid-diag-<ts>)")
    ap.add_argument("--duration", type=float, default=90.0,
                    help="seconds to run fengrid before SIGTERM; 0 = until exit")
    ap.add_argument("--strace", action="store_true", help="run under strace -c -f")
    ap.add_argument("--no-record", action="store_true", help="skip py-spy record")
    ap.add_argument("--env", action="append", default=[],
                    help="extra KEY=VAL passed to fengrid (repeatable)")
    ap.add_argument("--selftest", action="store_true",
                    help="exercise the procfs parsers against /proc/self and exit")
    args = ap.parse_args()

    if args.selftest:
        print("stat:", _stat_fields(os.getpid()))
        print("io:", _read_int_block(f"/proc/{os.getpid()}/io",
              ("rchar", "wchar", "read_bytes", "write_bytes", "syscr", "syscw")))
        print("rollup:", {k: _smaps_rollup(os.getpid()).get(k) for k in ("Rss", "Pss")})
        print("psi cpu/io/mem:", _psi("cpu"), _psi("io"), _psi("memory"))
        print("mount(/tmp):", _mount_fs("/tmp"))
        print("threads:", len(_thread_rows(os.getpid())))
        return 0

    bin_path = Path(args.bin).expanduser()
    data_dir = Path(args.data_dir).expanduser()
    if not bin_path.is_file():
        log(f"ERROR: binary not found: {bin_path}")
        return 2
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = Path(args.out or Path.home() / f"fengrid-diag-{ts}")
    out.mkdir(parents=True, exist_ok=True)
    log(f"output dir: {out}")

    (out / "00-run-info.txt").write_text(
        collect_env_probe(bin_path), encoding="utf-8")
    write_system_info(out, bin_path, data_dir)
    db_forensics(out, data_dir / "library.db")

    # Existing freeze artifacts, pre-run (post-run copies land in 10-app-logs)
    pre_freezes = set(data_dir.glob("freeze-*.log"))

    env = dict(os.environ)
    env["QSG_INFO"] = "1"          # scene-graph/RHI backend choice to stderr
    env["QT_LOGGING_RULES"] = (";".join([
        "qt.qml.timers*=true",        # slow QML timers/bindings
        "qt.scenegraph.general*=true",
        "qt.scenegraph.time.*=true",  # per-pass render timings
        "qt.quick.gpu*=true",
    ]) + ";" + env.get("QT_LOGGING_RULES", ""))
    for kv in args.env:
        k, _, v = kv.partition("=")
        env[k] = v

    cmd = [str(bin_path)]
    if args.strace and shutil.which("strace"):
        cmd = ["strace", "-c", "-f", "-o", str(out / "09-syscalls.txt")] + cmd
    log(f"launching: {' '.join(cmd)}")

    t0 = time.monotonic()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace",
                            bufsize=1, cwd=str(bin_path.parent), env=env)

    # app output → 03-run.log with elapsed timestamps
    runlog = (out / "03-run.log").open("a", encoding="utf-8")
    freeze_events: list = []

    def pump_output():
        if proc.stdout is None:
            return
        try:
            for line in proc.stdout:
                el = time.monotonic() - t0
                runlog.write(f"[{el:8.2f}s] {line}")
                runlog.flush()
                if "freeze detected" in line:
                    freeze_events.append((el, line.strip()))
        except (ValueError, OSError):
            pass
    threading.Thread(target=pump_output, daemon=True).start()

    pyspy = shutil.which("py-spy")
    gdb = shutil.which("gdb")

    def pyspy_dump(tag: str) -> None:
        if not pyspy:
            return
        r = run_cmd([pyspy, "dump", "--pid", str(proc.pid), "--native"], 30)
        path = out / f"06-pyspy-dump-{tag}.txt"
        path.write_text(
            f"# py-spy dump at T+{time.monotonic()-t0:.1f}s pid={proc.pid}\n"
            + r + "\n", encoding="utf-8")
        log(f"py-spy dump {tag} written")

    # flamegraph for the whole run (graceful SIGINT write at the end)
    recorder = None
    if pyspy and not args.no_record:
        recorder = subprocess.Popen(
            [pyspy, "record", "--pid", str(proc.pid), "--native", "--idle",
             "--format", "flamegraph", "-o", str(out / "07-flamegraph.svg")],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    stop = threading.Event()
    prev = {"utime": 0.0, "stime": 0.0, "minflt": 0, "majflt": 0,
            "rchar": 0, "wchar": 0, "read_bytes": 0, "write_bytes": 0,
            "syscr": 0, "syscw": 0}
    io_keys = tuple(prev.keys() - {"utime", "stime", "minflt", "majflt"})
    threads_f = (out / "05-threads.txt").open("a", encoding="utf-8")
    tsv_f = (out / "04-samples.tsv").open("a", encoding="utf-8")
    tsv_f.write("t,utime_s,stime_s,threads,state,minflt,majflt,rchar,wchar,"
                "read_bytes,write_bytes,syscr,syscw,rss_kb,pss_kb,"
                "priv_dirty_kb,psi_cpu,psi_io,psi_mem\n")

    def sampler():
        n = 0
        dumped_freezes = set()
        while not stop.is_set():
            el = time.monotonic() - t0
            if proc.poll() is not None:
                break
            st = _stat_fields(proc.pid)
            if st is None:                  # process vanished mid-sample
                break
            ios = _read_int_block(f"/proc/{proc.pid}/io", io_keys)
            roll = _smaps_rollup(proc.pid)
            tsv_f.write(",".join(map(str, [
                f"{el:.2f}",
                st["utime"] - prev["utime"], st["stime"] - prev["stime"],
                st["threads"], st["state"],
                st["minflt"] - prev["minflt"], st["majflt"] - prev["majflt"],
                ios.get("rchar", 0) - prev["rchar"],
                ios.get("wchar", 0) - prev["wchar"],
                ios.get("read_bytes", 0) - prev["read_bytes"],
                ios.get("write_bytes", 0) - prev["write_bytes"],
                ios.get("syscr", 0) - prev["syscr"],
                ios.get("syscw", 0) - prev["syscw"],
                roll.get("Rss", "").replace(" kB", ""),
                roll.get("Pss", "").replace(" kB", ""),
                roll.get("Private_Dirty", "").replace(" kB", ""),
                _psi("cpu"), _psi("io"), _psi("memory"),
            ])) + "\n")
            tsv_f.flush()
            prev.update({"utime": st["utime"], "stime": st["stime"],
                         "minflt": st["minflt"], "majflt": st["majflt"],
                         **{k: ios.get(k, 0) for k in io_keys}})
            n += 1
            if n % 4 == 0:                       # every ~2s: thread snapshot
                el2 = time.monotonic() - t0
                threads_f.write(f"\n=== T+{el2:.1f}s ===\n")
                for tid, comm, ts_, wchan, sysc, stack in _thread_rows(proc.pid):
                    threads_f.write(
                        f"tid={tid} {comm} state={ts_['state']} "
                        f"utime={ts_['utime']:.2f} stime={ts_['stime']:.2f} "
                        f"wchan={wchan or '-'} syscall={sysc or '-'}\n")
                    if stack and "denied" not in stack:
                        threads_f.write("".join(f"    {l}\n"
                                                for l in stack.splitlines()))
                kids = _children(proc.pid)
                if kids:
                    threads_f.write("children: " + ", ".join(
                        f"{p}:{c}" for p, c in kids) + "\n")
                threads_f.flush()
            if pyspy and n % 20 == 0:            # every ~10s: native dump
                pyspy_dump(f"{int(el):03d}")
            # new freeze-*.log → immediate dump + gdb backtraces
            new_freezes = set(data_dir.glob("freeze-*.log")) - pre_freezes
            if new_freezes and not dumped_freezes:
                dumped_freezes.update(new_freezes)
                log(f"freeze dump appeared at T+{el:.1f}s: {new_freezes}")
                pyspy_dump("freeze")
                if gdb:
                    r = run_cmd([gdb, "-p", str(proc.pid), "-batch",
                                 "-ex", "thread apply all bt"], 45)
                    (out / "08-gdb-bt.txt").write_text(r + "\n", encoding="utf-8")
            stop.wait(0.5)
    threading.Thread(target=sampler, daemon=True).start()

    # wait: fixed duration, or until the app exits on its own
    deadline = None if args.duration <= 0 else t0 + args.duration
    try:
        while proc.poll() is None:
            if deadline and time.monotonic() >= deadline:
                log(f"T+{args.duration:.0f}s — SIGTERM")
                if recorder and recorder.poll() is None:
                    recorder.send_signal(signal.SIGINT)   # graceful: writes svg
                proc.send_signal(signal.SIGTERM)
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    log("SIGTERM ignored — SIGKILL")
                    proc.kill()
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        log("interrupted — stopping fengrid")
        proc.terminate()
    stop.set()
    time.sleep(1.0)
    if recorder and recorder.poll() is None:
        try:
            recorder.wait(timeout=10)
        except subprocess.TimeoutExpired:
            recorder.send_signal(signal.SIGINT)

    rc = proc.poll()
    log(f"fengrid exited rc={rc} after {time.monotonic()-t0:.1f}s")

    # copy the app's own artifacts + everything we know about the freeze
    applogs = out / "10-app-logs"
    applogs.mkdir(exist_ok=True)
    for src in list(data_dir.glob("freeze-*.log")) + [data_dir / "crash.log"]:
        if src.is_file():
            shutil.copy2(src, applogs / src.name)
    if freeze_events:
        (out / "freeze-summary.txt").write_text(
            "freeze events:\n" + "\n".join(
                f"T+{el:.1f}s  {msg}" for el, msg in freeze_events) + "\n",
            encoding="utf-8")

    # one attachment-friendly bundle
    bundle = out.parent / f"{out.name}.tar.gz"
    with tarfile.open(bundle, "w:gz") as tar:
        tar.add(out, arcname=out.name)
    log(f"bundle: {bundle}")

    # quick console summary
    tail = (out / "03-run.log").read_text(errors="replace").splitlines()[-40:]
    print("\n--- last app output ---")
    print("\n".join(tail))
    print(f"\nAll files in: {out}\nAttach: {bundle}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
