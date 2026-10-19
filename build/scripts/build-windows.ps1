# build-windows.ps1 — build Fengrid (Qt 6) for windows-x64 | windows-arm64.
#
# Usage:
#   build-windows.ps1 -Target windows-x64
#   FENGRID_VARIANT=prod|dev   (default: prod; dev adds pytest/ruff)
#
# DRAFT (2026-10-18): not yet executed.
#   - windows-x64: expected to work after the PyInstaller/NSIS flags are
#     validated on a real runner.
#   - windows-arm64: EXPECTED TO FAIL at the PySide6 probe — PyPI does not
#     publish windows-arm64 wheels (status verified 2026-10-18; re-verify
#     before enabling). The probe below fails loudly with the decision
#     recorded in docs/architecture/0001-qt6-rewrite.md (risks).
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("windows-x64", "windows-arm64")]
    [string]$Target
)
$ErrorActionPreference = "Stop"
$VARIANT = if ($env:FENGRID_VARIANT) { $env:FENGRID_VARIANT } else { "prod" }
if ($VARIANT -notin @("prod", "dev")) { throw "unknown variant: $VARIANT" }

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$QtDir = Join-Path $Root "qt"

Push-Location $QtDir
try {
    python -m venv .venv
    . .\.venv\Scripts\Activate.ps1
    python -m pip install --upgrade pip wheel
    $Reqs = Join-Path $Root "build\requirements-build.txt"
    if ($VARIANT -eq "dev") { $Reqs = Join-Path $Root "build\requirements-dev.txt" }
    python -m pip install -r $Reqs

    # platform wheel probe — fail fast with the recorded decision
    try {
        python -c "import PySide6"
    } catch {
        if ($Target -eq "windows-arm64") {
            throw ("PySide6 wheels for windows-arm64 are not published on PyPI " +
                   "(verified 2026-10-18; re-verify before enabling this target). " +
                   "Options: build Qt/PySide from source, or ship the windows-x64 " +
                   "build for Windows-on-ARM emulation. " +
                   "See docs/architecture/0001-qt6-rewrite.md (risks).")
        }
        throw
    }
    python -c "import PySide6, sys; print('PySide6', PySide6.__version__)"

    pyinstaller --noconfirm --clean --name fengrid `
        --add-data "qml;qml" `
        --add-data "..\fonts;fonts" `
        --paths src `
        src\fengrid\__main__.py

    $Dist = Join-Path $QtDir "dist"
    # NSIS installer hook: the packaging work parked on the build-win-x64
    # branch (c464dc3) folds in here once the skeleton is validated.
    Compress-Archive -Path (Join-Path $Dist "fengrid") `
        -DestinationPath (Join-Path $Dist "fengrid-$VARIANT-$Target.zip") -Force
    Write-Host "artifact: $Dist\fengrid-$VARIANT-$Target.zip"
} finally {
    Pop-Location
}
