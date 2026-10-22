# Builds Kiki's native Tab5 app and, unless -CompileOnly, flashes it.
#   powershell -ExecutionPolicy Bypass -File device\kiki\build.ps1 [-Port COM9] [-CompileOnly]
# Needs arduino-cli with the M5Stack board package and the libraries M5Unified, M5GFX,
# ArduinoJson and lvgl 9.6 (see ARCHITECTURE.md). The include flag lets LVGL find lv_conf.h here.
param([string]$Port = "COM9", [switch]$CompileOnly)
$ErrorActionPreference = "Stop"
$sketch = $PSScriptRoot
$cli = "C:\Program Files\Arduino CLI\arduino-cli.exe"
if (-not (Test-Path $cli)) { $cli = "arduino-cli" }
$include = "-I`"$sketch`""
$arguments = @(
  "compile", "--fqbn", "m5stack:esp32:m5stack_tab5:CDCOnBoot=cdc",
  "--build-property", "compiler.c.extra_flags=$include",
  "--build-property", "compiler.cpp.extra_flags=$include",
  $sketch
)
if (-not $CompileOnly) { $arguments += @("--upload", "--port", $Port) }
& $cli @arguments
exit $LASTEXITCODE
