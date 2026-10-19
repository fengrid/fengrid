# syntax=docker/dockerfile:1
#
# Fengrid Linux builder — linux-x64 (amd64).
#
# Twin file: linux-arm64.Dockerfile (byte-identical except this header —
# documented in docker/README.md; keep in sync).
#
# Builds natively on the arch-tagged runner: --platform selects the variant,
# no QEMU emulation is involved. Output (via the artifact stage) is the
# PyInstaller bundle produced by build/scripts/build-linux.sh inside the
# container.
#
# Local build:
#   docker buildx build --platform linux/amd64 \
#     -f docker/linux-x64.Dockerfile \
#     --output type=local,dest=dist/linux-x64 .
#
# DRAFT (2026-10-18): not yet executed — validate the WebEngine runtime lib
# list on the first real run (see docker/README.md).
ARG BASE=python:3.12-slim-bookworm
FROM ${BASE} AS build
ARG VARIANT=prod
ENV DEBIAN_FRONTEND=noninteractive \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    FENGRID_VARIANT=${VARIANT} \
    FENGRID_IN_CONTAINER=1

# Qt WebEngine runtime dependencies + build tooling. Trim/extend after the
# first real run identifies what the bundled binary actually loads.
RUN apt-get update && apt-get install -y --no-install-recommends \
      libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
      libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
      libgbm1 libasound2 libpango-1.0-0 libcairo2 libfontconfig1 \
      libdbus-1-3 libegl1 libgl1 libglib2.0-0 \
      build-essential file patchelf git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /work
COPY build/scripts/ build/scripts/
COPY build/requirements-build.txt build/requirements-build.txt
COPY build/requirements-dev.txt build/requirements-dev.txt
COPY qt/ qt/
COPY fonts/ fonts/

# The build script skips venv creation when FENGRID_IN_CONTAINER=1 and uses
# the container's system python.
RUN bash build/scripts/build-linux.sh linux-x64

FROM scratch AS artifact
COPY --from=build /work/qt/dist/fengrid /fengrid
