# Sends test commands to Kiki's Tab5 program over USB serial and prints its log.
#   powershell -ExecutionPolicy Bypass -File device\kiki\serial.ps1 [-Port COM9] [-Seconds 10] "tapitem 0" "wait 2" "tapitem 0"
# Each argument is a command from kiki.ino's handleSerialTestCommands, or "wait n" (seconds).
# The log is printed for -Seconds after the last command.
[CmdletBinding(PositionalBinding = $false)]
param([string]$Port = "COM9", [int]$Seconds = 10, [Parameter(ValueFromRemainingArguments)][string[]]$Commands)
$ErrorActionPreference = "Stop"
$serial = New-Object System.IO.Ports.SerialPort $Port, 115200
$serial.DtrEnable = $false  # DTR and RTS reset the Tab5
$serial.RtsEnable = $false
$serial.NewLine = "`n"
$serial.Open()

function Show-LogFor([double]$secs) {
  $until = (Get-Date).AddSeconds($secs)
  while ((Get-Date) -lt $until) {
    $text = $serial.ReadExisting()
    if ($text) { Write-Host -NoNewline $text }
    Start-Sleep -Milliseconds 50
  }
}

try {
  foreach ($command in $Commands) {
    if ($command -match '^wait ([\d.]+)$') { Show-LogFor ([double]$Matches[1]); continue }
    $serial.WriteLine($command)
    Show-LogFor 0.05
  }
  Show-LogFor $Seconds
} finally {
  $serial.Close()
}
