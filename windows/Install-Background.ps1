[CmdletBinding()]
param(
    [string]$Python,
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
$sourcePath = (Resolve-Path -LiteralPath $Source).Path
if (-not (Test-Path -LiteralPath (Join-Path $sourcePath 'community/background.py'))) { throw 'The worker source is missing.' }
$null = New-Item -ItemType Directory -Path $Root -Force
$rootPath = (Resolve-Path -LiteralPath $Root).Path
# A versioned source snapshot avoids running a development checkout at logon.
. (Join-Path $sourcePath 'windows/Start-Vision.ps1')
$pythonPath = if ($Python) { (Resolve-Path -LiteralPath $Python).Path } else { Get-VisionPython $rootPath }
$snapshot = Copy-VisionSource $sourcePath $rootPath
$entry = Join-Path $rootPath 'run-background.py'
$escaped = $snapshot.Replace('\', '\\').Replace("'", "\'")
$scriptText = @"
import json
import sys
from pathlib import Path
from datetime import datetime, timezone
sys.path.insert(0, '$escaped')
try:
    from community.background import main
    main()
except Exception as error:
    report = {'status': 'INCOMPLETE', 'phase': 'startup', 'error_type': type(error).__name__,
              'timeUtc': datetime.now(timezone.utc).isoformat()}
    Path(__file__).with_name('startup-failure.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    raise
"@
[IO.File]::WriteAllText($entry, $scriptText, (New-Object Text.UTF8Encoding($false)))
# pythonw runs without a console window; no PowerShell execution policy override.
$windowlessPython = Join-Path (Split-Path -Parent $pythonPath) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $windowlessPython)) { throw 'The private runtime is missing pythonw.exe.' }
$arguments = '-B "{0}" --root "{1}" --accept-contributions' -f $entry, $rootPath
# The worker uses absolute paths and does not need a scheduler working directory.
$action = New-ScheduledTaskAction -Execute $windowlessPython -Argument $arguments
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
Write-Output 'Background task registered and start requested. Registration alone does not confirm that the worker started.'
Write-Output "Check $rootPath\background-status.json for a fresh status. Startup failures may be saved in startup-failure.json."
Write-Output 'After a restart, sign into Windows to resume. Sleep and power-off suspend computation.'
