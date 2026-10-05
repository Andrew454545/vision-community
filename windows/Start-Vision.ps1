[CmdletBinding()]
param(
    [switch]$AcceptDownloadsAndLiveImagery,
    [switch]$PrepareOnly,
    [switch]$BackgroundControls
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$script:VisionPythonVersion = '3.14.7'
$script:VisionPythonUrl = 'https://www.python.org/ftp/python/3.14.7/python-3.14.7-embed-amd64.zip'
$script:VisionPythonHash = 'd297e5ff019966817ad8502465176139f2d3d840fa4ed84b13bed399a6ab1f15'
$script:VisionUtf8 = New-Object System.Text.UTF8Encoding($false)

function Get-VisionFileHash([string]$Path) {
    # Works even when a parent PowerShell Core process supplies a module path
    # that hides Windows PowerShell's Get-FileHash cmdlet.
    $stream = [IO.File]::OpenRead($Path)
    $hasher = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($hasher.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
    finally { $hasher.Dispose(); $stream.Dispose() }
}

function Write-VisionJson([string]$Path, $Value) {
    [IO.File]::WriteAllText($Path, ($Value | ConvertTo-Json -Depth 10), $script:VisionUtf8)
}

function Assert-VisionRegularPath([string]$Path) {
    if (Test-Path -LiteralPath $Path) {
        $item = Get-Item -LiteralPath $Path -Force
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw 'VISION cannot use a linked application folder. Choose a regular local folder.'
        }
    }
}

function Get-VisionSourceFiles([string]$Source) {
    # Only named public source and fixture files enter the private app snapshot.
    # Never copy a whole checkout, .git, accounts, databases, logs or local data.
    $modules = @('__init__', 'admin', 'all_locations_full', 'all_locations_tail',
        'background', 'bootstrap', 'catalog', 'contribute', 'delivery', 'desktop', 'features', 'four_view',
        'indexed_local', 'local_search', 'measure', 'mma', 'mma_cloud', 'object_index', 'work_plan',
        'pano', 'parts', 'pc_canary', 'prompt', 'rank', 'scene_pipeline', 'scene_quality', 'search',
        'seal_index', 'segments', 'send_mma', 'server', 'service', 'source', 'store', 'submission_outbox',
        'verify', 'vision_handoff', 'vision_index', 'process_owner', 'worker')
    $relative = @($modules | ForEach-Object { 'community/{0}.py' -f $_ })
    $relative += @('community/runtime_manifest.json', 'community/country-names.txt',
        'community/desktop_web/index.html', 'community/desktop_web/style.css', 'community/desktop_web/app.js',
        'calibration/run_windows.py', 'calibration/quality.py', 'calibration/synthetic_canary.py')
    $relative += @('checksums.json', 'canary-112.tsv', 'fixture-1024.tsv', 'fixture-manifest.json',
        'generation-evidence.json', 'historical-reference.i8', 'local-vision-observation.json',
        'record-hashes.json') | ForEach-Object { "calibration/gen4-v1/$_" }
    Assert-VisionRegularPath $Source
    $required = @('community/desktop.py', 'community/work_plan.py', 'community/object_index.py', 'community/bootstrap.py', 'community/vision_index.py', 'community/process_owner.py',
        'community/runtime_manifest.json', 'community/desktop_web/index.html', 'community/submission_outbox.py', 'community/delivery.py',
        'calibration/run_windows.py', 'calibration/quality.py', 'calibration/synthetic_canary.py', 'calibration/gen4-v1/checksums.json')
    foreach ($name in $relative | Sort-Object -Unique) {
        $path = Join-Path $Source $name
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            if ($required -contains $name) { throw 'The VISION source download is incomplete. Extract the complete project ZIP and try again.' }
            continue
        }
        $parent = Split-Path -Parent $path
        while ($parent.Length -ge $Source.Length) {
            Assert-VisionRegularPath $parent
            if ($parent -eq $Source) { break }
            $parent = Split-Path -Parent $parent
        }
        Assert-VisionRegularPath $path
        [pscustomobject]@{ Relative = $name; Path = $path; Sha256 = (Get-VisionFileHash $path) }
    }
}

function Copy-VisionSource([string]$Source, [string]$Root) {
    $files = @(Get-VisionSourceFiles $Source)
    $inventory = ($files | ForEach-Object { $_.Relative + ':' + $_.Sha256 }) -join "`n"
    $hasher = [Security.Cryptography.SHA256]::Create()
    try { $hash = [BitConverter]::ToString($hasher.ComputeHash($script:VisionUtf8.GetBytes($inventory))).Replace('-', '').ToLowerInvariant() }
    finally { $hasher.Dispose() }
    $apps = Join-Path $Root 'apps'
    Assert-VisionRegularPath $apps
    [IO.Directory]::CreateDirectory($apps) | Out-Null
    $target = Join-Path $apps $hash
    Assert-VisionRegularPath $target
    if (-not (Test-Path -LiteralPath $target)) {
        $stage = Join-Path $apps ('staging-' + [guid]::NewGuid().ToString('N'))
        [IO.Directory]::CreateDirectory($stage) | Out-Null
        foreach ($file in $files) {
            $destination = Join-Path $stage $file.Relative
            [IO.Directory]::CreateDirectory((Split-Path -Parent $destination)) | Out-Null
            Copy-Item -LiteralPath $file.Path -Destination $destination
            if ((Get-VisionFileHash $destination) -ne $file.Sha256) {
                throw 'The project files changed during setup. Close other setup windows and try again.'
            }
        }
        Write-VisionJson (Join-Path $stage 'source-inventory.json') @{ sha256 = $hash; files = @($files | Select-Object Relative, Sha256) }
        # Both checked paths are children of the same private apps directory.
        Move-Item -LiteralPath $stage -Destination $target
    }
    foreach ($file in $files) {
        $path = Join-Path $target $file.Relative
        Assert-VisionRegularPath $path
        if (-not (Test-Path -LiteralPath $path -PathType Leaf) -or
            (Get-VisionFileHash $path) -ne $file.Sha256) {
            throw 'A private VISION application file failed its check. It was not started; please share the setup report with the maintainer.'
        }
    }
    $snapshotItems = @(Get-ChildItem -LiteralPath $target -Recurse -Force)
    if (@($snapshotItems | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count -or
        @($snapshotItems | Where-Object { -not $_.PSIsContainer }).Count -ne $files.Count + 1) {
        throw 'The private application snapshot contains unexpected files. It was not started.'
    }
    return $target
}

function Test-VisionPythonFiles([string]$Archive, [string]$Directory) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    Assert-VisionRegularPath $Directory
    $zip = [IO.Compression.ZipFile]::OpenRead($Archive)
    try {
        $expectedFiles = 0
        foreach ($entry in $zip.Entries) {
            if ([string]::IsNullOrEmpty($entry.Name)) { continue }
            # The official embedded distribution is flat; reject nested paths.
            if ($entry.FullName -ne $entry.Name -or $entry.Name -match '[:\\/]') { throw 'The Python archive contains an unexpected path.' }
            $path = Join-Path $Directory $entry.Name
            Assert-VisionRegularPath $path
            if (-not (Test-Path -LiteralPath $path -PathType Leaf) -or (Get-Item -LiteralPath $path).Length -ne $entry.Length) { return $false }
            $stream = $entry.Open()
            $hasher = [Security.Cryptography.SHA256]::Create()
            try { $expected = [BitConverter]::ToString($hasher.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
            finally { $hasher.Dispose(); $stream.Dispose() }
            if ((Get-VisionFileHash $path) -ne $expected) { return $false }
            $expectedFiles += 1
        }
        if (@(Get-ChildItem -LiteralPath $Directory -Force).Count -ne $expectedFiles) { return $false }
        return $true
    } finally { $zip.Dispose() }
}

function Get-VisionPython([string]$Root) {
    $downloads = Join-Path $Root 'downloads'
    Assert-VisionRegularPath $downloads
    [IO.Directory]::CreateDirectory($downloads) | Out-Null
    $archive = Join-Path $downloads ('python-' + $script:VisionPythonVersion + '-embed-amd64.zip')
    Assert-VisionRegularPath $archive
    if (-not (Test-Path -LiteralPath $archive -PathType Leaf)) {
        $partial = $archive + '.' + [guid]::NewGuid().ToString('N') + '.partial'
        Write-Host 'Downloading the small private Python runtime...'
        $ProgressPreference = 'SilentlyContinue'
        Invoke-WebRequest -UseBasicParsing -Uri $script:VisionPythonUrl -OutFile $partial
        if ((Get-VisionFileHash $partial) -ne $script:VisionPythonHash) {
            throw 'The Python download failed its checksum check. Nothing from it was executed. The failed download and report were kept.'
        }
        Move-Item -LiteralPath $partial -Destination $archive
    }
    if ((Get-VisionFileHash $archive) -ne $script:VisionPythonHash) {
        throw 'The saved Python download failed its checksum check. It was not executed; please share the setup report with the maintainer.'
    }
    $pythonParent = Join-Path $Root 'python'
    Assert-VisionRegularPath $pythonParent
    [IO.Directory]::CreateDirectory($pythonParent) | Out-Null
    $pythonDir = Join-Path $pythonParent ($script:VisionPythonVersion + '-' + $script:VisionPythonHash.Substring(0, 16))
    if (-not (Test-Path -LiteralPath $pythonDir)) {
        $stage = Join-Path $pythonParent ('staging-' + [guid]::NewGuid().ToString('N'))
        Expand-Archive -LiteralPath $archive -DestinationPath $stage
        if (-not (Test-VisionPythonFiles $archive $stage)) { throw 'The private Python files failed verification. They were not executed.' }
        Move-Item -LiteralPath $stage -Destination $pythonDir
    }
    if (-not (Test-VisionPythonFiles $archive $pythonDir)) { throw 'A private Python file failed verification. It was not executed; please share the setup report with the maintainer.' }
    Write-VisionJson (Join-Path $Root 'python-provenance.json') @{ version = $script:VisionPythonVersion; url = $script:VisionPythonUrl; sha256 = $script:VisionPythonHash }
    return (Join-Path $pythonDir 'python.exe')
}

function Open-VisionExisting([string]$Root) {
    $path = Join-Path $Root 'instance.json'
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return $false }
    try {
        $instance = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
        $uri = [Uri]$instance.url
        if ($uri.Scheme -ne 'http' -or $uri.Host -ne '127.0.0.1' -or $uri.AbsolutePath -ne '/' -or
            $uri.Port -lt 1 -or $uri.Fragment -notmatch '^#[A-Za-z0-9_-]{32,128}$') { return $false }
        $process = Get-Process -Id ([int]$instance.pid) -ErrorAction Stop
        $prefix = [IO.Path]::GetFullPath((Join-Path $Root 'python')).TrimEnd('\') + '\'
        if (-not $process.Path.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase) -or
            [IO.Path]::GetFileName($process.Path) -ne 'python.exe') { return $false }
        Start-Process -FilePath $instance.url
        return $true
    } catch { return $false }
}

function Start-Vision {
    $root = $null
    $guard = $null
    try {
        if (-not [Environment]::Is64BitProcess -or $env:PROCESSOR_ARCHITECTURE -ne 'AMD64' -or
            ($env:PROCESSOR_ARCHITEW6432 -and $env:PROCESSOR_ARCHITEW6432 -ne 'AMD64')) {
            throw 'This starter supports native 64-bit Intel or AMD Windows PCs. ARM and 32-bit computers are not supported.'
        }
        $processors = @(Get-CimInstance Win32_Processor)
        if (-not $processors.Count -or @($processors | Where-Object { $_.Architecture -ne 9 }).Count) {
            throw 'This starter requires an Intel or AMD Windows PC running native 64-bit Windows.'
        }
        if (-not $env:LOCALAPPDATA) { throw 'Your private application folder could not be found.' }
        $root = Join-Path $env:LOCALAPPDATA 'vision-community\desktop'
        Assert-VisionRegularPath (Split-Path -Parent $root)
        Assert-VisionRegularPath $root
        [IO.Directory]::CreateDirectory($root) | Out-Null
        if ($BackgroundControls) {
            & (Join-Path $PSScriptRoot 'Background-Control.ps1')
            return 0
        }
        if (-not $PrepareOnly -and (Open-VisionExisting $root)) { return 0 }
        try { $guard = [IO.File]::Open((Join-Path $root 'launcher.lock'), [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None) }
        catch { Write-Host 'VISION setup is already running. Please use its existing window and wait for setup to finish.'; return 0 }
        $consentPath = Join-Path $root 'download-consent.json'
        if (-not $AcceptDownloadsAndLiveImagery -and -not (Test-Path -LiteralPath $consentPath -PathType Leaf)) {
            Write-Host 'VISION will download private Python and about 1 GB of processing files from python.org and this project on GitHub.'
            Write-Host 'When you choose to test this PC or process locations, VISION retrieves live imagery using your internet connection.'
            Write-Host 'Nothing is installed for other applications. Setup creates no account and starts no indexing.'
            Write-Host 'You will choose account, testing and contribution actions in the VISION window.'
            $answer = Read-Host 'Continue with these downloads and live imagery when requested? Type Y to continue'
            if ($answer -notmatch '^(?i)y(es)?$') { Write-Host 'Setup cancelled. Nothing was downloaded.'; return 0 }
        }
        Write-VisionJson $consentPath @{ accepted = $true; version = 1; timeUtc = [DateTime]::UtcNow.ToString('o') }
        $drive = Get-PSDrive -Name ([IO.Path]::GetPathRoot($root).Substring(0, 1))
        if ($drive.Free -lt 3GB) { throw 'Please free at least 3 GB on the local drive, then start VISION again.' }
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
        $source = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
        $app = Copy-VisionSource $source $root
        $python = Get-VisionPython $root
        $arguments = @('-B', (Join-Path $app 'community\desktop.py'), '--root', $root)
        if ($PrepareOnly) { $arguments += '--prepare-only' } else { $arguments += '--prepare' }
        $guard.Dispose(); $guard = $null
        Write-Host 'Opening VISION. The first setup download can take a few minutes.'
        & $python @arguments
        if ($LASTEXITCODE -ne 0) { throw 'VISION stopped before it could finish. Its local diagnostic information was kept.' }
        return 0
    } catch {
        $message = $_.Exception.Message
        if ($root -and (Test-Path -LiteralPath $root -PathType Container)) {
            Write-VisionJson (Join-Path $root 'setup-failure.json') @{ status = 'INCOMPLETE'; message = $message; timeUtc = [DateTime]::UtcNow.ToString('o') }
            Write-Host "Diagnostic folder: $root"
        }
        Write-Host "VISION could not start: $message"
        return 1
    } finally {
        if ($guard) { $guard.Dispose() }
    }
}

# Dot-sourcing exposes the verification helpers to offline tests only.
if ($MyInvocation.InvocationName -ne '.') { exit (Start-Vision) }
