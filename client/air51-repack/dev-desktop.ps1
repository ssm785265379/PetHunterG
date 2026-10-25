# PetHunterG desktop preview (AIR ADL) -- fast iteration loop, no APK, no device
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\dev-desktop.ps1
#       Preview build\input-explore\APetHunter.swf (falls back to src\APetHunter.swf),
#       rewriting its server base URL to http://127.0.0.1:8080 so it talks to the local
#       Flask server, then open it in the AIR desktop runtime.
#
#   powershell -ExecutionPolicy Bypass -File .\dev-desktop.ps1 -Build
#       Run rebuild-client-patches.py first (FFDec), then preview the result.
#
#   powershell -ExecutionPolicy Bypass -File .\dev-desktop.ps1 -Swf build\input-explore\APetHunter-hire.swf
#       Preview a specific already-built SWF.
#
# Notes:
#   - src\*.swf is never modified; everything happens on a copy in build\desktop-dev.
#   - data\ is a directory junction to src\data (no 20+MB re-copy per run).
#   - On desktop the game talks to the local Flask server directly (no adb reverse).
#   - Known server bases are rewritten automatically:
#       http://43.173.99.241:8080      (remote build)
#       http://123.196.114.169/ ...196 (original client)
#       http://127.0.0.1:8080          (already local -> left untouched)

param(
    [string]$Swf = "",
    [switch]$Build,
    [int]$Width = 640,
    [int]$Height = 960
)

$ErrorActionPreference = 'Stop'

$root  = Split-Path -Parent $MyInvocation.MyCommand.Path
$src   = Join-Path $root 'src'
$dev   = Join-Path $root 'build\desktop-dev'
$adl   = 'D:\Tool\AIRSDKs\AIRSDK_51.4.1\bin\adl64.exe'
$patch = Join-Path $root 'patch_swf_url.py'
$localBase = 'http://127.0.0.1:8080'

if (-not (Test-Path $adl)) { throw "ADL not found: $adl" }
if (-not (Test-Path $src)) { throw "src not found: $src" }

if ($Build) {
    $rebuild = Join-Path $root 'rebuild-client-patches.py'
    Write-Host "[..] rebuilding client patches (FFDec) ..." -ForegroundColor Cyan
    & python $rebuild
    if ($LASTEXITCODE -ne 0) { throw "rebuild-client-patches.py failed (exit $LASTEXITCODE)" }
}

New-Item -ItemType Directory -Force -Path $dev | Out-Null

$dataLink = Join-Path $dev 'data'
if (-not (Test-Path $dataLink)) {
    cmd /c mklink /J "$dataLink" "$(Join-Path $src 'data')" | Out-Null
}

# pick source SWF
if (-not [string]::IsNullOrWhiteSpace($Swf)) {
    $candidate = if (Test-Path $Swf) { $Swf } else { Join-Path $root $Swf }
} else {
    $explore = Join-Path $root 'build\input-explore\APetHunter.swf'
    $candidate = if (Test-Path $explore) { $explore } else { Join-Path $src 'APetHunter.swf' }
}
if (-not (Test-Path $candidate)) { throw "SWF not found: $candidate" }

$target = Join-Path $dev 'APetHunter.swf'
Copy-Item $candidate $target -Force
Write-Host "[ok] source: $candidate" -ForegroundColor Green

# rewrite server base URL to the local Flask server
$bytes = [System.IO.File]::ReadAllBytes($target)
$ascii = [System.Text.Encoding]::ASCII.GetString($bytes)

if ($ascii.Contains($localBase)) {
    Write-Host "[ok] SWF already points at $localBase (no rewrite)" -ForegroundColor Green
} else {
    $patchArgs = @($patch, $target, $target)
    if ($ascii.Contains('http://43.173.99.241:8080')) {
        $patchArgs += @('--replace', "http://43.173.99.241:8080=$localBase", '--replace-all')
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
        & python @patchArgs
        if ($LASTEXITCODE -ne 0) { throw "patch_swf_url.py failed (exit $LASTEXITCODE)" }
        Write-Host "[ok] server base rewritten to $localBase" -ForegroundColor Green
    }
}

# desktop app descriptor (the Android one stays untouched)
$descriptor = Join-Path $dev 'PetHunter-desktop.xml'
$xml = @"
<?xml version="1.0" encoding="utf-8"?>
<application xmlns="http://ns.adobe.com/air/application/51.4">
    <id>com.lv1.hunter.dev</id>
    <versionNumber>2.7.1</versionNumber>
    <filename>PetHunterG-dev</filename>
    <name>Pet Hunter G (Desktop Dev)</name>
    <initialWindow>
        <content>APetHunter.swf</content>
        <title>PetHunterG desktop preview</title>
        <visible>true</visible>
        <width>$Width</width>
        <height>$Height</height>
        <renderMode>direct</renderMode>
        <autoOrients>false</autoOrients>
    </initialWindow>
</application>
"@
$xml | Set-Content -Path $descriptor -Encoding UTF8

Get-Process adl64 -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Milliseconds 300

$log = Join-Path $dev 'adl.log'
Start-Process -FilePath $adl -ArgumentList @('PetHunter-desktop.xml') -WorkingDirectory $dev `
    -RedirectStandardOutput $log -RedirectStandardError "$log.err"
Write-Host "[ok] preview launched (${Width}x${Height}); log: $log" -ForegroundColor Green
