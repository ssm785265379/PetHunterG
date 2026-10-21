# Sample the screen every few seconds and print a compact fingerprint.
#
# Identifying which UI page the client is showing cannot rely on OCR alone (it
# misses small text). A cheap per-row mean-luminance signature is enough: any
# page transition shows up as a large jump, so a burst of signatures reveals the
# order info -> explore animation -> battle without needing to see images.
#
#   powershell -File tools/screen_timeline.ps1 -Prefix run1 -Count 14 -Interval 3
param(
    [string]$Prefix = "run",
    [int]$Count = 14,
    [int]$Interval = 3,
    [string]$OutDir = "F:\git\PetHunterG"
)
$adb = "F:\SoftWare\adb\adb.exe"
$serial = "24086b59"
Add-Type -AssemblyName System.Drawing

$prev = $null
for ($i = 0; $i -lt $Count; $i++) {
    $shot = "/sdcard/$Prefix`_$i.png"
    $local = Join-Path $OutDir ".tl_$Prefix`_$i.png"
    & $adb -s $serial shell screencap -p $shot 2>$null | Out-Null
    & $adb -s $serial pull $shot $local 2>$null | Out-Null
    if (-not (Test-Path $local)) { Write-Output "$i : capture failed"; continue }

    $img = [System.Drawing.Image]::FromFile($local)
    $bmp = New-Object System.Drawing.Bitmap $img
    $W = $bmp.Width; $H = $bmp.Height
    $sig = @()
    $dark = 0; $tot = 0
    for ($band = 0; $band -lt 12; $band++) {
        $y0 = [int]($band * $H / 12); $y1 = [int](($band + 1) * $H / 12)
        $sum = 0.0; $n = 0
        for ($y = $y0; $y -lt $y1; $y += 17) {
            for ($x = 0; $x -lt $W; $x += 17) {
                $p = $bmp.GetPixel($x, $y)
                $l = 0.299 * $p.R + 0.587 * $p.G + 0.114 * $p.B
                $sum += $l; $n++
                $tot++
                if ($l -lt 12) { $dark++ }
            }
        }
        $sig += [int]($sum / [Math]::Max(1, $n))
    }
    $delta = ""
    if ($prev) {
        $d = 0
        for ($k = 0; $k -lt 12; $k++) { $d += [Math]::Abs($sig[$k] - $prev[$k]) }
        $delta = "delta=$d"
    }
    Write-Output ("{0,2} t={1,2}s dark={2,4:N1}% sig={3} {4}" -f $i, ($i * $Interval), (100 * $dark / [Math]::Max(1, $tot)), ($sig -join ","), $delta)
    $prev = $sig
    $bmp.Dispose(); $img.Dispose()
    if ($i -lt $Count - 1) { Start-Sleep -Seconds $Interval }
}