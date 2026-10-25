# Click inside the AIR desktop preview window at logical 640x960 coordinates.
#
# Why: desktop verification ("open the blacksmith, tap the item") is still the
# user's job by default, but when the user explicitly asks the agent to click,
# this drives the window without touching the phone.
#
#   powershell -ExecutionPolicy Bypass -File tools\desktop-click.ps1 -X 150 -Y 380
#   powershell -ExecutionPolicy Bypass -File tools\desktop-click.ps1 -X 150 -Y 380 -Double
#   powershell -ExecutionPolicy Bypass -File tools\desktop-click.ps1 -X 150 -Y 380 -NoClick   # move only
#
# Coordinates are in the window's client area, expressed in the 640x960 logical
# space used by every screenshot (the tool scales to physical pixels itself).

param(
    [string]$Title = 'PetHunterG preview [main]',
    [Parameter(Mandatory = $true)][int]$X,
    [Parameter(Mandatory = $true)][int]$Y,
    [int]$LogicalWidth = 640,
    [int]$LogicalHeight = 960,
    [switch]$Double,
    [switch]$NoClick
)

$ErrorActionPreference = 'Stop'

if (-not ('PetHunterClick.Win32' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Text;
using System.Runtime.InteropServices;

namespace PetHunterClick {
    public static class Win32 {
        public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);

        [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr l);
        [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
        [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr h, out RECT r);
        [DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr h, ref POINT p);
        [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
        [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
        [DllImport("user32.dll")] public static extern void mouse_event(uint flags, uint dx, uint dy, uint data, UIntPtr extra);
        [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();

        public const uint LEFTDOWN = 0x0002;
        public const uint LEFTUP = 0x0004;

        [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
        [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X, Y; }

        public static IntPtr FindByTitle(string title) {
            IntPtr found = IntPtr.Zero;
            EnumWindows((h, l) => {
                var sb = new StringBuilder(512);
                GetWindowText(h, sb, 512);
                if (sb.ToString() == title) { found = h; return false; }
                return true;
            }, IntPtr.Zero);
            return found;
        }
    }
}
'@
}

[void][PetHunterClick.Win32]::SetProcessDPIAware()

$hwnd = [PetHunterClick.Win32]::FindByTitle($Title)
if ($hwnd -eq [IntPtr]::Zero) { Write-Host "[x] window not found: $Title" -ForegroundColor Red; exit 1 }

[void][PetHunterClick.Win32]::SetForegroundWindow($hwnd)
Start-Sleep -Milliseconds 250

$rect = New-Object PetHunterClick.Win32+RECT
[void][PetHunterClick.Win32]::GetClientRect($hwnd, [ref]$rect)
$origin = New-Object PetHunterClick.Win32+POINT
[void][PetHunterClick.Win32]::ClientToScreen($hwnd, [ref]$origin)

$clientW = $rect.Right - $rect.Left
$clientH = $rect.Bottom - $rect.Top
$sx = [int]($origin.X + $X * ($clientW / [double]$LogicalWidth))
$sy = [int]($origin.Y + $Y * ($clientH / [double]$LogicalHeight))

Write-Host ("[i] client {0}x{1} at ({2},{3}); logical ({4},{5}) -> screen ({6},{7})" -f $clientW, $clientH, $origin.X, $origin.Y, $X, $Y, $sx, $sy)

[void][PetHunterClick.Win32]::SetCursorPos($sx, $sy)
Start-Sleep -Milliseconds 120
if (-not $NoClick) {
    [PetHunterClick.Win32]::mouse_event([PetHunterClick.Win32]::LEFTDOWN, 0, 0, 0, [UIntPtr]::Zero)
    Start-Sleep -Milliseconds 60
    [PetHunterClick.Win32]::mouse_event([PetHunterClick.Win32]::LEFTUP, 0, 0, 0, [UIntPtr]::Zero)
    if ($Double) {
        Start-Sleep -Milliseconds 80
        [PetHunterClick.Win32]::mouse_event([PetHunterClick.Win32]::LEFTDOWN, 0, 0, 0, [UIntPtr]::Zero)
        Start-Sleep -Milliseconds 60
        [PetHunterClick.Win32]::mouse_event([PetHunterClick.Win32]::LEFTUP, 0, 0, 0, [UIntPtr]::Zero)
    }
    Write-Host "[ok] clicked" -ForegroundColor Green
} else {
    Write-Host "[ok] moved (no click)" -ForegroundColor Green
}
