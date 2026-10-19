# install.ps1 — install & launch the Fengrid (Windows)
#
# Installs to ~\fengrid\ (or a custom location) and places a launcher
# (fengrid.cmd) in a folder that is added to the user's PATH. The launcher
# starts a local-only web server (loopback bind) and opens the page over
# http:// so refresh and format conversion always work; `fengrid --file`
# opens the plain file instead.
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
    [switch]$Remove,   # alias for -Uninstall
    [string]$IconMode = 'copy'   # copy (default) or hardlink; hardlinks fall
                                 # back to a copy when the filesystem refuses
)
if ($Remove) { $Uninstall = $true }

$ErrorActionPreference = 'Stop'

function Write-Info  { param($m) Write-Host ':: ' -ForegroundColor Cyan -NoNewline; Write-Host $m }
function Write-Ok    { param($m) Write-Host ':: ' -ForegroundColor Green -NoNewline; Write-Host $m }
function Write-Warn2 { param($m) Write-Host ':: ' -ForegroundColor Yellow -NoNewline; Write-Host $m }
function Write-Die   { param($m) Write-Host ':: ' -ForegroundColor Red -NoNewline; Write-Host $m; exit 1 }

# Normalize a user-typed path: trim whitespace, strip surrounding quotes
# (Explorer "Copy as path" and PowerShell tab completion both add them to
# paths with spaces) and expand a leading ~. Without this, pasting
# "D:\Library\Design Library\Icons" fails every Test-Path below.
function ConvertTo-CleanPath {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) { return '' }
    $p = $Value.Trim()
    while ($p.Length -ge 2 -and
           (($p[0] -eq '"' -and $p[$p.Length - 1] -eq '"') -or
            ($p[0] -eq "'" -and $p[$p.Length - 1] -eq "'"))) {
        $p = $p.Substring(1, $p.Length - 2).Trim()
    }
    if ($p -like '~*') { $p = $p -replace '^~', $HOME }
    return $p
}

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
    $InstallDir = ConvertTo-CleanPath (Read-Host "Install location? [Enter = $DefaultInstallDir, or type a custom path]")
    if (-not $InstallDir) { $InstallDir = $DefaultInstallDir }
    if (-not [IO.Path]::IsPathRooted($InstallDir)) { $InstallDir = Join-Path (Get-Location) $InstallDir }
    # strip trailing slashes, but keep a bare drive root intact (D:\ stays D:\,
    # otherwise the TrimEnd turns it into the drive-relative 'D:')
    if ($InstallDir -notmatch '^[A-Za-z]:\\$') { $InstallDir = $InstallDir.TrimEnd('\') }

    # hidden? (any dot-prefixed component)
    $hidden = $false
    foreach ($part in ($InstallDir -split '[\\/]')) {
        if ($part -match '^\.\w' -or $part -eq '.') { $hidden = $true; break }
    }

    # writable / root-owned? walk up to the nearest existing ancestor
    $check = $InstallDir
    while (-not (Test-Path -LiteralPath $check)) {
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
    # compare by SID, not by name — the 'NT AUTHORITY\SYSTEM' string is
    # localized on non-English Windows
    try {
        $owner = (Get-Item -LiteralPath $check -Force -ErrorAction Stop).GetAccessControl().Owner
        $ownerSid = (New-Object System.Security.Principal.NTAccount($owner)).Translate(
            [System.Security.Principal.SecurityIdentifier]).Value
        if ($ownerSid -eq 'S-1-5-18' -and $check -ne $HOME) { $risky = $true }
    } catch {
        if ((Get-Item $check -ErrorAction SilentlyContinue).Owner -eq 'NT AUTHORITY\SYSTEM' -and $check -ne $HOME) { $risky = $true }
    }

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
    $path = ConvertTo-CleanPath (Read-Host 'Icon folder to scan (path, or Enter to skip)')
    if (-not $path) { break }
    # -LiteralPath: '[' and ']' in folder names are not wildcards
    if (Test-Path -LiteralPath $path -PathType Container) {
        $customPaths += $path
        Write-Ok "Will scan: $path"
    } elseif (Test-Path -LiteralPath $path) {
        Write-Warn2 "Not a directory (it is a file): $path - skipped"
    } else {
        Write-Warn2 "Directory not found: $path - skipped"
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
        # -LiteralPath: '[' and ']' in folder names are not wildcards
        $allIcons += Get-ChildItem -LiteralPath $p -Filter $e -Recurse -File -ErrorAction SilentlyContinue
    }
}
$allIcons = $allIcons | Sort-Object FullName -Unique
if ($allIcons.Count -eq 0) {
    Write-Die 'No icon files found in the scanned folders.'
}
$paths = $allIcons | ForEach-Object { $_.FullName -replace '\\', '/' }
# UTF-8 (no BOM): -Encoding ASCII mangles non-ASCII icon file names. Write
# next to the script, not into the caller's current directory — the copy
# below reads it from $ScriptDir, which differs when the script is run via
# -File from another directory.
[IO.File]::WriteAllLines((Join-Path $ScriptDir $ListFile), [string[]]$paths)
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

# local icon tree: mirrors install.sh and the page's parseLine — a path
# containing "/icons/" is filed under its suffix after that marker
# (theme-style layouts), anything else flat as icons/<parent-dir>/<file>.
# (Without the marker rule, a scan folder literally named "icons" would
# diverge from the page's derived relative path and render broken.)
if ($IconMode -notin @('copy', 'hardlink')) {
    Write-Warn2 "Unknown -IconMode '$IconMode' - using copy."
    $IconMode = 'copy'
}
if ($IconMode -eq 'hardlink') {
    Write-Info 'Hardlinking icon files into icons\ ...'
} else {
    Write-Info 'Copying icon files into icons\ ...'
}
$copied = 0
foreach ($icon in $allIcons) {
    $p = $icon.FullName -replace '\\', '/'
    $marker = '/icons/'
    $idx = $p.IndexOf($marker)
    if ($idx -ge 0) {
        $rel = $p.Substring($idx + $marker.Length)
    } else {
        $rel = (Split-Path -Parent $icon.FullName | Split-Path -Leaf) + '/' + $icon.Name
    }
    $dest = Join-Path $InstallDir (Join-Path 'icons' $rel)
    $destDir = Split-Path -Parent $dest
    New-Item -ItemType Directory -Path $destDir -Force | Out-Null
    if ((Test-Path -LiteralPath $dest) -and
        (Get-FileHash -LiteralPath $dest).Hash -ne (Get-FileHash -LiteralPath $icon.FullName).Hash) {
        # same name, different content — two scan roots sharing a theme
        # folder name; suffix instead of silently overwriting
        $stem = [IO.Path]::GetFileNameWithoutExtension($icon.Name)
        $ext = [IO.Path]::GetExtension($icon.Name)
        $i = 1
        while (Test-Path -LiteralPath (Join-Path $destDir ('{0}-{1}{2}' -f $stem, $i, $ext))) { $i++ }
        $dest = Join-Path $destDir ('{0}-{1}{2}' -f $stem, $i, $ext)
    }
    if ($IconMode -eq 'hardlink') {
        # hardlink to the original (no extra disk on the same volume); any
        # refusal - cross-volume, older PowerShell, permission - falls back
        # to a real copy so the install never half-fails
        New-Item -ItemType HardLink -Path $dest -Target $icon.FullName -Force -ErrorAction SilentlyContinue | Out-Null
        if (-not (Test-Path -LiteralPath $dest)) {
            Copy-Item -LiteralPath $icon.FullName -Destination $dest -Force
        }
    } else {
        Copy-Item -LiteralPath $icon.FullName -Destination $dest -Force
    }
    $copied++
}
if ($IconMode -eq 'hardlink') {
    Write-Ok "$copied icon files hardlinked to icons\ (refusals were copied)"
} else {
    Write-Ok "$copied icon files copied to icons\"
}

# list.js mirrors list.txt as a JS array (fetch() is blocked on file:// pages)
$jsPaths = ($paths | ForEach-Object { '"' + ($_ -replace '"', '\"') + '"' }) -join ','
[IO.File]::WriteAllText((Join-Path $InstallDir 'list.js'), "window.ICON_LIST=[$jsPaths];`r`n", (New-Object System.Text.UTF8Encoding($false)))

# ---------------------------------------------------------------------------
# 4. Launcher + user PATH
# ---------------------------------------------------------------------------
$binDir = Join-Path $HOME '.local\bin'
New-Item -ItemType Directory -Path $binDir -Force | Out-Null
$launcher = Join-Path $binDir $LauncherName
$cmdLines = @(
    '@echo off',
    # UTF-8 codepage so an install path with non-ASCII characters survives
    # cmd's default OEM codepage (the .cmd itself is written as UTF-8 below)
    'chcp 65001 >nul',
    # parentheses are required: inside an array literal the comma operator
    # binds tighter than +, so an unparenthesized concatenation here is
    # parsed as three separate elements and the .cmd gets APP_DIR split
    ('set "APP_DIR=' + $InstallDir + '"'),
    'if /i "%~1"=="--file" goto file',
    'rem reuse a server that is already up on the port (e.g. the LAN webshare)',
    'curl -s -o nul http://127.0.0.1:8642/server-state.js 2>nul && goto open',
    'set "PYEXE="',
    'where pythonw >nul 2>nul && set "PYEXE=pythonw"',
    'where python >nul 2>nul && if not defined PYEXE set "PYEXE=python"',
    'if not defined PYEXE goto file',
    'start "" %PYEXE% "%APP_DIR%\server\serve.py" --dir "%APP_DIR%" --port 8642 --host 127.0.0.1 --kill-existing',
    'timeout /t 2 /nobreak >nul',
    ':open',
    'start "" "http://127.0.0.1:8642/"',
    'goto :eof',
    ':file',
    'start "" "%APP_DIR%\index.html"'
)
# UTF-8 (no BOM): -Encoding ASCII mangles non-ASCII install paths
[IO.File]::WriteAllText($launcher, ($cmdLines -join "`r`n") + "`r`n", (New-Object System.Text.UTF8Encoding($false)))
Write-Ok "Created $launcher -> starts the local server and opens http://127.0.0.1:8642/ (fengrid --file opens the plain file)"

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
try {
    & $launcher
} catch {
    Write-Warn2 "Could not launch automatically ($($_.Exception.Message))."
    Write-Info "Open this file manually: $(Join-Path $InstallDir 'index.html')"
}
Write-Ok 'Done. Quick launch any time:  fengrid'