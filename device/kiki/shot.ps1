# Saves what the Tab5 shows as a PNG, through kiki.ino's "shot" serial command.
#   powershell -ExecutionPolicy Bypass -File device\kiki\shot.ps1 [-Port COM9] [-Out screen.png] ["tapitem 0" "wait 1" ...]
# Commands before the shot work as in serial.ps1 ("wait n" waits n seconds). The Tab5 sends
# "SHOT w h", then each row as 0xA5 0x5A, the row number (2 bytes, little-endian) and w RGB pixels;
# the markers let this find its place again if a log line lands between rows.
[CmdletBinding(PositionalBinding = $false)]
param([string]$Port = "COM9", [string]$Out = "screen.png", [Parameter(ValueFromRemainingArguments)][string[]]$Commands)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing
Add-Type -TypeDefinition @"
public static class ShotRow {  // RGB from the Tab5 to the bitmap's BGR, one row
  public static void Copy(byte[] src, int from, byte[] dst, int to, int width) {
    for (int x = 0; x < width; x++) {
      dst[to + x * 3] = src[from + x * 3 + 2];
      dst[to + x * 3 + 1] = src[from + x * 3 + 1];
      dst[to + x * 3 + 2] = src[from + x * 3];
    }
  }
}
"@
$serial = New-Object System.IO.Ports.SerialPort $Port, 115200
$serial.DtrEnable = $false  # DTR and RTS reset the Tab5
$serial.RtsEnable = $false
$serial.ReadBufferSize = 8MB
$serial.Open()
try {
  foreach ($command in $Commands) {
    if ($command -match '^wait ([\d.]+)$') { Start-Sleep -Milliseconds ([int]([double]$Matches[1] * 1000)); continue }
    $serial.WriteLine($command)
    Start-Sleep -Milliseconds 50
  }
  $serial.DiscardInBuffer()
  $serial.WriteLine("shot")

  $data = New-Object System.IO.MemoryStream
  $chunk = New-Object byte[] 65536
  $quietSince = Get-Date
  $deadline = (Get-Date).AddSeconds(60)
  while ((Get-Date) -lt $deadline) {
    $n = if ($serial.BytesToRead) { $serial.Read($chunk, 0, $chunk.Length) } else { 0 }
    if ($n) { $data.Write($chunk, 0, $n); $quietSince = Get-Date }
    elseif ($data.Length -gt 0 -and ((Get-Date) - $quietSince).TotalMilliseconds -gt 1500) { break }
    else { Start-Sleep -Milliseconds 20 }
  }
} finally {
  $serial.Close()
}

$bytes = $data.ToArray()
$text = [System.Text.Encoding]::ASCII.GetString($bytes)
$header = [regex]::Match($text, 'SHOT (\d+) (\d+)\n')
if (-not $header.Success) { throw "no SHOT header in $($bytes.Length) bytes" }
$w = [int]$header.Groups[1].Value; $h = [int]$header.Groups[2].Value
$rowBytes = $w * 3
$bitmap = New-Object System.Drawing.Bitmap $w, $h, ([System.Drawing.Imaging.PixelFormat]::Format24bppRgb)
$lock = $bitmap.LockBits((New-Object System.Drawing.Rectangle 0, 0, $w, $h), 'WriteOnly', $bitmap.PixelFormat)
$pixels = New-Object byte[] ($lock.Stride * $h)
$pos = $header.Index + $header.Length
$found = 0
for ($row = 0; $row -lt $h; $row++) {
  $lo = $row -band 0xFF; $hi = $row -shr 8
  while ($pos + 4 + $rowBytes -le $bytes.Length -and -not ($bytes[$pos] -eq 0xA5 -and $bytes[$pos + 1] -eq 0x5A -and $bytes[$pos + 2] -eq $lo -and $bytes[$pos + 3] -eq $hi)) { $pos++ }
  if ($pos + 4 + $rowBytes -gt $bytes.Length) { break }
  [ShotRow]::Copy($bytes, $pos + 4, $pixels, $row * $lock.Stride, $w)
  $pos += 4 + $rowBytes
  $found++
}
[System.Runtime.InteropServices.Marshal]::Copy($pixels, 0, $lock.Scan0, $pixels.Length)
$bitmap.UnlockBits($lock)
$bitmap.Save((Join-Path (Get-Location) $Out), [System.Drawing.Imaging.ImageFormat]::Png)
"saved ${Out}: $found of $h rows"
