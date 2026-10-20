# docker/ — Fengrid build pipelines

Status as of 2026-10-19: the linux pipelines have run for real (see "First
run results"); windows/macos remain drafted and their first runs validate
image tags, PyInstaller flags, and the QtWebEngine runtime library list. The
workflow only triggers on `main` (prod) and `dev` (dev); pushes to `dev-qt`
fire nothing — use `workflow_dispatch` to exercise the pipelines when
testing begins.

## Target → builder matrix

| Target | Dockerfile | How it builds | CI runner label |
|---|---|---|---|
| linux-x64 | `docker/linux-x64.Dockerfile` | Docker (arch-native, no QEMU), via `build/scripts/build-docker-linux.sh` | `["self-hosted","docker","linux-x64"]` |
| linux-arm64 | `docker/linux-arm64.Dockerfile` | Docker (arch-native, no QEMU), via `build/scripts/build-docker-linux.sh` | `["self-hosted","docker","linux-arm64"]` |
| windows-x64 | `docker/windows-x64.Dockerfile` (draft) — **default CI path is the native script** | Windows host w/ Windows containers, or native `build-windows.ps1` | `["self-hosted","docker","windows-x64"]` |
| windows-arm64 | `docker/windows-arm64.Dockerfile` — **intentional fail-fast stub** | fails at the PySide6 wheel probe (see below) | `["self-hosted","docker","windows-arm64"]` |
| macos-x64 | `docker/macos-x64.Dockerfile` — **fail-fast stub** | native `build-macos.sh` (Docker cannot host macOS) | `["self-hosted","docker","macos-x64"]` |
| macos-arm64 | `docker/macos-arm64.Dockerfile` — **fail-fast stub** | native `build-macos.sh` | `["self-hosted","docker","macos-arm64"]` |

## Platform caveats (read before "fixing" anything)

- **No QEMU.** Runners are tagged per architecture, so each Linux build
  executes natively on its own arch — `--platform` merely selects the
  variant. Never enable QEMU emulation for these builds; it is slow and
  pointless given arch-tagged runners.
- **macOS cannot be containerized.** Apple's EULA forbids macOS system images
  on non-Apple hardware and no macOS base images exist. The macOS rows in the
  workflow therefore run `build/scripts/build-macos.sh` **natively** on the
  macOS runners; the Dockerfiles for those targets exist only so the pipeline
  list is complete and fails with an explanation rather than silently.
- **The `docker` label on macOS rows** reflects the user-specified runner
  labeling convention, not the build method: the label routes the job; the
  script chooses the toolchain. If the macOS runner lacks Docker entirely,
  that is fine — the job never calls it.
- **Windows containers require a Windows host.** The `docker,windows-x64`
  runner must be a Windows machine with Windows containers enabled (process
  isolation). If Docker is unavailable there, the workflow still works: the
  Windows rows run `build/scripts/build-windows.ps1` natively, which produces
  the same artifact.
- **Windows ARM64 wheels.** PySide6 does not publish Windows ARM64 wheels on
  PyPI (verified 2026-10-18). The stub Dockerfile and the probe inside
  `build-windows.ps1` both fail loudly with the recorded decision. Re-verify
  wheel availability before enabling the target; options are documented in
  `docs/architecture/0001-qt6-rewrite.md` (risks).

## The buildx wrapper (`build/scripts/build-docker-linux.sh`)

Both local builds and the CI linux rows go through one script so the two
paths cannot drift:

```sh
# linux-x64 prod, artifacts -> build/linux-x64/ (bind-mount extraction)
bash build/scripts/build-linux-x64.sh          # thin wrapper, same as below
bash build/scripts/build-docker-linux.sh linux-x64

# linux-arm64 dev variant, artifacts -> build/linux-arm64/
FENGRID_VARIANT=dev bash build/scripts/build-docker-linux.sh linux-arm64

# build straight to files without loading an image (what CI uses)
OUTPUT=local bash build/scripts/build-docker-linux.sh linux-x64

# tag + push the builder image
PUSH=1 PUSH_REF=ghcr.io/fengrid/fengrid-builder:linux-x64 \
  bash build/scripts/build-docker-linux.sh linux-x64
```

### GL / rendering notes

The artifact never ships the host X/GL stack (the container's `libX11`/
`libxcb`/`libGL*` copies would shadow the end machine's and break glvnd
vendor dispatch → `qglx_findConfig` FBConfig failures, `SIGABRT`). Qt
resolves X/GL from the end machine at runtime, where a working vendor
stack is guaranteed on any box that can show a window.

If the display has no usable hardware GL (GLX-less XWayland, some
NVIDIA/VM setups), the app detects it at startup via a ctypes GLX/EGL
probe and falls back to the software renderer instead of aborting — you
will see `warning: no usable hardware GL on this display — using the
software renderer` on stderr. Force it manually with
`QT_QUICK_BACKEND=software ./fengrid`; explicit `QT_*` env vars always
override the probe.

Knobs: `FENGRID_VARIANT` (prod|dev), `IMAGE` (default
`fengrid-builder:<target>`), `PUSH`/`PUSH_REF`, `OUTPUT=bind|local`,
`BUILD_DIR` (default `<repo>/build/<target>`), `FENGRID_SMOKE` (default 1 —
runs the frozen binary offscreen inside the container with
`QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox --disable-gpu"`; set 0 to skip).
All output is teed to `$BUILD_DIR/build.log`; the script fails if the
tarball did not appear, and prints its sha256.

Native (no Docker) equivalents:

```sh
bash build/scripts/build-linux.sh linux-x64          # prod
FENGRID_VARIANT=dev bash build/scripts/build-linux.sh linux-arm64
pwsh build/scripts/build-windows.ps1 -Target windows-x64   # or powershell on Windows hosts
bash build/scripts/build-macos.sh macos-arm64              # on macOS only
```

## Artifacts

- `build/<target>/fengrid-<variant>-<target>.tar.gz` plus the unpacked
  onedir bundle in `build/<target>/fengrid/` (wrapper + CI)
- `qt/dist/fengrid-<variant>-<target>.tar.gz` (native linux script)
- `qt/dist/fengrid-<variant>-<target>.zip` (windows, macos)

CI uploads `fengrid-<variant>-<target>-<sha>` via `actions/upload-artifact@v4`
(the linux rows upload the tarball only, not the unpacked tree).

## First run results (2026-10-19, linux-x64 prod)

The first real container run failed at PyInstaller's datas step with
`Unable to find '/work/branding/assets'` — and could not be fixed by adding a
`COPY branding/` line, because `branding/` is gitignored by design (internal
candidate branding docs) and would never exist in a CI checkout. Findings
folded back into the pipeline:

- The runtime needs exactly one file from the brand tree —
  `fengrid-mark.svg` (window icon). It now ships from the tracked
  `qt/resources/branding/` (provenance note inside), and the app falls back
  to the legacy `branding/assets` path when present. The spec no longer
  references `branding/` at all.
- `qt/fengrid.spec` was a stale build byproduct with host-absolute paths
  inside `COPY qt/`'s context. Removed; `build-linux.sh` now regenerates the
  spec per run into `build/pyinstaller/<target>-<variant>/` (gitignored) and
  invokes `python -m PyInstaller` so PATH can never bite in slim images.
- Added a root `.dockerignore` (context drops from ~200 MB to a few MB and
  no stale `qt/dist` tarball can enter an image).
- The artifact stage now lands `dist/` in full — the earlier form silently
  dropped the tarball it claimed to produce.
- The build script's `--add-data` entries are checked for existence and
  skipped with a warning instead of aborting the build.
- The container-side smoke test (`FENGRID_SMOKE=1`, default on in the
  wrapper) launches the frozen binary offscreen and captures a screenshot —
  this is the guard that catches the next class of failure (missing runtime
  libs, WebEngine sandbox) before CI does.

## QtWebEngine runtime note (Linux)

The Linux Dockerfiles pre-install the shared libraries QtWebEngine needs at
launch (`libnss3`, `libgbm1`, `libxkbcommon0`, `libasound2`, `libegl1`,
`libfontconfig1`, …). **Validated 2026-10-19 on the second container run:**
PyInstaller's unresolved-library warnings named exactly
`libxkbfile.so.1`, `libXtst.so.6`, `libpulse.so.0`, the `libxcb-*` family
and `libxkbcommon-x11.so.0` — those packages are now installed in the
builder image so PyInstaller bundles them into the artifact (self-contained
on minimal hosts). `libgtk-3` is intentionally absent: only the optional
gtk3 platform theme wants it and Qt falls back when the plugin can't load.
The container-side smoke test (`FENGRID_SMOKE=1`, default in the wrapper)
exercises the frozen binary offscreen on every run; the remaining
unresolved-lib warnings in the build log (gtk3 theme only) are expected.
