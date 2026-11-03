# syntax=docker/dockerfile:1
#
# Fengrid Windows builder — windows-arm64. INTENTIONAL FAIL-FAST STUB (draft).
#
# PySide6 does not publish Windows ARM64 wheels on PyPI (status verified
# 2026-10-18; re-verify before enabling this target). This image exists so
# the pipeline target is explicit and fails with a clear message instead of
# a cryptic installer error. The decision is recorded in
# docs/architecture/0001-qt6-rewrite.md (risks).
#
# When wheels appear (or Qt/PySide is built from source), replace this file
# with a copy of windows-x64.Dockerfile adjusted for the arm64 python
# installer and verify it on the windows-arm64 runner.
FROM mcr.microsoft.com/windows/servercore:ltsc2022
SHELL ["powershell", "-Command", "$ErrorActionPreference='Stop';"]
RUN Write-Host 'ERROR: PySide6 wheels for Windows ARM64 are not published on PyPI (verified 2026-10-18; re-verify before enabling). Options: build Qt/PySide from source, or ship the windows-x64 build for Windows-on-ARM emulation. See docs/architecture/0001-qt6-rewrite.md (risks).'; exit 1
