[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$Python,
    [Parameter(Mandatory=$true)][string]$Source,
    [Parameter(Mandatory=$true)][string]$Root,
    [switch]$AcceptContributions,
    [switch]$Remove
)
$ErrorActionPreference = 'Stop'
$taskName = 'VISION Community Background Indexing'
if ($Remove) {
    Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Output 'Automatic indexing removed. Saved work and account files were preserved.'
    return
}
if (-not $AcceptContributions) { throw 'AcceptContributions is required to enable unattended downloads, imagery retrieval, account creation and verified contributions.' }
$pythonPath = (Resolve-Path -LiteralPath $Python).Path
$sourcePath = (Resolve-Path -LiteralPath $Source).Path
if (-not (Test-Path -LiteralPath (Join-Path $sourcePath 'community/background.py'))) { throw 'The worker source is missing.' }
$null = New-Item -ItemType Directory -Path $Root -Force
$rootPath = (Resolve-Path -LiteralPath $Root).Path
# A versioned source snapshot avoids running a development checkout at logon.
. (Join-Path $sourcePath 'windows/Start-Vision.ps1')
$snapshot = Copy-VisionSource $sourcePath $rootPath
$entry = Join-Path $rootPath 'run-background.py'
$escaped = $snapshot.Replace('\', '\\').Replace("'", "\'")
$scriptText = "import sys`nsys.path.insert(0, '$escaped')`nfrom community.background import main`nmain()`n"
[IO.File]::WriteAllText($entry, $scriptText, (New-Object Text.UTF8Encoding($false)))
$arguments = '-B "{0}" --root "{1}" --accept-contributions' -f $entry, $rootPath
$action = New-ScheduledTaskAction -Execute $pythonPath -Argument $arguments -WorkingDirectory $rootPath
$identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$logon = New-ScheduledTaskTrigger -AtLogOn -User $identity
$recovery = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 15)
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$task = New-ScheduledTask -Action $action -Trigger @($logon, $recovery) -Settings $settings -Principal $principal `
    -Description 'Opt-in VISION contributor. Resumes after sign-in and saved checkpoints. No Codex usage. Pause using the PAUSE file in its private folder.'
Register-ScheduledTask -TaskName $taskName -InputObject $task -Force | Out-Null
Start-ScheduledTask -TaskName $taskName
Write-Output 'Automatic indexing enabled. After a restart, sign into Windows to resume. Sleep and power-off suspend computation.'
