[CmdletBinding()]
param(
    [string]$Python,
    [Parameter(Mandatory=$true)][string]$Source,
    [Parameter(Mandatory=$true)][string]$Root,
    [switch]$AcceptContributions,
    [ValidateSet('slow', 'medium', 'max', 'pause')][string]$DayPace = 'medium',
    [ValidateSet('slow', 'medium', 'max', 'pause')][string]$NightPace = 'max',
    [ValidatePattern('^(?:[01][0-9]|2[0-3]):[0-5][0-9]$')][string]$DayStart = '08:00',
    [ValidatePattern('^(?:[01][0-9]|2[0-3]):[0-5][0-9]$')][string]$NightStart = '22:00',
    [ValidateRange(1, 1440)][int]$RetryMinutes = 30,
    [ValidateRange(0, 4096)][int]$StorageLimitGB = 0,
    [switch]$AllowSleep,
    [switch]$Remove
)
$ErrorActionPreference = 'Stop'
$taskName = 'VISION Community Background Indexing'
if (-not $Remove -and -not $AcceptContributions) {
    throw 'AcceptContributions is required to enable unattended downloads, imagery retrieval, account creation and verified contributions.'
}
if ($DayStart -eq $NightStart) { throw 'Choose different day and night start times.' }
$sourcePath = (Resolve-Path -LiteralPath $Source).Path
if (-not (Test-Path -LiteralPath (Join-Path $sourcePath 'community/background.py'))) { throw 'The worker source is missing.' }
. (Join-Path $sourcePath 'windows/Start-Vision.ps1')
Assert-VisionRegularPath $Root
$null = New-Item -ItemType Directory -Path $Root -Force
$rootPath = (Resolve-Path -LiteralPath $Root).Path
$stopPath = Join-Path $rootPath 'STOP-AFTER-BATCH'

function Open-BackgroundGuard([string]$Folder) {
    $stream = [IO.File]::Open((Join-Path $Folder 'desktop.lock'), [IO.FileMode]::OpenOrCreate,
                            [IO.FileAccess]::ReadWrite, [IO.FileShare]::ReadWrite)
    try {
        # Same byte-range lock used by the guided app and the background worker.
        $stream.Lock(0, 1)
        return $stream
    } catch [IO.IOException] {
        $stream.Dispose()
        return $null
    }
}

function Assert-BackgroundRegistration([string]$Name, [string]$Executable, [string]$Arguments) {
    # Read back Windows' saved task, rather than treating registration as proof
    # of an unlimited lifetime. Never start an expiring or differently scoped task.
    [xml]$document = Export-ScheduledTask -TaskName $Name -ErrorAction Stop
    $ns = New-Object Xml.XmlNamespaceManager($document.NameTable)
    $ns.AddNamespace('t', 'http://schemas.microsoft.com/windows/2004/02/mit/task')
    function Task-Text([string]$Path) {
        $node = $document.SelectSingleNode('/t:Task/' + $Path, $ns)
        if ($node) { return $node.InnerText }
        return ''
    }
    $expected = @{
        't:Actions/t:Exec/t:Command' = $Executable
        't:Actions/t:Exec/t:Arguments' = $Arguments
        't:Principals/t:Principal/t:LogonType' = 'InteractiveToken'
        't:Settings/t:MultipleInstancesPolicy' = 'IgnoreNew'
        't:Settings/t:ExecutionTimeLimit' = 'PT0S'
        't:Settings/t:StartWhenAvailable' = 'true'
        't:Settings/t:DisallowStartIfOnBatteries' = 'false'
        't:Settings/t:StopIfGoingOnBatteries' = 'false'
        't:Settings/t:RestartOnFailure/t:Interval' = 'PT5M'
        't:Settings/t:RestartOnFailure/t:Count' = '3'
        't:Triggers/t:TimeTrigger/t:Repetition/t:Interval' = 'PT15M'
    }
    foreach ($path in $expected.Keys) {
        if ((Task-Text $path) -cne $expected[$path]) { throw 'Windows did not save the expected recovery settings. The worker was not started; its stop request and reports were kept.' }
    }
    # Windows omits default Enabled/least-privilege fields in exported XML.
    # Check their effective saved values as well as any explicit XML values.
    $saved = Get-ScheduledTask -TaskName $Name -ErrorAction Stop
    if (-not $saved -or $saved.Settings.Enabled -ne $true -or [int]$saved.Principal.RunLevel -ne 0 -or
        $saved.Settings.RunOnlyIfIdle -ne $false -or $saved.Settings.RunOnlyIfNetworkAvailable -ne $false -or
        (Task-Text 't:Settings/t:Enabled') -notin @('', 'true') -or
        (Task-Text 't:Settings/t:RunOnlyIfIdle') -notin @('', 'false') -or
        (Task-Text 't:Settings/t:RunOnlyIfNetworkAvailable') -notin @('', 'false') -or
        (Task-Text 't:Principals/t:Principal/t:RunLevel') -notin @('', 'LeastPrivilege')) {
        throw 'Windows did not save an enabled task with limited privileges. The worker was not started; its stop request and reports were kept.'
    }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = Task-Text 't:Principals/t:Principal/t:UserId'
    $logonUser = Task-Text 't:Triggers/t:LogonTrigger/t:UserId'
    if ($principal -notin @($identity.Name, $identity.User.Value) -or $logonUser -notin @($identity.Name, $identity.User.Value) -or
        $document.SelectNodes('/t:Task/t:Actions/*', $ns).Count -ne 1 -or
        $document.SelectNodes('/t:Task/t:Principals/*', $ns).Count -ne 1 -or
        $document.SelectNodes('/t:Task/t:Triggers/*', $ns).Count -ne 2 -or
        $document.SelectNodes('/t:Task/t:Triggers/*/t:EndBoundary', $ns).Count -ne 0 -or
        $document.SelectNodes('/t:Task/t:Triggers/*[t:Enabled="false"]', $ns).Count -ne 0 -or
        (Task-Text 't:Triggers/t:TimeTrigger/t:Repetition/t:Duration') -notin @('', 'PT0S') -or
        (Task-Text 't:Triggers/t:TimeTrigger/t:Repetition/t:StopAtDurationEnd') -notin @('', 'false')) {
        throw 'Windows saved a different owner or an expiring recovery schedule. The worker was not started; its stop request and reports were kept.'
    }
}

$installGuard = $null
$workerGuard = $null
$handoverStarted = $false
$registrationSucceeded = $false
try {
    try {
        $installGuard = [IO.File]::Open((Join-Path $rootPath 'background-install.lock'),
            [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    } catch [IO.IOException] { throw 'Another VISION installation is running. Wait for it to finish before trying again.' }
    $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($existing) {
        $expectedRoot = '--root "' + $rootPath + '"'
        $matchesRoot = @($existing.Actions | Where-Object {
            $_.Arguments -and $_.Arguments.IndexOf($expectedRoot, [StringComparison]::OrdinalIgnoreCase) -ge 0
        })
        if (-not $matchesRoot.Count) { throw 'The existing VISION task uses a different folder. Use its original private folder to update or remove it.' }
    }
    $workerGuard = Open-BackgroundGuard $rootPath
    if (-not $workerGuard) {
        $state = $null
        try { $state = (Get-Content -LiteralPath (Join-Path $rootPath 'background-status.json') -Raw | ConvertFrom-Json).state }
        catch { }
        $idleStates = @('paused', 'scheduled_pause', 'waiting_for_schedule', 'waiting_for_work',
            'waiting_for_service', 'waiting_for_verification', 'waiting_for_space', 'needs_attention', 'running', 'stopped')
        if ($state -notin $idleStates) {
            throw 'VISION is still open or processing. Close Start VISION, or choose Pause after batch in Background VISION and wait for the batch to finish, then retry. No active work was interrupted.'
        }
        # An idle worker observes this marker between batches and during waits.
        # Never force-stop a native process or replace source while it owns work.
        $handoverStarted = $true
        if (-not (Test-Path -LiteralPath $stopPath)) { [IO.File]::WriteAllText($stopPath, '', $script:VisionUtf8) }
        $deadline = [DateTime]::UtcNow.AddSeconds(60)
        do {
            Start-Sleep -Seconds 1
            $workerGuard = Open-BackgroundGuard $rootPath
        } while (-not $workerGuard -and [DateTime]::UtcNow -lt $deadline)
        if (-not $workerGuard) {
            throw 'The worker has not finished stopping. Its files and stop request were kept. Wait for it to finish, then run setup again; no process was force-stopped.'
        }
    }
    $handoverStarted = $true
    # Keep recovery launches stopped throughout setup, including an abrupt
    # installer exit after registration. Clear only after readback and settings.
    if (-not (Test-Path -LiteralPath $stopPath)) {
        [IO.File]::WriteAllText($stopPath, '', $script:VisionUtf8)
    }
    if ($Remove) {
        if ($existing) { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false }
        Write-Output 'Automatic indexing removed after the worker stopped. Saved accounts, checkpoints, pause requests and failure reports were preserved.'
        return
    }
    $pythonPath = if ($Python) { (Resolve-Path -LiteralPath $Python).Path } else { Get-VisionPython $rootPath }
    $windowlessPython = Join-Path (Split-Path -Parent $pythonPath) 'pythonw.exe'
    if (-not (Test-Path -LiteralPath $windowlessPython)) { throw 'The private runtime is missing pythonw.exe.' }
    $snapshot = Copy-VisionSource $sourcePath $rootPath
    # Keep launchers immutable as well as app snapshots. Existing startup/failure
    # files and the entry point of any previous installation remain untouched.
    $launcherDir = Join-Path (Join-Path $rootPath 'launchers') (Split-Path -Leaf $snapshot)
    Assert-VisionRegularPath (Split-Path -Parent $launcherDir)
    Assert-VisionRegularPath $launcherDir
    [IO.Directory]::CreateDirectory($launcherDir) | Out-Null
    $escaped = $snapshot.Replace('\', '\\').Replace("'", "\'")
    $escapedRoot = $rootPath.Replace('\', '\\').Replace("'", "\'")
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
    (Path('$escapedRoot') / 'startup-failure.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    raise
"@
    $hasher = [Security.Cryptography.SHA256]::Create()
    try { $launcherHash = [BitConverter]::ToString($hasher.ComputeHash($script:VisionUtf8.GetBytes($scriptText))).Replace('-', '').ToLowerInvariant() }
    finally { $hasher.Dispose() }
    $entry = Join-Path $launcherDir ('run-background-' + $launcherHash.Substring(0, 32) + '.py')
    if (Test-Path -LiteralPath $entry) {
        Assert-VisionRegularPath $entry
        if ([IO.File]::ReadAllText($entry) -ne $scriptText) { throw 'The saved background launcher changed. It was not replaced or started.' }
    } else { [IO.File]::WriteAllText($entry, $scriptText, $script:VisionUtf8) }
    $arguments = '-B "{0}" --root "{1}" --accept-contributions --day-pace {2} --night-pace {3} --day-start {4} --night-start {5} --retry-minutes {6}' -f `
        $entry, $rootPath, $DayPace, $NightPace, $DayStart, $NightStart, $RetryMinutes
    $arguments += ' --storage-limit-gb ' + $StorageLimitGB
    if ($AllowSleep) { $arguments += ' --no-keep-awake' }
    $action = New-ScheduledTaskAction -Execute $windowlessPython -Argument $arguments
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $logon = New-ScheduledTaskTrigger -AtLogOn -User $identity
    # Scheduler recovery is independent of the worker's service retry cooldown.
    $recovery = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 15)
    $recovery.Repetition.StopAtDurationEnd = $false
    $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable `
        -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5) `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    $principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
    $task = New-ScheduledTask -Action $action -Trigger @($logon, $recovery) -Settings $settings -Principal $principal `
        -Description 'Opt-in VISION contributor with local day/night pacing. Resumes after sign-in and saved checkpoints. No Codex usage. Pause using the PAUSE file in its private folder.'
    Register-ScheduledTask -TaskName $taskName -InputObject $task -Force | Out-Null
    $registrationSucceeded = $true
    Assert-BackgroundRegistration $taskName $windowlessPython $arguments
    Write-VisionJson (Join-Path $rootPath 'background-registration.json') @{
        status = 'SAVED_RECOVERY_SETTINGS_VERIFIED'; timeUtc = [DateTime]::UtcNow.ToString('o')
        unlimitedTaskLifetime = $true; recoveryEveryMinutes = 15; resumesAfterSignIn = $true
        preventsOverlappingTasks = $true; actualStartVerified = $false; enduranceVerified = $false
    }
    Write-VisionJson (Join-Path $rootPath 'background-settings.json') @{
        dayPace = $DayPace; nightPace = $NightPace; dayStart = $DayStart; nightStart = $NightStart
        retryMinutes = $RetryMinutes; keepAwake = -not [bool]$AllowSleep; clock = 'Windows local time'
        storageLimitGB = $StorageLimitGB
    }
    if (Test-Path -LiteralPath $stopPath) { Remove-Item -LiteralPath $stopPath }
    $workerGuard.Dispose(); $workerGuard = $null
    Start-ScheduledTask -TaskName $taskName
    Write-Output "Background schedule saved: $DayStart day ($DayPace), $NightStart night ($NightPace), retry every $RetryMinutes minutes. Times follow this PC's local clock."
    if ($StorageLimitGB) { Write-Output "Private folder allowance: $StorageLimitGB GB. New processing pauses at batch boundaries; existing work is kept. This is not a hard disk quota." }
    Write-Output 'Registration and a start request do not confirm that the worker started.'
    Write-Output 'Saved Windows recovery settings were verified: no task expiry, sign-in recovery, 15-minute recovery trigger, and no overlapping tasks.'
    Write-Output "Check $rootPath\background-status.json for a fresh status. Startup failures may be saved in startup-failure.json."
    Write-Output 'After a restart, sign into Windows to resume. Power-off suspends computation. PAUSE and existing account/work files were preserved.'
} catch {
    # A failed update must not leave a newly registered or previous task free to
    # resume silently. Preserve the stop request and every account/work file.
    if ($handoverStarted -and -not (Test-Path -LiteralPath $stopPath)) {
        [IO.File]::WriteAllText($stopPath, '', $script:VisionUtf8)
    }
    $reportPath = Join-Path $rootPath ('background-install-failure-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfff') + '.json')
    Write-VisionJson $reportPath @{
        status = 'INCOMPLETE'; errorType = $_.Exception.GetType().Name
        registrationSucceeded = $registrationSucceeded; stopRequestPreserved = (Test-Path -LiteralPath $stopPath)
        timeUtc = [DateTime]::UtcNow.ToString('o')
    }
    Write-Warning "Installation did not finish. Existing accounts and work were kept. Diagnostic report: $reportPath"
    throw
} finally {
    if ($workerGuard) { $workerGuard.Dispose() }
    if ($installGuard) { $installGuard.Dispose() }
}
