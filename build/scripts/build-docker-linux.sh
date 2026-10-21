#!/usr/bin/env bash
#
# build-docker-linux.sh — docker buildx wrapper for the Fengrid Linux pipelines.
#
# Builds the PyInstaller bundle inside docker/linux-<target>.Dockerfile and
# lands the artifacts in a local bind-mount directory. CI (build.yml) calls
# this script with OUTPUT=local, so CI and local builds share one code path.
#
# Usage:
#   build-docker-linux.sh [linux-x64|linux-arm64]     (default: linux-x64)
#
# Environment knobs:
#   FENGRID_VARIANT=prod|dev     build variant (default: prod)
#   IMAGE=<name:tag>             builder image tag (default: fengrid-builder:<target>)
#   PUSH=1                       after build, tag + push the builder image
#   PUSH_REF=<name:tag>          registry ref to push to (default: $IMAGE;
#                                e.g. ghcr.io/fengrid/fengrid-builder:linux-x64)
#   OUTPUT=bind|local            artifact extraction method (default: bind)
#                                  bind  : build the builder stage (--load), then
#                                          run the image and bind-mount $BUILD_DIR
#                                          as /out — artifacts copied as the
#                                          calling user, so no root-owned files
#                                  local : buildx --output type=local against the
#                                          final artifact stage — no image load
#   BUILD_DIR=<dir>              artifact destination (default: <repo>/build/<target>)
#   FENGRID_SMOKE=1              run the container-side offscreen smoke test
#                                (default: 1 — set 0 to skip)
#
# All output is teed to $BUILD_DIR/build.log.
set -euo pipefail

TARGET="${1:-linux-x64}"
case "$TARGET" in
    linux-x64)   PLATFORM="linux/amd64" ;;
    linux-arm64) PLATFORM="linux/arm64" ;;
    *) echo "unknown target: $TARGET (use linux-x64 or linux-arm64)" >&2; exit 1 ;;
esac

VARIANT="${FENGRID_VARIANT:-prod}"
case "$VARIANT" in
    prod|dev) ;;
    *) echo "unknown variant: $VARIANT (use prod or dev)" >&2; exit 1 ;;
esac

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DOCKERFILE="$ROOT/docker/$TARGET.Dockerfile"
BUILD_DIR="${BUILD_DIR:-$ROOT/build/$TARGET}"
IMAGE="${IMAGE:-fengrid-builder:$TARGET}"
PUSH="${PUSH:-0}"
PUSH_REF="${PUSH_REF:-}"
OUTPUT="${OUTPUT:-bind}"
SMOKE="${FENGRID_SMOKE:-1}"

case "$OUTPUT" in
    bind|local) ;;
    *) echo "unknown OUTPUT: $OUTPUT (use bind or local)" >&2; exit 1 ;;
esac

mkdir -p "$BUILD_DIR"
exec > >(tee -a "$BUILD_DIR/build.log") 2>&1

echo "== fengrid docker build: $TARGET variant=$VARIANT output=$OUTPUT $(date -u '+%Y-%m-%dT%H:%M:%SZ') =="

if [ "$OUTPUT" = "local" ]; then
    # build straight to a local directory via the final artifact stage
    docker buildx build \
        --platform "$PLATFORM" \
        --build-arg "VARIANT=$VARIANT" \
        --build-arg "SMOKE=$SMOKE" \
        -f "$DOCKERFILE" \
        --output "type=local,dest=$BUILD_DIR" \
        "$ROOT"
else
    # build the builder stage into the local docker image store
    docker buildx build \
        --platform "$PLATFORM" \
        --target build \
        --build-arg "VARIANT=$VARIANT" \
        --build-arg "SMOKE=$SMOKE" \
        -f "$DOCKERFILE" \
        -t "$IMAGE" \
        --load \
        "$ROOT"
fi

if [ "$PUSH" = "1" ]; then
    REF="${PUSH_REF:-$IMAGE}"
    if [ -n "$PUSH_REF" ] && [ "$PUSH_REF" != "$IMAGE" ]; then
        docker tag "$IMAGE" "$PUSH_REF"
    fi
    docker push "$REF"
    echo "pushed image: $REF"
fi

if [ "$OUTPUT" = "bind" ]; then
    # extract as the calling user (no root-owned files), HOME=/tmp so the
    # uid-without-passwd case never trips Qt/PyInstaller cache lookups
    docker run --rm --platform "$PLATFORM" \
        --user "$(id -u):$(id -g)" \
        -e HOME=/tmp \
        -v "$BUILD_DIR:/out" \
        "$IMAGE" \
        bash -c 'cp -a /work/qt/dist/. /out/ && ls -l /out'
fi

TARBALL="$BUILD_DIR/fengrid-${VARIANT}-${TARGET}.tar.gz"
if [ ! -f "$TARBALL" ]; then
    echo "error: artifact $TARBALL was not produced" >&2
    exit 1
fi

echo "== done =="
sha256sum "$TARBALL"
