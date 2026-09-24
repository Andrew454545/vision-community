[CmdletBinding()]
param(
    [switch]$AcceptDownloadsAndLiveImagery,
    [switch]$PrepareOnly,
    [switch]$BootstrapOnly
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if (-not $AcceptDownloadsAndLiveImagery) {
    throw 'Read calibration/START-HERE.md. Downloads and fixture-only live imagery require -AcceptDownloadsAndLiveImagery.'
}
if (-not [Environment]::Is64BitProcess -or $env:PROCESSOR_ARCHITECTURE -ne 'AMD64') {
    throw 'This test requires native 64-bit Windows on an Intel/AMD x86-64 PC. ARM and 32-bit sessions are not supported.'
}
$source = Split-Path -Parent $PSScriptRoot
$testRoot = Join-Path $env:LOCALAPPDATA ('vision-community-calibration\' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0,8))
foreach ($cloudRoot in @($env:OneDrive, $env:OneDriveCommercial, $env:OneDriveConsumer)) {
    if ($cloudRoot -and $testRoot.StartsWith($cloudRoot.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'The calibration directory must not be inside OneDrive.'
    }
}
New-Item -ItemType Directory -Path $testRoot | Out-Null
$utf8 = New-Object System.Text.UTF8Encoding($false)
function Write-JsonFile($Path, $Value) {
    [IO.File]::WriteAllText($Path, ($Value | ConvertTo-Json -Depth 12), $utf8)
}
Write-Host 'VISION scene calibration: no account or recovery code is needed.'
Write-Host 'This downloads about 1 GB of runtime/model assets plus live imagery, and performs three full runs.'
Write-Host "All temporary files and results stay here: $testRoot"

try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $machine = @{ architecture = $env:PROCESSOR_ARCHITECTURE; powershell_version = $PSVersionTable.PSVersion.ToString() }
    try {
        $os = Get-CimInstance Win32_OperatingSystem
        $machine.os = @{ caption = $os.Caption; version = $os.Version; build = $os.BuildNumber }
        $cpus = @(Get-CimInstance Win32_Processor)
        $machine.cpu = @($cpus | Select-Object Name, NumberOfCores, NumberOfLogicalProcessors)
        $machine.sockets = $cpus.Count
        $machine.ram_bytes = (Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory
        $machine.gpu = @(Get-CimInstance Win32_VideoController | Select-Object Name, DriverVersion)
    } catch {
        $machine.hardware_details = 'NOT_ATTESTED'
    }
    Write-JsonFile (Join-Path $testRoot 'machine.json') $machine
    $drive = Get-PSDrive -Name ([IO.Path]::GetPathRoot($testRoot).Substring(0,1))
    if ($drive.Free -lt 3GB) { throw 'Please free at least 3 GB on the local drive before starting.' }

    # Application-local Python, pinned from python.org; no PATH, registry or system installation.
    $pythonUrl = 'https://www.python.org/ftp/python/3.14.7/python-3.14.7-embed-amd64.zip'
    $pythonHash = 'd297e5ff019966817ad8502465176139f2d3d840fa4ed84b13bed399a6ab1f15'
    $pythonZip = Join-Path $testRoot 'python-embed.zip'
    Write-Host 'Preparing a private copy of Python. You do not need to install it yourself.'
    $ProgressPreference = 'SilentlyContinue'
    Invoke-WebRequest -UseBasicParsing -Uri $pythonUrl -OutFile $pythonZip
    if ((Get-FileHash $pythonZip -Algorithm SHA256).Hash.ToLowerInvariant() -ne $pythonHash) {
        throw 'The Python download did not match its published checksum. Nothing from it was executed.'
    }
    $pythonDir = Join-Path $testRoot 'python'
    Expand-Archive -LiteralPath $pythonZip -DestinationPath $pythonDir
    $python = Join-Path $pythonDir 'python.exe'
    Write-JsonFile (Join-Path $testRoot 'python-provenance.json') @{ url = $pythonUrl; sha256 = $pythonHash }
    if ($BootstrapOnly) {
        # CI exercises actual embedded Python import/isolation and fixture validation without inference or large assets.
        $smoke = "import runpy; m=runpy.run_path(r'" + (Join-Path $PSScriptRoot 'run_windows.py') + "'); m['verify_fixture'](); print('EMBEDDED_PYTHON_FIXTURE_SMOKE_OK')"
        & $python -B -c $smoke
        if ($LASTEXITCODE -ne 0) { throw 'Embedded Python smoke check failed.' }
        Write-Host 'Bootstrap and fixture verification passed. No imagery was retrieved.'
        exit 0
    }
    $arguments = @('-B', (Join-Path $PSScriptRoot 'run_windows.py'), '--root', $testRoot, '--allow-downloads')
    if ($PrepareOnly) { $arguments += '--prepare-only' }
    else { $arguments += '--allow-live-imagery' }
    & $python @arguments
    if ($LASTEXITCODE -ne 0) { throw 'The calibration stopped; inspect the return ZIP and its report.' }
    Write-Host 'Finished. Give pc-calibration-results.zip and its SHA-256 file to Andrew.'
    Write-Host 'This experiment does not automatically approve the PC for contributions.'
} catch {
    $message = $_.Exception.Message.Replace($testRoot, '$TEST_ROOT').Replace($env:USERPROFILE, '$USER_HOME')
    Write-JsonFile (Join-Path $testRoot 'setup-failure.json') @{ status = 'INCOMPLETE'; error = $message }
    $returnZip = Join-Path $testRoot 'pc-calibration-results.zip'
    if (-not (Test-Path -LiteralPath $returnZip)) {
        $evidence = @((Join-Path $testRoot 'setup-failure.json'))
        if (Test-Path (Join-Path $testRoot 'machine.json')) { $evidence += (Join-Path $testRoot 'machine.json') }
        Compress-Archive -LiteralPath $evidence -DestinationPath $returnZip
        [IO.File]::WriteAllText(($returnZip + '.sha256.txt'), (Get-FileHash $returnZip -Algorithm SHA256).Hash.ToLowerInvariant(), $utf8)
    }
    Write-Host "Stopped: $message"
    Write-Host "Give Andrew this failure evidence: $returnZip"
    exit 1
}
