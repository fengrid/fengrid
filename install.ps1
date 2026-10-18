# install.ps1 — install & launch the Fengrid (Windows)
#
# Installs to ~\fengrid\ (or a custom location) and places a launcher
# (fengrid.cmd) in a folder that is added to the user's PATH.
#
# Compatible with Windows PowerShell 5.1 and PowerShell 7+.
# Run with:  powershell -ExecutionPolicy Bypass -File install.ps1
#            (or right-click -> Run with PowerShell)
# Uninstall: powershell -ExecutionPolicy Bypass -File install.ps1 -Uninstall
#
# The script prompts before anything permanent and never requires admin
# rights; it only writes under the user profile.

[CmdletBinding()]
param(
    [switch]$Uninstall,
    [switch]$Remove   # alias for -Uninstall
)
if ($Remove) { $Uninstall = $true }

$ErrorActionPreference = 'Stop'

function Write-Info  { param($m) Write-Host ':: ' -ForegroundColor Cyan -NoNewline; Write-Host $m }
function Write-Ok    { param($m) Write-Host ':: ' -ForegroundColor Green -NoNewline; Write-Host $m }
function Write-Warn2 { param($m) Write-Host ':: ' -ForegroundColor Yellow -NoNewline; Write-Host $m }
function Write-Die   { param($m) Write-Host ':: ' -ForegroundColor Red -NoNewline; Write-Host $m; exit 1 }

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$DefaultInstallDir = Join-Path $HOME 'fengrid'
$InstallDir = $DefaultInstallDir
$LauncherName = 'fengrid.cmd'
$ListFile = 'list.txt'

# ---------------------------------------------------------------------------
# Uninstaller
# ---------------------------------------------------------------------------
function Invoke-Uninstall {
    Write-Info 'Fengrid uninstaller'
    $candidates = @()
    foreach ($d in @(
        (Join-Path $HOME 'fengrid'),
        (Join-Path $HOME 'icon-browser'),
        (Join-Path $HOME 'gtk4-icon-browser'),
        (Join-Path $HOME '.local\share\gtk4-icon-browser'))) {
        if (Test-Path $d) { $candidates += $d }
    }
    $custom = Read-Host 'Custom install location to remove? (path, or Enter to skip)'
    if ($custom) { $candidates += $custom }

    if ($candidates.Count -eq 0) {
        Write-Ok 'Nothing found to remove.'
        return
    }

    foreach ($c in $candidates) {
        if ($c -eq $ScriptDir) {
            Write-Warn2 "$c is the repository this script runs from - skipped."
            continue
        }
        if (-not (Test-Path (Join-Path $c 'index.html')) -or -not (Test-Path (Join-Path $c $ListFile))) {
            Write-Warn2 "$c does not look like a Fengrid install - skipped for safety."
            continue
        }
        $size = '{0:N1} MB' -f ((Get-ChildItem $c -Recurse -File | Measure-Object Length -Sum).Sum / 1MB)
        $answer = Read-Host "Remove $c ($size)? [y/N]"
        if ($answer -match '^[yY]') {
            Remove-Item -Recurse -Force $c
            Write-Ok "Removed $c"
        } else {
            Write-Info "Kept $c"
        }
    }

    # PATH entry — removes the marker + export from profile files, and cleans
    # the .cmd launcher dir entry from the user PATH.
    foreach ($rc in @((Join-Path $HOME '.bashrc'), (Join-Path $HOME '.zshrc'))) {
        if (Test-Path $rc) {
            $hit = Select-String -Path $rc -Pattern '^# (Fengrid|Icon Browser|GTK4 icon browser)$' -Quiet
            if ($hit) {
                $answer = Read-Host "Remove the PATH entry install.sh-style marker in $rc? [y/N]"
                if ($answer -match '^[yY]') {
                    $lines = Get-Content $rc
                    $out = @(); $skip = $false
                    foreach ($l in $lines) {
                        if ($l -match '^# (Fengrid|Icon Browser|GTK4 icon browser)$') { $skip = $true; continue }
                        if ($skip) { $skip = $false; continue }
                        $out += $l
                    }
                    Set-Content -Path $rc -Value $out
                    Write-Ok "Removed PATH entry from $rc"
                }
            }
        }
    }

    # user PATH cleanup (directories named like ours)
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    if ($userPath) {
        $parts = $userPath -split ';' | Where-Object { $_ -and $_ -notmatch 'fengrid|icon-browser' }
        [Environment]::SetEnvironmentVariable('Path', ($parts -join ';'), 'User')
        Write-Ok 'User PATH cleaned of fengrid / legacy icon-browser entries (takes effect in new shells).'
    }

    Write-Ok 'Uninstall complete.'
    exit 0
}

if ($Uninstall) { Invoke-Uninstall }

# ---------------------------------------------------------------------------
# 0. Install location
# ---------------------------------------------------------------------------
while ($true) {
    $answer = Read-Host "Install location? [Enter = $DefaultInstallDir, or type a custom path]"
    $InstallDir = if ($answer) { $answer } else { $DefaultInstallDir }
    if ($InstallDir -like '~*') { $InstallDir = $InstallDir -replace '^~', $HOME }
    if (-not [IO.Path]::IsPathRooted($InstallDir)) { $InstallDir = Join-Path (Get-Location) $InstallDir }
    $InstallDir = $InstallDir.TrimEnd('\')

    # hidden? (any dot-prefixed component)
    $hidden = $false
    foreach ($part in ($InstallDir -split '[\\/]')) {
        if ($part -match '^\.\w' -or $part -eq '.') { $hidden = $true; break }
    }

    # writable / root-owned? walk up to the nearest existing ancestor
    $check = $InstallDir
    while (-not (Test-Path $check)) {
        $parent = Split-Path -Parent $check
        if (-not $parent) { break }
        $check = $parent
    }
    $risky = $false
    try {
        $probe = Join-Path $check ([IO.Path]::GetRandomFileName() + '.probe')
        New-Item -ItemType File -Path $probe -ErrorAction Stop | Out-Null
        Remove-Item $probe
    } catch {
        $risky = $true
    }
    if ((Get-Item $check -ErrorAction SilentlyContinue).Owner -eq 'NT AUTHORITY\SYSTEM' -and $check -ne $HOME) { $risky = $true }

    $confirmed = $true
    if ($hidden) {
        $answer = Read-Host "Hidden directory chosen: $InstallDir - some sandboxed browsers CANNOT access hidden paths, so the page or its icons may fail to load. Install there anyway? [y/N]"
        if ($answer -notmatch '^[yY]') { $confirmed = $false }
    }
    if ($confirmed -and $risky) {
        $answer = Read-Host "Unwritable or system-owned location: $InstallDir - this script avoids elevated installs, so it would likely fail. Install there anyway? [y/N]"
        if ($answer -notmatch '^[yY]') { $confirmed = $false }
    }
    if ($confirmed) { break }
    Write-Info 'Pick a different location.'
}
Write-Ok "Will install to: $InstallDir"

# ---------------------------------------------------------------------------
# 1. Icon source discovery (any folder, any of the common formats)
# ---------------------------------------------------------------------------
Write-Info "Scanning common Windows icon locations is not useful by default (system icons live inside DLLs) - pick folders to scan."
$customPaths = @()
while ($true) {
    $answer = Read-Host 'Icon folder to scan (path, or Enter to skip)'
    if (-not $answer) { break }
    if (Test-Path $answer -PathType Container) {
        $customPaths += $answer
        Write-Ok "Will scan: $answer"
    } else {
        Write-Warn2 "Not a directory: $answer - skipped"
    }
}
if ($customPaths.Count -eq 0) {
    Write-Die "No icon folders given - nothing to preview. Re-run and provide at least one folder of icons (png/svg/ico)."
}

# ---------------------------------------------------------------------------
# 2. Generate list.txt (+ list.js fallback) with forward slashes
# ---------------------------------------------------------------------------
Write-Info "Generating $ListFile ..."
$exts = @('*.png', '*.svg', '*.ico')
$allIcons = @()
foreach ($p in $customPaths) {
    foreach ($e in $exts) {
        $allIcons += Get-ChildItem -Path $p -Filter $e -Recurse -File -ErrorAction SilentlyContinue
    }
}
$allIcons = $allIcons | Sort-Object FullName -Unique
if ($allIcons.Count -eq 0) {
    Write-Die 'No icon files found in the scanned folders.'
}
$paths = $allIcons | ForEach-Object { $_.FullName -replace '\\', '/' }
$paths | Set-Content -Path $ListFile -Encoding ASCII
Write-Ok "$ListFile written ($($paths.Count) icon files)"

# ---------------------------------------------------------------------------
# 3. Install files
# ---------------------------------------------------------------------------
Write-Info "Installing to $InstallDir ..."
New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
Copy-Item (Join-Path $ScriptDir 'index.html') $InstallDir -Force
if (Test-Path (Join-Path $ScriptDir 'fonts')) {
    Copy-Item (Join-Path $ScriptDir 'fonts') $InstallDir -Recurse -Force
}
if (Test-Path (Join-Path $ScriptDir 'server')) {
    Copy-Item (Join-Path $ScriptDir 'server') $InstallDir -Recurse -Force
}
Copy-Item (Join-Path $ScriptDir $ListFile) $InstallDir -Force

# local icon tree: icons/<theme>/<file> with theme = folder name
Write-Info 'Copying icon files into icons\ ...'
$copied = 0
foreach ($icon in $allIcons) {
    $theme = Split-Path -Parent $icon.FullName | Split-Path -Leaf
    $destDir = Join-Path $InstallDir (Join-Path 'icons' $theme)
    New-Item -ItemType Directory -Path $destDir -Force | Out-Null
    # forward-slash list path -> rel used by the page must match icons/<theme>/<name>
    Copy-Item $icon.FullName (Join-Path $destDir $icon.Name) -Force
    $copied++
}
Write-Ok "$copied icon files copied to icons\"

# list.js mirrors list.txt as a JS array (fetch() is blocked on file:// pages)
$jsPaths = ($paths | ForEach-Object { '"' + ($_ -replace '"', '\"') + '"' }) -join ','
"window.ICON_LIST=[$jsPaths];" | Set-Content -Path (Join-Path $InstallDir 'list.js') -Encoding ASCII

# ---------------------------------------------------------------------------
# 4. Launcher + user PATH
# ---------------------------------------------------------------------------
$binDir = Join-Path $HOME '.local\bin'
New-Item -ItemType Directory -Path $binDir -Force | Out-Null
$launcher = Join-Path $binDir $LauncherName
"@echo off`r`nstart `"`" `"$InstallDir\index.html`"" | Set-Content -Path $launcher -Encoding ASCII
Write-Ok "Created $launcher -> opens $InstallDir\index.html"

$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if (-not $userPath) { $userPath = '' }
if (($userPath -split ';') -notcontains $binDir) {
    $answer = Read-Host "Add $binDir to your user PATH? [Y/n]"
    if ($answer -notmatch '^[nN]') {
        $newPath = if ($userPath) { "$userPath;$binDir" } else { $binDir }
        [Environment]::SetEnvironmentVariable('Path', $newPath, 'User')
        Write-Ok 'PATH updated (takes effect in new shells/terminals).'
    } else {
        Write-Warn2 'Skipping PATH update - use the full launcher path instead.'
    }
}

# ---------------------------------------------------------------------------
# 5. Launch
# ---------------------------------------------------------------------------
Write-Info 'Launching fengrid...'
Start-Process (Join-Path $InstallDir 'index.html')
Write-Ok 'Done. Quick launch any time:  fengrid'