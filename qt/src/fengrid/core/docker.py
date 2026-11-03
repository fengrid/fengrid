"""Docker integration core for the Projects studio.

Wraps the docker CLI (no SDK dependency — the binary is the stable
interface) so projects can be packaged, shipped, and inspected:

  - build/run/stop/rm   project images + containers (compose-free MVP)
  - logs/exec/inspect   attach to a running container
  - browse/copy_out     use Fengrid's tools on assets living in the
                        container's filesystem (tar streaming)
  - publish port        live browser preview via Docker networking

Every call has a timeout and raises DockerError with the CLI's own
message — the bridge surfaces it verbatim in the UI. All user input is
passed as argv (never a shell), so names/labels can't inject anything.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path

TIMEOUT = 120
LONG_TIMEOUT = 600


class DockerError(Exception):
    def __init__(self, message: str, code: int = 1):
        super().__init__(message)
        self.code = code


def docker_available() -> bool:
    try:
        return subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True, text=True, timeout=15).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _run(args: list[str], timeout: int = TIMEOUT) -> str:
    if not docker_available():
        raise DockerError("docker is not available", 127)
    try:
        proc = subprocess.run(
            ["docker", *args], capture_output=True, text=True,
            timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise DockerError(f"docker {args[0]} timed out", 124) from e
    if proc.returncode != 0:
        raise DockerError((proc.stderr or proc.stdout).strip()[:400],
                          proc.returncode)
    return proc.stdout


def version() -> str:
    try:
        return _run(["version", "--format", "{{.Server.Version}}"]).strip()
    except DockerError:
        return ""


# ────────────────────────────────────────────────────────── lifecycle
def ps(all_: bool = False) -> list[dict]:
    out = _run(["ps", "-a" if all_ else "",
                "--format", "{{json .}}"] if all_ else
               ["ps", "--format", "{{json .}}"])
    return [json.loads(ln) for ln in out.splitlines() if ln.strip()]


def images() -> list[dict]:
    out = _run(["images", "--format", "{{json .}}"])
    return [json.loads(ln) for ln in out.splitlines() if ln.strip()]


def build(context_dir: str, tag: str, dockerfile: str = "Dockerfile") -> dict:
    """`docker build` with plain progress (suitable for log tailing)."""
    if not Path(context_dir).is_dir():
        raise DockerError(f"build context {context_dir!r} is not a directory")
    _run(["build", "-f", dockerfile, "-t", tag, str(Path(context_dir))],
         timeout=LONG_TIMEOUT)
    return {"tag": tag}


def run(image: str, name: str, ports: list[str] | None = None,
        volumes: list[str] | None = None, env: dict | None = None,
        command: list[str] | None = None, detach: bool = True) -> dict:
    """Create + start a container. ports: ['8080:80']; volumes:
    ['/host:/cont']; env keys must match [A-Za-z_][A-Za-z0-9_]*."""
    args = ["run", "-d" if detach else "-it", "--name", name]
    for p in ports or []:
        _check_port(p)
        args += ["-p", p]
    for v in volumes or []:
        _check_volume(v)
        args += ["-v", v]
    for k, val in (env or {}).items():
        if not k or not k[0].isalpha() and k[0] != "_" \
                or not all(c.isalnum() or c == "_" for c in k):
            raise DockerError(f"bad env name {k!r}")
        args += ["-e", f"{k}={val}"]
    args.append(image)
    if command:
        args += list(command)
    cid = _run(args, timeout=LONG_TIMEOUT).strip()
    return {"container_id": cid, "name": name}


def _check_port(p: str) -> None:
    parts = p.split(":")
    if len(parts) not in (2, 3) or not all(
            x.isdigit() for x in parts[-2:]):
        raise DockerError(f"bad port mapping {p!r} (want host:container)")


def _check_volume(v: str) -> None:
    parts = v.split(":")
    if len(parts) < 2 or not parts[0] or not parts[1]:
        raise DockerError(f"bad volume {v!r} (want source:target)")


def stop(name: str) -> None:
    _run(["stop", name], timeout=LONG_TIMEOUT)


def start(name: str) -> None:
    _run(["start", name])


def rm(name: str, force: bool = False) -> None:
    args = ["rm"]
    if force:
        args.append("-f")
    args.append(name)
    _run(args)


def logs(name: str, tail: int = 200) -> str:
    tail = max(1, min(int(tail), 10000))
    return _run(["logs", "--tail", str(tail), name])


def inspect(name: str) -> dict:
    out = _run(["inspect", name])
    data = json.loads(out)
    return data[0] if data else {}


def state(name: str) -> dict:
    """Compact status for the UI: running?, ports, health."""
    try:
        info = inspect(name)
    except DockerError:
        return {"exists": False}
    st = info.get("State", {})
    ports = []
    for raw, binds in (info.get("NetworkSettings", {})
                       .get("Ports", {}) or {}).items():
        for b in binds or []:
            ports.append(f"{b.get('HostIp', '127.0.0.1')}:"
                         f"{b.get('HostPort')}->{raw}")
    return {
        "exists": True,
        "running": bool(st.get("Running")),
        "status": info.get("State", {}).get("Status", ""),
        "ports": ports,
        "image": info.get("Config", {}).get("Image", ""),
    }


# ───────────────────────────────────────── container filesystem access
def browse(container: str, path: str = "/") -> list[dict]:
    """List a directory INSIDE the container (`exec ls`), for attaching
    Fengrid's tools to container-local storage."""
    path = _safe_path(path)
    out = _run(["exec", container, "ls", "-1ap", path])
    rows = []
    for ln in out.splitlines():
        if not ln.strip():
            continue
        directory = ln.endswith("/")
        rows.append({"name": ln.rstrip("/"),
                     "dir": directory,
                     "path": path.rstrip("/") + "/" + ln.rstrip("/")})
    return rows


def copy_out(container: str, path: str, dest_dir: str) -> str:
    """docker cp a file (or directory) out of the container into the
    host, so scans/imports/exports can process it locally. Returns the
    absolute destination path."""
    path = _safe_path(path)
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    _run(["cp", f"{container}:{path}", str(dest)], timeout=LONG_TIMEOUT)
    return str(dest / Path(path).name)


def _safe_path(path: str) -> str:
    """Container paths go through the CLI as argv, so quoting is safe;
    reject empty/relative nonsense and shell-looking strings anyway."""
    p = (path or "").strip()
    if not p or p.startswith("-") or any(c in p for c in "`$;&"):
        raise DockerError(f"unsafe container path {path!r}")
    return p


def tag_repr(tag: str) -> str:
    # cheap normalization for display
    t = (tag or "").strip()
    if ":" not in t.split("/")[-1]:
        t += ":latest"
    return t


def shell_quote_note(args: list[str]) -> str:
    """Debug helper (tests) — documents that args are passed to execve
    directly; shlex only for logging."""
    return " ".join(shlex.quote(a) for a in args)


os.environ.setdefault("DOCKER_TIMEOUT", str(TIMEOUT))
