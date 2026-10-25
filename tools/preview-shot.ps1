# Capture a window (default: the AIR desktop preview) into a PNG for review.
#
# Why: the whole review loop now happens on the PC -- change code, open the ADL
# preview at 640x960, grab a screenshot, look at it. No APK, no phone.
#
#   powershell -ExecutionPolicy Bypass -File tools\preview-shot.ps1
#   powershell -ExecutionPolicy Bypass -File tools\preview-shot.ps1 -Name login
#   powershell -ExecutionPolicy Bypass -File tools\preview-shot.ps1 -Title "PetHunterG desktop preview" -Name bag-popup
#   powershell -ExecutionPolicy Bypass -File tools\preview-shot.ps1 -ClientArea   # drop the title bar
#
# Default output: docs\preview\<yyyy-MM-dd>\<HHmmss>-<Name>.png (local, git-ignored).
#
# Notes:
#   - The window is restored and brought to the foreground first; an occluded or
#     minimised window captures as garbage/black.
#   - SetProcessDPIAware() is called so the coordinates are physical pixels even
#     when Windows display scaling is not 100%.
#   - Prints a non-black ratio as a sanity check: a fully black shot is almost
#     always "window not found / not painted", not "the game is black".

param(
    [string]$Title = 'PetHunterG desktop preview',
    [string]$Name  = 'shot',
    [string]$Path  = '',
    [int]$WaitMs   = 450,
    [switch]$ClientArea,
    # 桌面窗口在 150% 缩放下会被抓成 960x1440；给 640x960 就统一缩放回去，
    # 方便不同 lane 的截图直接对比。
    [int]$Width   = 0,
    [int]$Height  = 0
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing

if (-not ('PetHunterShot.Win32' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Text;
using System.Runtime.InteropServices;

namespace PetHunterShot {
    public static class Win32 {
        // FindWindow(NULL, title) is unreliable from PowerShell (a $null string
        // argument can arrive as "" instead of NULL, which matches nothing), so
        // look the title up with EnumWindows instead.
        public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);

        [DllImport("user32.dll")]
        public static extern bool EnumWindows(EnumProc callback, IntPtr lParam);

        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        public static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int count);

        public static IntPtr FindByTitle(string title, bool contains) {
            IntPtr exact = IntPtr.Zero;
            IntPtr partial = IntPtr.Zero;
            EnumWindows((hWnd, lParam) => {
                var sb = new StringBuilder(512);
                GetWindowText(hWnd, sb, 512);
                string text = sb.ToString();
                if (text.Length == 0) return true;
                if (text == title && exact == IntPtr.Zero) {
                    exact = hWnd;
                    return false;
                }
                if (partial == IntPtr.Zero && contains &&
                    text.IndexOf(title, StringComparison.OrdinalIgnoreCase) >= 0) {
                    partial = hWnd;
                }
                return true;
            }, IntPtr.Zero);
            return exact != IntPtr.Zero ? exact : partial;
        }

        [DllImport("user32.dll")]
        public static extern bool SetForegroundWindow(IntPtr hWnd);

        [DllImport("user32.dll")]
        public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);

        [DllImport("user32.dll")]
        public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);

        [DllImport("user32.dll")]
        public static extern bool GetClientRect(IntPtr hWnd, out RECT lpRect);

        [DllImport("user32.dll")]
        public static extern bool ClientToScreen(IntPtr hWnd, ref POINT lpPoint);

        [DllImport("user32.dll")]
        public static extern bool SetProcessDPIAware();

        [StructLayout(LayoutKind.Sequential)]
        public struct RECT { public int Left, Top, Right, Bottom; }

        [StructLayout(LayoutKind.Sequential)]
        public struct POINT { public int X, Y; }
    }
}
'@
}

[void][PetHunterShot.Win32]::SetProcessDPIAware()

$hwnd = [PetHunterShot.Win32]::FindByTitle($Title, $false)
if ($hwnd -eq [IntPtr]::Zero) {
    $hwnd = [PetHunterShot.Win32]::FindByTitle($Title, $true)   # 退一步：标题包含
}
if ($hwnd -eq [IntPtr]::Zero) {
    Write-Host "[x] window title not found: '$Title'" -ForegroundColor Red
    $titles = Get-Process |
        Where-Object { $_.MainWindowTitle } |
        Select-Object -ExpandProperty MainWindowTitle -Unique |
        Sort-Object
    if ($titles) {
        Write-Host "    windows that currently have a title:" -ForegroundColor Yellow
        $titles | ForEach-Object { Write-Host "      - $_" }
    } else {
        Write-Host "    no visible window titles at all (is ADL running?)" -ForegroundColor Yellow
    }
    exit 1
}

[void][PetHunterShot.Win32]::ShowWindow($hwnd, 9)   # SW_RESTORE
[void][PetHunterShot.Win32]::SetForegroundWindow($hwnd)
Start-Sleep -Milliseconds $WaitMs

$rect = New-Object PetHunterShot.Win32+RECT
if ($ClientArea) {
    [void][PetHunterShot.Win32]::GetClientRect($hwnd, [ref]$rect)
    $origin = New-Object PetHunterShot.Win32+POINT
    $origin.X = 0; $origin.Y = 0
    [void][PetHunterShot.Win32]::ClientToScreen($hwnd, [ref]$origin)
    $x = $origin.X; $y = $origin.Y
    $w = $rect.Right - $rect.Left
    $h = $rect.Bottom - $rect.Top
} else {
    [void][PetHunterShot.Win32]::GetWindowRect($hwnd, [ref]$rect)
    $x = $rect.Left; $y = $rect.Top
    $w = $rect.Right - $rect.Left
    $h = $rect.Bottom - $rect.Top
}

if ($w -le 0 -or $h -le 0) {
    Write-Host "[x] window has no drawable area ($w x $h)" -ForegroundColor Red
    exit 1
}

if ([string]::IsNullOrWhiteSpace($Path)) {
    $root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
    $day  = Get-Date -Format 'yyyy-MM-dd'
    $stamp = Get-Date -Format 'HHmmss'
    $safe = ($Name -replace '[^\w\-]', '-')
    $Path = Join-Path $root "docs\preview\$day\$stamp-$safe.png"
}
$dir = Split-Path -Parent $Path
if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }

$bmp = New-Object System.Drawing.Bitmap($w, $h)
$gfx = [System.Drawing.Graphics]::FromImage($bmp)
try {
    $gfx.CopyFromScreen($x, $y, 0, 0, (New-Object System.Drawing.Size($w, $h)))
} finally {
    $gfx.Dispose()
}

$capturedW = $w; $capturedH = $h
if ($Width -gt 0 -and $Height -gt 0 -and ($w -ne $Width -or $h -ne $Height)) {
    $scaled = New-Object System.Drawing.Bitmap($Width, $Height)
    $sg = [System.Drawing.Graphics]::FromImage($scaled)
    try {
        $sg.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
        $sg.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
        $sg.DrawImage($bmp, 0, 0, $Width, $Height)
    } finally {
        $sg.Dispose()
    }
    $bmp.Dispose()
    $bmp = $scaled
    $w = $Width; $h = $Height
}

$bmp.Save($Path, [System.Drawing.Imaging.ImageFormat]::Png)

# cheap sanity check: sample 40x40 points, count non-black ones
$lit = 0; $total = 0
$sx = [Math]::Max(1, [int]($w / 40)); $sy = [Math]::Max(1, [int]($h / 40))
for ($yy = 0; $yy -lt $h; $yy += $sy) {
    for ($xx = 0; $xx -lt $w; $xx += $sx) {
        $total++
        $p = $bmp.GetPixel($xx, $yy)
        if (($p.R + $p.G + $p.B) -gt 36) { $lit++ }
    }
}
$bmp.Dispose()

$ratio = if ($total -gt 0) { 100.0 * $lit / $total } else { 0 }
$note = if ($capturedW -ne $w -or $capturedH -ne $h) { " (captured ${capturedW}x${capturedH}, scaled)" } else { "" }
Write-Host ("[ok] {0}  ({1}x{2}{3}, non-black {4:N1}%)" -f $Path, $w, $h, $note, $ratio) -ForegroundColor Green
if ($ratio -lt 1) {
    Write-Host "[!] almost entirely black -- window probably not painted/occluded, capture again" -ForegroundColor Yellow
}
