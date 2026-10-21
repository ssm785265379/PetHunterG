# Crop a region, upscale it, and OCR it, to read small UI text.
#
# The OCR engine drops small fixed-width text at the client's native scale, so
# page identification needs a zoomed crop: this cuts the requested band, scales
# it 2x with nearest-neighbour, and hands it to tools/ocr.ps1.
#
#   powershell -File tools/ocr_crop.ps1 -Path shot.png -Y0 0 -Y1 700 [-Scale 2]
param(
    [Parameter(Mandatory=$true)][string]$Path,
    [int]$Y0 = 0,
    [int]$Y1 = 0,
    [int]$Scale = 2
)
Add-Type -AssemblyName System.Drawing
$img = [System.Drawing.Image]::FromFile($Path)
$bmp = New-Object System.Drawing.Bitmap $img
if ($Y1 -le $Y0) { $Y1 = $bmp.Height }
$h = [Math]::Min($Y1, $bmp.Height) - $Y0
$rect = New-Object System.Drawing.Rectangle 0, $Y0, $bmp.Width, $h
$crop = $bmp.Clone($rect, $bmp.PixelFormat)
$big = New-Object System.Drawing.Bitmap ($bmp.Width * $Scale), ($h * $Scale)
$g = [System.Drawing.Graphics]::FromImage($big)
$g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::NearestNeighbor
$g.DrawImage($crop, 0, 0, $big.Width, $big.Height)
$g.Dispose()
$out = [System.IO.Path]::ChangeExtension($Path, "")
$out = $out + "crop_$Y0`_$Y1.png"
$big.Save($out, [System.Drawing.Imaging.ImageFormat]::Png)
$big.Dispose(); $crop.Dispose(); $bmp.Dispose(); $img.Dispose()
Write-Output "cropped -> $out"
& "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "F:\git\PetHunterG\tools\ocr.ps1" -Path (Resolve-Path $out).Path