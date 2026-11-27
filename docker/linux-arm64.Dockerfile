# syntax=docker/dockerfile:1
#
# Fengrid Linux builder — linux-arm64 (aarch64).
#
# Twin file: linux-x64.Dockerfile (byte-identical except this header —
# documented in docker/README.md; keep in sync).
#
# Builds natively on the arch-tagged runner: --platform selects the variant,
# no QEMU emulation is involved. Output (via the artifact stage) is the
# PyInstaller bundle produced by build/scripts/build-linux.sh inside the
# container.
#
# Local build:
#   docker buildx build --platform linux/arm64 \
#     -f docker/linux-arm64.Dockerfile \
#     --output type=local,dest=dist/linux-arm64 .
#
# DRAFT (2026-10-18): not yet executed — validate the WebEngine runtime lib
# list on the first real run (see docker/README.md).
ARG BASE=ghcr.io/astral-sh/uv:python3.12-bookworm-slim
FROM ${BASE} AS build
ARG VARIANT=prod
# forwarded from build-docker-linux.sh (FENGRID_SMOKE knob) — without
# this, the env never reaches build-linux.sh and docker artifacts ship
# WITHOUT the smoke gate the docs promise
ARG SMOKE=1
# host commit for the About screen (#43): the image has no .git, so
# build-docker-linux.sh forwards it and build-linux.sh stamps it
ARG COMMIT=unknown
ENV DEBIAN_FRONTEND=noninteractive \
    UV_NO_CACHE=1 \
    UV_LINK_MODE=copy \
    FENGRID_VARIANT=${VARIANT} \
    FENGRID_SMOKE=${SMOKE} \
    FENGRID_BUILD_COMMIT=${COMMIT}

# Qt WebEngine runtime dependencies + build tooling. Validated on the first
# two container runs (2026-10-19): PyInstaller's "Library not found" list
# named the xcb family, libxkbcommon-x11, libxkbfile/libXtst (WebEngine) and
# libpulse (Multimedia/TextToSpeech) — they are installed here so PyInstaller
# bundles them and the artifact is self-contained on minimal hosts. libgtk-3
# was deliberately left out: only the optional gtk3 platform theme needs it,
# and Qt falls back gracefully when the plugin cannot load. (Twin of
# linux-x64.Dockerfile — keep in sync.)
RUN apt-get update && apt-get install -y --no-install-recommends \
      libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
      libxkbcommon0 libxkbcommon-x11-0 libxcomposite1 libxdamage1 \
      libxfixes3 libxrandr2 libxtst6 libxkbfile1 \
      libxcb-keysyms1 libxcb-render-util0 libxcb-image0 libxcb-xkb1 \
      libxcb-shape0 libxcb-cursor0 libxcb-icccm4 libxcb-util1 \
      libgbm1 libasound2 libpulse0 libpango-1.0-0 libcairo2 \
      libfontconfig1 libdbus-1-3 libegl1 libgl1 libglib2.0-0 \
      build-essential file patchelf git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /work
COPY build/scripts/ build/scripts/
# qt/ carries pyproject.toml + the committed uv.lock (the uv project root)
COPY qt/ qt/
COPY fonts/ fonts/

# uv (on PATH in this base image) syncs /work/qt/.venv from the committed
# uv.lock inside build-linux.sh — no pip/venv steps in the Dockerfile.
RUN bash build/scripts/build-linux.sh linux-arm64

FROM scratch AS artifact
# land both the onedir bundle and the tar.gz the build script produces —
# the earlier form (dist/fengrid only) silently dropped the tarball that
# docker/README.md documents as the artifact (twin of linux-x64.Dockerfile)
COPY --from=build /work/qt/dist/ /
