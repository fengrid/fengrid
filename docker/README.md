# docker/ — Fengrid build pipelines (DRAFT — none executed yet)

Status as of 2026-10-18: these Dockerfiles and the workflow in
`.github/workflows/build.yml` were drafted per the `dev-qt` task and have
**not** been run. First real runs validate image tags, PyInstaller flags, and
the QtWebEngine runtime library list. The workflow only triggers on `main`
(prod) and `dev` (dev); pushes to `dev-qt` fire nothing — use
`workflow_dispatch` to exercise the pipelines when testing begins.

## Target → builder matrix

| Target | Dockerfile | How it builds | CI runner label |
|---|---|---|---|
| linux-x64 | `docker/linux-x64.Dockerfile` | Docker (arch-native, no QEMU) | `["self-hosted","docker","linux-x64"]` |
| linux-arm64 | `docker/linux-arm64.Dockerfile` | Docker (arch-native, no QEMU) | `["self-hosted","docker","linux-arm64"]` |
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

## Local builds

```sh
# linux-x64 (prod)
docker buildx build --platform linux/amd64 \
  -f docker/linux-x64.Dockerfile \
  --output type=local,dest=dist/linux-x64 .

# linux-arm64 (dev)
docker buildx build --platform linux/arm64 \
  -f docker/linux-arm64.Dockerfile --build-arg VARIANT=dev \
  --output type=local,dest=dist/linux-arm64 .
```

Native (no Docker) equivalents:

```sh
bash build/scripts/build-linux.sh linux-x64          # prod
FENGRID_VARIANT=dev bash build/scripts/build-linux.sh linux-arm64
pwsh build/scripts/build-windows.ps1 -Target windows-x64   # or powershell on Windows hosts
bash build/scripts/build-macos.sh macos-arm64              # on macOS only
```

## Artifacts

- `dist/fengrid-<variant>-<target>.tar.gz` (linux, native scripts)
- `qt/dist/fengrid-<variant>-<target>.tar.gz` (linux, docker build via the
  script inside the container; `--output` lands the bundle under `dist/`)
- `qt/dist/fengrid-<variant>-<target>.zip` (windows, macos)

CI uploads `fengrid-<variant>-<target>-<sha>` via `actions/upload-artifact@v4`.

## QtWebEngine runtime note (Linux)

The Linux Dockerfiles pre-install the shared libraries QtWebEngine needs at
launch (`libnss3`, `libgbm1`, `libxkbcommon0`, `libasound2`, `libegl1`,
`libfontconfig1`, …). The list was drafted from the Qt deployment docs and
**not yet validated by running the bundle** — expect to trim or extend it on
the first real run. This is also flagged in
`docs/architecture/0001-qt6-rewrite.md` (packaging).
