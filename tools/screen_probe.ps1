# Describe a screenshot as text: where the non-black content actually is.
#
# The model driving this session cannot view images, so "is the screen blank?"
# has to be answered numerically. This prints an ASCII luminance map plus the
# vertical bands that contain visible content, which is enough to tell a real
# page from a black screen with two rows of icons at the top.
#
#   powershell -File tools/screen_probe.ps1 -Path shot.png
param([Parameter(Mandatory=$true)][string]$Path)

Add-Type -AssemblyName System.Drawing
$img = [System.Drawing.Image]::FromFile($Path)
$bmp = New-Object System.Drawing.Bitmap $img
$W = $bmp.Width; $H = $bmp.Height
Write-Output ("{0}: {1}x{2}" -f (Split-Path $Path -Leaf), $W, $H)

function Lum($x, $y) {
    $p = $bmp.GetPixel($x, $y)
    return 0.299 * $p.R + 0.587 * $p.G + 0.114 * $p.B
}

# 1. overall darkness
$step = [Math]::Max(1, [Math]::Min($W, $H) / 200)
$total = 0; $dark = 0
for ($y = 0; $y -lt $H; $y += $step) {
    for ($x = 0; $x -lt $W; $x += $step) {
        $total++
        if ((Lum $x $y) -lt 12) { $dark++ }
    }
}
Write-Output ("dark samples: {0:N1}% of {1}" -f (100 * $dark / $total), $total)

# 2. content bands
$rowStep = [Math]::Max(1, $H / 240)
$runs = @()
$span = [Math]::Max(1, [int]($W / $step))
for ($y = 0; $y -lt $H; $y += $rowStep) {
    $lit = 0
    for ($x = 0; $x -lt $W; $x += $step) {
        if ((Lum $x $y) -ge 12) { $lit++ }
    }
    if ($lit -gt $span * 0.01) {
        if ($runs.Count -gt 0 -and ($y - $runs[-1][1]) -le ($rowStep * 2)) {
            $runs[-1][1] = $y
        } else {
            $runs += ,@($y, $y)
        }
    }
}
if ($runs.Count -eq 0) {
    Write-Output "no visible content at all"
} else {
    Write-Output ("content bands: {0}" -f $runs.Count)
    foreach ($r in $runs) {
        Write-Output ("  y {0,5} .. {1,5}   ({2,4:N1}% of height)" -f $r[0], $r[1], (100 * ($r[1] - $r[0]) / $H))
    }
}

# 3. ASCII map
$shades = @(' ', '.', ':', '-', '=', '+', '*', '#', '%', '@')
$rowsN = 56; $colsN = 56
Write-Output ""
Write-Output "ASCII map (@ bright, space black):"
for ($r = 0; $r -lt $rowsN; $r++) {
    $y0 = [int]($r * $H / $rowsN); $y1 = [int](($r + 1) * $H / $rowsN)
    if ($y1 -le $y0) { $y1 = $y0 + 1 }
    $line = ""
    for ($c = 0; $c -lt $colsN; $c++) {
        $x0 = [int]($c * $W / $colsN); $x1 = [int](($c + 1) * $W / $colsN)
        if ($x1 -le $x0) { $x1 = $x0 + 1 }
        $best = 0.0
        $ys = [Math]::Max(1, [int](($y1 - $y0) / 4))
        $xs = [Math]::Max(1, [int](($x1 - $x0) / 4))
        for ($yy = $y0; $yy -lt $y1; $yy += $ys) {
            for ($xx = $x0; $xx -lt $x1; $xx += $xs) {
                $v = Lum $xx $yy
                if ($v -gt $best) { $best = $v }
            }
        }
        $idx = [Math]::Min(9, [int]($best / 256 * 10))
        $line += $shades[$idx]
    }
    Write-Output $line
}

$bmp.Dispose(); $img.Dispose()