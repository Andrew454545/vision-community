[CmdletBinding()]
param([string]$Packet)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
# Reuse the checked private Python/source installer, without its desktop main.
. (Join-Path $PSScriptRoot 'Start-Vision.ps1')
Add-Type -AssemblyName System.Windows.Forms
if (-not $Packet) {
    $choice = New-Object System.Windows.Forms.OpenFileDialog
    $choice.Title = 'Choose your assigned VISION Scene packet'
    $choice.Filter = 'VISION Scene packet (*.json)|*.json'
    if ($choice.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { exit 0 }
    $Packet = $choice.FileName
    $choice.Dispose()
}
if (-not $env:LOCALAPPDATA) { throw 'Your private application folder could not be found.' }
$pilotRoot = Join-Path $env:LOCALAPPDATA 'vision-community\local-scene-pilot-app'
Assert-VisionRegularPath (Split-Path -Parent $pilotRoot)
Assert-VisionRegularPath $pilotRoot
[IO.Directory]::CreateDirectory($pilotRoot) | Out-Null
$pilotSource = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$pilotKitRuntime = Join-Path $pilotSource 'pilot-runtime'
if (-not (Test-Path -LiteralPath $pilotKitRuntime -PathType Container)) {
    throw 'This source checkout has no prepared processing runtime. Ask the maintainer for the complete local Scene pilot kit.'
}
Write-Host 'VISION Local Scenes uses your computer, not the project cloud.'
Write-Host 'Setup downloads private Python and about 1 GB of Scene model files from python.org and the project on GitHub.'
Write-Host 'Start retrieves imagery using your internet. Results stay here. No account, upload, search or background task is created.'
$pilotAnswer = Read-Host 'Continue with setup? Type Y to continue'
if ($pilotAnswer -notmatch '^(?i)y(es)?$') { exit 0 }
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
$pilotApp = Copy-VisionSource $pilotSource $pilotRoot
$pilotPython = Get-VisionPython $pilotRoot
$pilotRuntime = Join-Path $pilotRoot 'runtime'
& $pilotPython -B (Join-Path $pilotApp 'community\local_scene_setup.py') --kit-runtime $pilotKitRuntime --runtime-root $pilotRuntime --download-models
if ($LASTEXITCODE -ne 0) { throw 'The local Scene processing files could not be verified. Your files are kept.' }
& $pilotPython -B (Join-Path $pilotApp 'community\local_scene_ui.py') --packet $Packet --data-dir (Join-Path $pilotRoot 'results') --runtime-root $pilotRuntime
if ($LASTEXITCODE -ne 0) { throw 'The local Scene pilot stopped. Your saved work is kept.' }
