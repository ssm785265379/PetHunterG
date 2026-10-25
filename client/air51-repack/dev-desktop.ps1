# PetHunterG desktop preview (AIR ADL) -- one window per development lane.
#
# Why lanes: backend work happens on several branches at once, each with its own
# Flask port and its own save file. Every lane gets its own ADL window, its own
# build directory and a title that names the lane, so several game windows can be
# open together and screenshots can target one of them by title.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\dev-desktop.ps1
#       main lane: port 8080, title "PetHunterG preview [main]",
#       build\desktop-dev-main\, previews build\input-explore\APetHunter.swf.
#
#   powershell -ExecutionPolicy Bypass -File .\dev-desktop.ps1 -Label b1 -Port 8081
#       b1 lane: rewrites the SWF's server base to http://127.0.0.1:8081 and opens
#       build\desktop-dev-b1\ with title "PetHunterG preview [b1]".
#
#   powershell -ExecutionPolicy Bypass -File .\dev-desktop.ps1 -Label b1 -Port 8081 -Build
#       Run rebuild-client-patches.py first (FFDec, ~40s), then open the window.
#
#   powershell -ExecutionPolicy Bypass -File .\dev-desktop.ps1 -Label c1 -Swf build\input-explore\APetHunter-bag.swf
#       Preview a specific already-built SWF in its own window.
#
# Notes:
#   - src\*.swf is never modified; everything happens on a copy under $DevDir.
#   - Only THIS lane's window is restarted (recorded in <DevDir>\adl.pid); other
#     lanes' windows are left alone. -NoKill keeps even this one.
#   - data\ is a directory junction to src\data (no 20+MB re-copy per run).
#   - Known server bases are rewritten automatically:
#       http://43.173.99.241:8080      (remote build)
#       http://127.0.0.1:8080          (already local, other port -> rewritten to -Port)
#       http://123.196.114.169/ ...196 (original client)
#   - Window must stay 640x960: the SWF stage is 640x960, other sizes shift buttons.

param(
    [string]$Swf = "",
    [switch]$Build,
    [int]$Width = 640,
    [int]$Height = 960,
    [int]$Port = 8080,
    [string]$Label = "main",
    [string]$DevDir = "",
    [switch]$NoKill,
    [int]$WaitSeconds = 15
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
$repack = Join-Path $root 'client\air51-repack'
$src = Join-Path $repack 'src'
$adl = 'D:\Tool\AIRSDKs\AIRSDK_51.4.1\bin\adl64.exe'
$patch = Join-Path $repack 'patch_swf_url.py'
$venvPython = Join-Path $root 'server\.venv\Scripts\python.exe'
$python = if (Test-Path $venvPython) { $venvPython } else { 'python' }
$localBase = "http://127.0.0.1:$Port"

$safeLabel = ($Label -replace '[^\w\-]', '-')
if ([string]::IsNullOrWhiteSpace($DevDir)) {
    $dev = Join-Path $repack "build\desktop-dev-$safeLabel"
} else {
    $dev = if ([System.IO.Path]::IsPathRooted($DevDir)) { $DevDir } else { Join-Path $repack $DevDir }
}
$title = "PetHunterG preview [$safeLabel]"

if (-not (Test-Path $adl)) { throw "ADL not found: $adl" }
if (-not (Test-Path $src)) { throw "src not found: $src" }

if ($Build) {
    $rebuild = Join-Path $repack 'rebuild-client-patches.py'
    Write-Host "[..] rebuilding client patches (FFDec) ..." -ForegroundColor Cyan
    & $python $rebuild
    if ($LASTEXITCODE -ne 0) { throw "rebuild-client-patches.py failed (exit $LASTEXITCODE)" }
}

New-Item -ItemType Directory -Force -Path $dev | Out-Null

$dataLink = Join-Path $dev 'data'
if (-not (Test-Path $dataLink)) {
    cmd /c mklink /J "$dataLink" "$(Join-Path $src 'data')" | Out-Null
}

# pick source SWF
if (-not [string]::IsNullOrWhiteSpace($Swf)) {
    $candidate = if (Test-Path $Swf) { $Swf } else { Join-Path $repack $Swf }
} else {
    $explore = Join-Path $repack 'build\input-explore\APetHunter.swf'
    $candidate = if (Test-Path $explore) { $explore } else { Join-Path $src 'APetHunter.swf' }
}
if (-not (Test-Path $candidate)) { throw "SWF not found: $candidate" }

$target = Join-Path $dev 'APetHunter.swf'
Copy-Item $candidate $target -Force
Write-Host "[ok] lane=$safeLabel port=$Port source: $candidate" -ForegroundColor Green

# rewrite server base URL to this lane's Flask port
$bytes = [System.IO.File]::ReadAllBytes($target)
$ascii = [System.Text.Encoding]::ASCII.GetString($bytes)

if ($ascii.Contains($localBase)) {
    Write-Host "[ok] SWF already points at $localBase (no rewrite)" -ForegroundColor Green
} else {
    $patchArgs = @($patch, $target, $target)
    if ($ascii.Contains('http://43.173.99.241:8080')) {
        $patchArgs += @('--replace', "http://43.173.99.241:8080=$localBase", '--replace-all')
    } elseif ($ascii.Contains('http://127.0.0.1:8080')) {
        $patchArgs += @('--replace', "http://127.0.0.1:8080=$localBase", '--replace-all')
    } else {
        $originals = @(
            'http://123.196.114.169/=http://127.0.0.1:8080/',
            'http://123.196.114.177=http://127.0.0.1:8080',
            'http://123.196.114.185=http://127.0.0.1:8080',
            'http://123.196.114.196=http://127.0.0.1:8080'
        )
        $found = 0
        foreach ($o in $originals) {
            $old = $o.Split('=')[0]
            if ($ascii.Contains($old)) { $patchArgs += @('--replace', $o); $found++ }
        }
        if ($found -eq 0) {
            $ips = [regex]::Matches($ascii, '\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(:\d+)?') |
                ForEach-Object { $_.Value } | Sort-Object -Unique
            Write-Host "[warn] unknown server base in SWF; not rewritten. IPs seen: $($ips -join ', ')" -ForegroundColor Yellow
            $patchArgs = @()
        }
    }
    if ($patchArgs.Count -gt 0) {
        & $python @patchArgs
        if ($LASTEXITCODE -ne 0) { throw "patch_swf_url.py failed (exit $LASTEXITCODE)" }
        Write-Host "[ok] server base rewritten to $localBase" -ForegroundColor Green
    }
}

# desktop app descriptor (the Android one stays untouched)
# The id must differ per lane: ADL is single-instance per application id and a
# second process would just forward its launch to the first window and exit.
$descriptor = Join-Path $dev 'PetHunter-desktop.xml'
$xml = @"
<?xml version="1.0" encoding="utf-8"?>
<application xmlns="http://ns.adobe.com/air/application/51.4">
    <id>com.lv1.hunter.dev.$safeLabel</id>
    <versionNumber>2.7.1</versionNumber>
    <filename>PetHunterG-dev</filename>
    <name>Pet Hunter G (Desktop Dev)</name>
    <initialWindow>
        <content>APetHunter.swf</content>
        <title>$title</title>
        <visible>true</visible>
        <width>$Width</width>
        <height>$Height</height>
        <renderMode>direct</renderMode>
        <autoOrients>false</autoOrients>
    </initialWindow>
</application>
"@
$xml | Set-Content -Path $descriptor -Encoding UTF8

# restart only THIS lane's window (pid recorded per DevDir)
$pidFile = Join-Path $dev 'adl.pid'
if (-not $NoKill -and (Test-Path $pidFile)) {
    $oldPid = (Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    if ($oldPid -and ($oldPid -as [int])) {
        $old = Get-Process -Id ([int]$oldPid) -ErrorAction SilentlyContinue
        if ($old -and $old.ProcessName -eq 'adl64') {
            Stop-Process -Id $old.Id -Force -ErrorAction SilentlyContinue
            Start-Sleep -Milliseconds 300
        }
    }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

$log = Join-Path $dev 'adl.log'
$proc = Start-Process -FilePath $adl -ArgumentList @('PetHunter-desktop.xml') -WorkingDirectory $dev `
    -RedirectStandardOutput $log -RedirectStandardError "$log.err" -PassThru
Set-Content -Path $pidFile -Value $proc.Id -Encoding ascii

# wait until the window shows up under the expected title
$deadline = (Get-Date).AddSeconds($WaitSeconds)
$seen = $false
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 400
    $p = Get-Process -Id $proc.Id -ErrorAction SilentlyContinue
    if (-not $p) { break }
    if ($p.MainWindowTitle -eq $title) { $seen = $true; break }
}
if (-not $seen) {
    $p = Get-Process -Id $proc.Id -ErrorAction SilentlyContinue
    $actual = if ($p) { $p.MainWindowTitle } else { '<process exited>' }
    Write-Host "[!] window title not confirmed after ${WaitSeconds}s (actual: '$actual'); check $log.err" -ForegroundColor Yellow
} else {
    Write-Host "[ok] window ready: $title (pid $($proc.Id), ${Width}x${Height})" -ForegroundColor Green
}

Write-Host "LANE=$safeLabel PORT=$Port PID=$($proc.Id) TITLE=$title DEV=$dev"
