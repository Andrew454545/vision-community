[CmdletBinding()]
param([Parameter(Mandatory=$true)][ValidatePattern('^[a-f0-9]{40}$')][string]$Revision,
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-f0-9]{64}$')][string]$InventoryHash,
    [Parameter(Mandatory=$true)][ValidateRange(1,2147483647)][int]$WaitPid)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$base = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Programs\VISION Community'
$program = Join-Path $base $Revision.Substring(0,16)
$project = Join-Path $program 'project'
$executable = Join-Path $program 'VISION.exe'
function Assert-Plain([string]$Path) {
    while ($Path) {
        if ((Test-Path -LiteralPath $Path) -and ((Get-Item -LiteralPath $Path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'linked_program_path' }
        $Path = Split-Path -Parent $Path
    }
}
try {
    Assert-Plain $program
    $waiting = Get-Process -Id $WaitPid -ErrorAction SilentlyContinue
    if ($waiting) {
        if ($waiting.MainModule.FileName -ne $executable -or -not $waiting.WaitForExit(30000)) { throw 'application_still_running' }
    }
    $inventory = Join-Path $project 'release-inventory.json'
    Assert-Plain $inventory
    if ((Get-FileHash -LiteralPath $inventory -Algorithm SHA256).Hash.ToLowerInvariant() -ne $InventoryHash) { throw 'changed_inventory' }
    $value = Get-Content -LiteralPath $inventory -Raw | ConvertFrom-Json
    if ($value.sourceRevision -ne $Revision) { throw 'changed_revision' }
    foreach ($file in $value.files.PSObject.Properties) {
        $path = Join-Path $project $file.Name
        Assert-Plain $path
        if ((Get-Item -LiteralPath $path).Length -ne $file.Value.bytes -or (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $file.Value.sha256) { throw 'changed_program_file' }
    }
    # Walk without following redirected children; unknown files are preserved.
    $pending = New-Object 'Collections.Generic.Stack[string]'; $pending.Push($project)
    while ($pending.Count) {
        foreach ($entry in Get-ChildItem -LiteralPath $pending.Pop() -Force) {
            Assert-Plain $entry.FullName
            if ($entry.PSIsContainer) { $pending.Push($entry.FullName) }
            else {
                $relative = $entry.FullName.Substring($project.Length + 1).Replace('\','/')
                if ($relative -ne 'release-inventory.json' -and -not $value.files.PSObject.Properties[$relative]) { throw 'unfamiliar_program_file' }
            }
        }
    }
    $unknown = @(Get-ChildItem -LiteralPath $program -Force | Where-Object { $_.Name -notin @('project','VISION.exe') })
    if ($unknown.Count) { throw 'unfamiliar_program_file' }
    # Existing ownership/handover guards refuse an active batch or another task.
    . (Join-Path $project 'windows\Background-Control.ps1')
    $privateRoot = Get-VisionControlRoot ''
    & (Join-Path $project 'windows\Install-Background.ps1') -Remove -Source $project -Root $privateRoot
    $shell = New-Object -ComObject WScript.Shell
    $menu = Join-Path ([Environment]::GetFolderPath('Programs')) 'VISION Community'
    foreach ($link in @((Join-Path ([Environment]::GetFolderPath('DesktopDirectory')) 'VISION Community.lnk'),
        (Join-Path $menu 'VISION Community.lnk'),(Join-Path $menu 'Automatic processing.lnk'))) {
        Assert-Plain $link
        if ((Test-Path -LiteralPath $link) -and $shell.CreateShortcut($link).TargetPath -eq $executable) { Remove-Item -LiteralPath $link }
    }
    $key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\VISIONCommunity'
    if ((Test-Path -LiteralPath $key) -and (Get-ItemProperty -LiteralPath $key).InstallLocation -eq $program) { Remove-Item -LiteralPath $key }
    Remove-Item -LiteralPath $program -Recurse
    # Remove this temporary helper after reading; the private worker folder stays.
    Remove-Item -LiteralPath $PSCommandPath
    Remove-Item -LiteralPath $PSScriptRoot
} catch {
    Add-Type -AssemblyName System.Windows.Forms
    [Windows.Forms.MessageBox]::Show('VISION could not be removed safely. Its application and your saved work are kept. Finish any active batch, then retry or ask the maintainer for help.','VISION Community') | Out-Null
    exit 1
}
