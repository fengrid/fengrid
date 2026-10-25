# build-windows.ps1 — build Fengrid (Qt 6) for windows-x64 | windows-arm64.
#
# Usage (PowerShell, on a Windows host):
#   .\build-windows.ps1 -Target windows-x64
#   $env:FENGRID_VARIANT = "prod" | "dev"    # default: prod; dev adds pytest/ruff
#   $env:FENGRID_SMOKE   = "1"               # after PyInstaller, launch the frozen
#                                            # binary offscreen and capture a
#                                            # screenshot — fails the build if it
#                                            # does not start
#
# Mirrors build-linux.sh (validated 2026-10-19, linux-x64). STATUS: skeleton —
# not yet executed on a Windows runner. Expect flag-level adjustments the first
# real run (PyInstaller/NSIS specifics noted inline).
#
#   - windows-x64: expected to work.
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
if ($VARIANT -notin @("prod", "dev")) { throw "unknown variant: $VARIANT (use prod or dev)" }

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$QtDir = Join-Path $Root "qt"
$OutDir = Join-Path $QtDir "dist"
# spec is REGENERATED on every run into build/pyinstaller/<target>-<variant> —
# never committed (host-absolute paths in a checked-in spec are a landmine).
$SpecDir = Join-Path $Root (Join-Path "build\pyinstaller" "$Target-$VARIANT")

Push-Location $QtDir
try {
    # native run: isolated venv so CI/local builds don't pollute the host env
    python -m venv .venv
    . .\.venv\Scripts\Activate.ps1
    python -m pip install --upgrade pip wheel
    $Reqs = Join-Path $Root "build\requirements-build.txt"
    if ($VARIANT -eq "dev") { $Reqs = Join-Path $Root "build\requirements-dev.txt" }
    python -m pip install -r $Reqs

    # platform wheel probe — fail fast with the recorded decision (mirrors the
    # probe in build-linux.sh)
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

    # data bundle: every entry is optional at build time — a missing tree logs a
    # warning and is skipped instead of aborting the build halfway through
    # PyInstaller (mirrors add_data in build-linux.sh; Windows separator is ';')
    $DataArgs = @()
    function Add-DataTree([string]$Src, [string]$Dest) {
        if (Test-Path $Src) {
            $script:DataArgs += "--add-data", "$Src;$Dest"
        } else {
            Write-Warning "data tree missing, skipped: $Src"
        }
    }
    Add-DataTree (Join-Path $QtDir "qml") "qml"
    Add-DataTree (Join-Path $Root "fonts") "fonts"
    Add-DataTree (Join-Path $QtDir "resources") "resources"

    New-Item -ItemType Directory -Force -Path $SpecDir | Out-Null
    python -m PyInstaller --noconfirm --clean `
        --specpath $SpecDir `
        @DataArgs `
        --name fengrid `
        --paths src `
        src\fengrid\__main__.py

    # optional smoke test (FENGRID_SMOKE=1): turns "it compiled" into "it
    # starts". Offscreen platform + software rendering + WebEngine sandbox
    # flags, mirroring the container-safe linux smoke. NOTE: PySide6 wheels
    # ship the offscreen platform plugin (platforms/qoffscreen.dll); if the
    # first real run disagrees, drop the QT_QPA_PLATFORM line.
    if ($env:FENGRID_SMOKE -eq "1") {
        $SmokeDb = Join-Path $env:TEMP ("fengrid-smoke-" + $PID + ".db")
        $SmokeShot = Join-Path $OutDir ("smoke-" + $Target + "-" + $VARIANT + ".png")
        Write-Host "smoke: launching frozen binary offscreen"
        # scope the smoke env overrides to the launch, then restore the
        # caller's environment (a stray QT_QPA_PLATFORM would poison a later
        # interactive run in the same shell)
        $SmokeEnv = @{}
        foreach ($Name in @("QT_QPA_PLATFORM", "QT_QUICK_BACKEND",
                            "QTWEBENGINE_CHROMIUM_FLAGS", "HOME", "XDG_DATA_HOME")) {
            $SmokeEnv[$Name] = [Environment]::GetEnvironmentVariable($Name)
        }
        $env:QT_QPA_PLATFORM = "offscreen"
        $env:QT_QUICK_BACKEND = "software"
        $env:QTWEBENGINE_CHROMIUM_FLAGS = "--no-sandbox --disable-gpu"
        $env:HOME = $env:TEMP
        $env:XDG_DATA_HOME = Join-Path $env:TEMP "fengrid-smoke-home"
        try {
            & (Join-Path $OutDir "fengrid\fengrid.exe") `
                --screenshot $SmokeShot --shot-delay 1500 --no-scan --db $SmokeDb
            if ($LASTEXITCODE -ne 0) {
                throw "smoke test failed (binary did not start cleanly)"
            }
            if (-not (Test-Path -LiteralPath $SmokeShot) -or
                (Get-Item -LiteralPath $SmokeShot).Length -eq 0) {
                throw "smoke screenshot is empty"
            }
            Write-Host "smoke: ok ($SmokeShot)"
        } finally {
            foreach ($Name in $SmokeEnv.Keys) {
                [Environment]::SetEnvironmentVariable($Name, $SmokeEnv[$Name])
            }
        }
    }

    # NSIS installer hook: the packaging work parked on the build-win-x64
    # branch (c464dc3: installer/fengrid.nsi + win-setup-helper.ps1) folds in
    # here once the skeleton is validated.
    $Artifact = Join-Path $OutDir ("fengrid-" + $VARIANT + "-" + $Target + ".zip")
    Compress-Archive -Path (Join-Path $OutDir "fengrid") `
        -DestinationPath $Artifact -Force
    Write-Host "artifact: $Artifact"
} finally {
    Pop-Location
}
