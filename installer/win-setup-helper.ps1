# win-setup-helper.ps1 — install-time / uninstall-time helper for the NSIS
# Windows installer (installer/fengrid.nsi). All text-file generation lives
# here so encodings are handled by .NET ([IO.File] UTF-8, no BOM), never by
# NSIS's ANSI FileWrite.
#
# Modes:
#   scan      - generate list.txt / list.js, copy the scanned icons into
#               <InstallDir>\icons\, and write the fengrid.cmd launcher(s)
#   uninstall - stop a running fengrid web server, and remove the launcher
#               + its PATH entry only when they are ours
#
# Windows PowerShell 5.1 compatible. Exits 0 on success, non-zero on failure.

param(
    [Parameter(Mandatory = $true)][ValidateSet('scan', 'uninstall')][string]$Mode,
    [Parameter(Mandatory = $true)][string]$InstallDir,
    [string]$Roots = '',      # |-separated icon folders (paths cannot contain |)
    [switch]$Portable         # scan mode: launcher stays inside the install dir
)

$ErrorActionPreference = 'Stop'

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

if ($Mode -eq 'uninstall') {
    # stop a running fengrid web server (python ... serve.py ... 8642)
    try {
        Get-CimInstance Win32_Process -Filter "Name LIKE 'python%'" -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -match 'serve\.py' -and $_.CommandLine -match '8642' } |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    } catch { }
    # remove the standard-install launcher + its PATH entry, but only when
    # they are ours (a user's own ~/.local/bin must not be touched)
    $bin = Join-Path $HOME '.local\bin'
    $lnk = Join-Path $bin 'fengrid.cmd'
    $ours = $false
    if (Test-Path -LiteralPath $lnk) {
        try {
            if ([IO.File]::ReadAllText($lnk) -match 'fengrid launcher') { $ours = $true }
        } catch { }
    }
    if ($ours) {
        Remove-Item -LiteralPath $lnk -Force -ErrorAction SilentlyContinue
        try {
            $p = [Environment]::GetEnvironmentVariable('Path', 'User')
            if ($p) {
                $n = ($p -split ';' | Where-Object { $_ -and $_.TrimEnd('\') -ne $bin.TrimEnd('\') }) -join ';'
                if ($n -ne $p) {
                    [Environment]::SetEnvironmentVariable('Path', $n, 'User')
                    Write-Host 'PATH entry removed'
                }
            }
        } catch {
            Write-Host "PATH not updated ($($_.Exception.Message))"
        }
    }
    exit 0
}

# --- scan mode -------------------------------------------------------------
if (-not (Test-Path -LiteralPath $InstallDir -PathType Container)) {
    Write-Error "Install dir not found: $InstallDir"
    exit 1
}

$customPaths = @()
foreach ($r in ($Roots -split '\|')) {
    $p = ConvertTo-CleanPath $r
    if (-not $p) { continue }
    if (Test-Path -LiteralPath $p -PathType Container) {
        $customPaths += $p
        Write-Host "Will scan: $p"
    } else {
        Write-Host "SKIP (not a directory): $p"
    }
}
$customPaths = @($customPaths | Select-Object -Unique)

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
    Write-Error 'No icon files found in the scanned folders.'
    exit 1
}

$paths = $allIcons | ForEach-Object { $_.FullName -replace '\\', '/' }
# UTF-8 (no BOM): ASCII mangles non-ASCII icon file names
[IO.File]::WriteAllLines((Join-Path $InstallDir 'list.txt'), [string[]]$paths)
Write-Host ("list.txt written ({0} icon files)" -f $paths.Count)

# local icon tree: mirrors install.sh and the page's parseLine — a path
# containing "/icons/" is filed under its suffix after that marker
# (theme-style layouts), anything else flat as icons/<parent-dir>/<file>
Write-Host 'Copying icon files into icons\ ...'
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
        # same name, different content — suffix instead of silently overwriting
        $stem = [IO.Path]::GetFileNameWithoutExtension($icon.Name)
        $ext = [IO.Path]::GetExtension($icon.Name)
        $i = 1
        while (Test-Path -LiteralPath (Join-Path $destDir ('{0}-{1}{2}' -f $stem, $i, $ext))) { $i++ }
        $dest = Join-Path $destDir ('{0}-{1}{2}' -f $stem, $i, $ext)
    }
    Copy-Item -LiteralPath $icon.FullName -Destination $dest -Force
    $copied++
}
Write-Host ("{0} icon files copied to icons\" -f $copied)

# list.js mirrors list.txt as a JS array (fetch() is blocked on file:// pages)
$jsPaths = ($paths | ForEach-Object { '"' + ($_ -replace '"', '\"') + '"' }) -join ','
[IO.File]::WriteAllText((Join-Path $InstallDir 'list.js'), "window.ICON_LIST=[$jsPaths];`r`n", (New-Object System.Text.UTF8Encoding($false)))

# fengrid.cmd launcher (UTF-8 + chcp 65001 so non-ASCII paths survive cmd).
# The in-app copy uses %~dp0 so the folder stays movable — drop it on a
# thumbdrive and it still works.
$cmdLines = @(
    '@echo off',
    'chcp 65001 >nul',
    'rem fengrid launcher',
    'set "APP_DIR=%~dp0."',
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
$utf8 = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText((Join-Path $InstallDir 'fengrid.cmd'), ($cmdLines -join "`r`n") + "`r`n", $utf8)
Write-Host "Created $(Join-Path $InstallDir 'fengrid.cmd')"

if (-not $Portable) {
    # standard install also places the launcher on the (baked) install path
    $bin = Join-Path $HOME '.local\bin'
    New-Item -ItemType Directory -Path $bin -Force | Out-Null
    $std = @($cmdLines | ForEach-Object { if ($_ -eq 'set "APP_DIR=%~dp0."') { 'set "APP_DIR=' + $InstallDir + '"' } else { $_ } })
    [IO.File]::WriteAllText((Join-Path $bin 'fengrid.cmd'), ($std -join "`r`n") + "`r`n", $utf8)
    Write-Host "Created $(Join-Path $bin 'fengrid.cmd')"
}
exit 0
