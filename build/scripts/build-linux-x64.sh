#!/usr/bin/env bash
#
# build-linux-x64.sh — build the Linux x64 package with docker buildx.
#
# Thin entry point for the linux-x64 pipeline: it delegates to
# build-docker-linux.sh (the single source of truth shared with CI) so the
# local and GitHub-Actions paths can never drift. Output is attached to the
# calling terminal AND teed to the build log; the resulting bundle and
# tarball are copied to ./build/linux-x64/ as the invoking user (bind-mount
# extraction — no root-owned files).
#
# Usage:
#   build-linux-x64.sh                # prod variant
#   FENGRID_VARIANT=dev build-linux-x64.sh
#
# Environment knobs (forwarded to build-docker-linux.sh):
#   FENGRID_VARIANT=prod|dev   build variant (default: prod)
#   IMAGE=<name:tag>           builder image tag (default: fengrid-builder:linux-x64)
#   PUSH=1                     tag + push the builder image after build
#   PUSH_REF=<name:tag>        registry ref to push (default: $IMAGE)
#   OUTPUT=bind|local          artifact extraction (default: bind)
#   BUILD_DIR=<dir>            artifact destination (default: <repo>/build/linux-x64)
#   FENGRID_SMOKE=1            offscreen smoke test inside the container (default: 1)
#
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
exec bash "$HERE/build-docker-linux.sh" linux-x64
