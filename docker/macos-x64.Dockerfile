# Fengrid macOS builder — macos-x64. INTENTIONAL FAIL-FAST STUB (draft).
#
# macOS applications cannot be built inside Docker: Apple's EULA forbids
# macOS system images on non-Apple hardware and no macOS base images exist.
# The CI workflow therefore runs build/scripts/build-macos.sh NATIVELY on
# the macos-x64 runner; this file exists only so the pipeline list is
# complete and fails with an explanation rather than silently.
#
# See docker/README.md (platform caveats) and
# docs/architecture/0001-qt6-rewrite.md (risks).
FROM alpine:3.20
CMD ["/bin/sh", "-c", "echo 'ERROR: macOS cannot be built in Docker (Apple EULA; no macOS base images). Run build/scripts/build-macos.sh natively on a macOS runner.' && exit 1"]
