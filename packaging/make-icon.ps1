<#
.SYNOPSIS
  Draws the PKOS app icon (a small knowledge graph on a blue rounded square) and writes
  desktop\build-resources\icon.ico (16-256 px) and icon.png (512 px). Uses only .NET System.Drawing.
#>
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing
$out = Join-Path (Split-Path -Parent $PSScriptRoot) "desktop\build-resources"
New-Item -ItemType Directory -Force $out | Out-Null

function New-IconBitmap([int]$size) {
  $bmp = New-Object System.Drawing.Bitmap $size, $size, ([System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
  $g.Clear([System.Drawing.Color]::Transparent)
  $s = $size / 512.0

  # Rounded square with a diagonal blue gradient.
  $r = 112 * $s; $pad = 16 * $s; $w = $size - 2 * $pad
  $path = New-Object System.Drawing.Drawing2D.GraphicsPath
  $path.AddArc($pad, $pad, 2 * $r, 2 * $r, 180, 90)
  $path.AddArc($pad + $w - 2 * $r, $pad, 2 * $r, 2 * $r, 270, 90)
  $path.AddArc($pad + $w - 2 * $r, $pad + $w - 2 * $r, 2 * $r, 2 * $r, 0, 90)
  $path.AddArc($pad, $pad + $w - 2 * $r, 2 * $r, 2 * $r, 90, 90)
  $path.CloseFigure()
  $rect = New-Object System.Drawing.RectangleF $pad, $pad, $w, $w
  $grad = New-Object System.Drawing.Drawing2D.LinearGradientBrush $rect, ([System.Drawing.Color]::FromArgb(255, 37, 99, 235)), ([System.Drawing.Color]::FromArgb(255, 15, 23, 42)), 45.0
  $g.FillPath($grad, $path)

  # Graph: one central node linked to four others.
  $nodes = @(@(256, 256, 62), @(140, 150, 34), @(378, 140, 30), @(388, 360, 36), @(150, 372, 30))
  $line = New-Object System.Drawing.Pen ([System.Drawing.Color]::FromArgb(200, 191, 219, 254)), ([single](18 * $s))
  $line.StartCap = [System.Drawing.Drawing2D.LineCap]::Round; $line.EndCap = [System.Drawing.Drawing2D.LineCap]::Round
  foreach ($n in $nodes[1..4]) { $g.DrawLine($line, [single](256 * $s), [single](256 * $s), [single]($n[0] * $s), [single]($n[1] * $s)) }
  $g.DrawLine($line, [single](378 * $s), [single](140 * $s), [single](388 * $s), [single](360 * $s))
  $white = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::White)
  $glow = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 147, 197, 253))
  foreach ($n in $nodes) {
    $d = 2 * $n[2] * $s
    $brush = if ($n[2] -gt 50) { $white } else { $glow }
    $g.FillEllipse($brush, [single]($n[0] * $s - $d / 2), [single]($n[1] * $s - $d / 2), [single]$d, [single]$d)
  }
  $g.Dispose()
  return $bmp
}

# PNG (electron-builder and the window icon).
$big = New-IconBitmap 512
$big.Save((Join-Path $out "icon.png"), [System.Drawing.Imaging.ImageFormat]::Png)

# ICO with PNG-compressed entries (supported since Windows Vista).
$sizes = 16, 24, 32, 48, 64, 128, 256
$images = foreach ($sz in $sizes) {
  $bmp = New-IconBitmap $sz
  $ms = New-Object System.IO.MemoryStream
  $bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
  , $ms.ToArray()
}
$fs = [System.IO.File]::Create((Join-Path $out "icon.ico"))
$bw = New-Object System.IO.BinaryWriter $fs
$bw.Write([uint16]0); $bw.Write([uint16]1); $bw.Write([uint16]$sizes.Count)
$offset = 6 + 16 * $sizes.Count
for ($i = 0; $i -lt $sizes.Count; $i++) {
  $sz = $sizes[$i]; $len = $images[$i].Length
  $bw.Write([byte]($(if ($sz -ge 256) { 0 } else { $sz }))); $bw.Write([byte]($(if ($sz -ge 256) { 0 } else { $sz })))
  $bw.Write([byte]0); $bw.Write([byte]0); $bw.Write([uint16]1); $bw.Write([uint16]32)
  $bw.Write([uint32]$len); $bw.Write([uint32]$offset)
  $offset += $len
}
foreach ($img in $images) { $bw.Write($img) }
$bw.Close()
Write-Host "icon.ico and icon.png written to $out"
