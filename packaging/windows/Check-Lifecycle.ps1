# Actual per-user install/update/repair/removal of two built setups, driven
# through the real windows with UI Automation. Disposable CI accounts only:
# it refuses to run beside any existing VISION program, private folder, task
# or removal entry. Private files are synthetic; nothing contacts a service,
# downloads models or imagery, creates an account or starts native work.
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$SetupA, [Parameter(Mandatory=$true)][ValidatePattern('^[a-f0-9]{40}$')][string]$RevisionA,
    [Parameter(Mandatory=$true)][string]$SetupB, [Parameter(Mandatory=$true)][ValidatePattern('^[a-f0-9]{40}$')][string]$RevisionB,
    [Parameter(Mandatory=$true)][string]$Report)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes, System.Windows.Forms, Microsoft.VisualBasic
Add-Type 'using System; using System.Runtime.InteropServices; public static class LifecycleNative { [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l); }'
$UIA = [Windows.Automation.AutomationElement]

$base = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Programs\VISION Community'
$privateRoot = Join-Path $env:LOCALAPPDATA 'vision-community\desktop'
$menu = Join-Path ([Environment]::GetFolderPath('Programs')) 'VISION Community'
$desktopLink = Join-Path ([Environment]::GetFolderPath('DesktopDirectory')) 'VISION Community.lnk'
$uninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\VISIONCommunity'
$taskName = 'VISION Community Background Indexing'
$programA = Join-Path $base $RevisionA.Substring(0,16)
$programB = Join-Path $base $RevisionB.Substring(0,16)
$work = Join-Path ([IO.Path]::GetTempPath()) ('vision-lifecycle-' + [Guid]::NewGuid().ToString('N'))
$checks = [ordered]@{}

if ($env:VISION_DISPOSABLE_LIFECYCLE -ne '1') { throw 'Set VISION_DISPOSABLE_LIFECYCLE=1 only on a disposable test account.' }
foreach ($path in @($base, $privateRoot, $menu, $desktopLink, $uninstallKey)) {
    if (Test-Path -LiteralPath $path) { throw "Refusing to run: existing VISION state at $path" }
}
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) { throw 'Refusing to run: an automatic VISION task exists.' }
if ($RevisionA -eq $RevisionB) { throw 'Two different revisions are required.' }

function Check([string]$Name, [bool]$Value) {
    $checks[$Name] = $Value
    Write-Output ("{0} {1}" -f $(if ($Value) { 'PASS' } else { 'FAIL' }), $Name)
    if (-not $Value) { throw "check_failed: $Name" }
}
function Wait-For([scriptblock]$Test, [string]$What, [int]$Seconds = 60) {
    $deadline = [DateTime]::UtcNow.AddSeconds($Seconds)
    do { $value = & $Test; if ($value) { return $value }; Start-Sleep -Milliseconds 250 } while ([DateTime]::UtcNow -lt $deadline)
    throw "timeout: $What"
}
function Find-Window([int]$ProcessId, [string]$Title) {
    $condition = New-Object Windows.Automation.AndCondition(
        (New-Object Windows.Automation.PropertyCondition($UIA::ProcessIdProperty, $ProcessId)),
        (New-Object Windows.Automation.PropertyCondition($UIA::NameProperty, $Title)))
    return $UIA::RootElement.FindFirst([Windows.Automation.TreeScope]::Children, $condition)
}
function Find-Control($Window, [string]$Name) {
    return $Window.FindFirst([Windows.Automation.TreeScope]::Descendants, (New-Object Windows.Automation.AndCondition(
        (New-Object Windows.Automation.PropertyCondition($UIA::NameProperty, $Name)),
        (New-Object Windows.Automation.PropertyCondition($UIA::ControlTypeProperty, [Windows.Automation.ControlType]::Button)))))
}
function Invoke-Control($Window, [string]$Name) {
    $control = Wait-For { Find-Control $Window $Name } "button $Name" 20
    $pattern = $null
    if ($control.TryGetCurrentPattern([Windows.Automation.InvokePattern]::Pattern, [ref]$pattern)) { $pattern.Invoke(); return }
    # Some hosted sessions expose WinForms buttons without Invoke; click the real control instead.
    $handle = [IntPtr]$control.Current.NativeWindowHandle
    if ($handle -eq [IntPtr]::Zero) { throw "button $Name has no invoke pattern or window handle" }
    [LifecycleNative]::PostMessage($handle, 0x00F5, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null
}
function Get-Texts($Window) {
    $condition = New-Object Windows.Automation.PropertyCondition($UIA::ControlTypeProperty, [Windows.Automation.ControlType]::Text)
    return @($Window.FindAll([Windows.Automation.TreeScope]::Descendants, $condition) | ForEach-Object { $_.Current.Name }) -join "`n"
}
function Show-Tree([int]$ProcessId) {
    # Diagnostics only: control types, names and classes, never file contents.
    $condition = New-Object Windows.Automation.PropertyCondition($UIA::ProcessIdProperty, $ProcessId)
    foreach ($top in @($UIA::RootElement.FindAll([Windows.Automation.TreeScope]::Children, $condition))) {
        foreach ($item in @($top) + @($top.FindAll([Windows.Automation.TreeScope]::Descendants, [Windows.Automation.Condition]::TrueCondition))) {
            $patterns = @($item.GetSupportedPatterns() | ForEach-Object { $_.ProgrammaticName }) -join ','
            Write-Output ("  {0} | {1} | {2} | {3}" -f $item.Current.ControlType.ProgrammaticName, $item.Current.Name, $item.Current.ClassName, $patterns)
        }
    }
}
function Wait-Text($Window, [string]$Fragment, [int]$Seconds = 60) {
    return Wait-For { $text = Get-Texts $Window; if ($text.Contains($Fragment)) { $text } } "text $Fragment" $Seconds
}
function Open-Launcher([string]$Program, [string]$Arguments = '', [string]$Folder = $work) {
    $process = if ($Arguments) { Start-Process -FilePath $Program -ArgumentList $Arguments -WorkingDirectory $Folder -PassThru }
               else { Start-Process -FilePath $Program -WorkingDirectory $Folder -PassThru }
    return $process
}
function Close-Launcher($Process) {
    if (-not $Process.HasExited) { $null = $Process.CloseMainWindow() }
    if (-not $Process.WaitForExit(20000)) { throw 'launcher_did_not_close' }
}
function Install-With([string]$Setup, [switch]$Keyboard) {
    $process = Open-Launcher $Setup
    $window = Wait-For { Find-Window $process.Id 'VISION Community' } 'setup window'
    if (-not $script:treeShown) { $script:treeShown = $true; Write-Output 'UI Automation view of the setup window:'; Show-Tree $process.Id }
    if ($Keyboard) {
        # The default button answers Enter without a mouse.
        $null = Wait-For { [Microsoft.VisualBasic.Interaction]::AppActivate($process.Id); $true } 'focus' 10
        Start-Sleep -Milliseconds 500
        [Windows.Forms.SendKeys]::SendWait('{ENTER}')
    } else { Invoke-Control $window 'Install VISION' }
    $text = Wait-Text $window 'Installed.' 120
    Close-Launcher $process
    return $text
}
function Test-Program([string]$Program, [string]$Setup) {
    $project = Join-Path $Program 'project'
    $inventory = Join-Path $project 'release-inventory.json'
    if (-not (Test-Path -LiteralPath $inventory)) { return $false }
    $value = Get-Content -LiteralPath $inventory -Raw | ConvertFrom-Json
    $names = @($value.files.PSObject.Properties)
    foreach ($file in $names) {
        $path = Join-Path $project $file.Name
        if (-not (Test-Path -LiteralPath $path) -or (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $file.Value.sha256) { return $false }
    }
    if (@(Get-ChildItem -LiteralPath $project -Recurse -File -Force).Count -ne $names.Count + 1) { return $false }
    return (Get-FileHash -LiteralPath (Join-Path $Program 'VISION.exe')).Hash -eq (Get-FileHash -LiteralPath $Setup).Hash
}
function Get-Link([string]$Path) { $shell = New-Object -ComObject WScript.Shell; return $shell.CreateShortcut($Path) }
function Test-Links([string]$Program) {
    $exe = Join-Path $Program 'VISION.exe'
    $main = Get-Link (Join-Path $menu 'VISION Community.lnk'); $auto = Get-Link (Join-Path $menu 'Automatic processing.lnk')
    $desk = Get-Link $desktopLink
    return ($main.TargetPath -eq $exe -and $main.Arguments -eq '' -and $main.WorkingDirectory -eq $Program -and
            $auto.TargetPath -eq $exe -and $auto.Arguments -eq '--background' -and $desk.TargetPath -eq $exe -and
            @(Get-ChildItem -LiteralPath $menu).Count -eq 2)
}
function Test-Registry([string]$Program) {
    $value = Get-ItemProperty -LiteralPath $uninstallKey
    return ($value.InstallLocation -eq $Program -and $value.UninstallString -eq ('"' + (Join-Path $Program 'VISION.exe') + '" --uninstall') -and
            $value.DisplayName -eq 'VISION Community')
}
function Get-ProgramFolders { return @(Get-ChildItem -LiteralPath $base -Directory -Force | ForEach-Object Name | Sort-Object) }
function Get-PrivateHashes {
    $result = [ordered]@{}
    foreach ($name in $fixtureNames) { $result[$name] = (Get-FileHash -LiteralPath (Join-Path $privateRoot $name) -Algorithm SHA256).Hash }
    return ($result.GetEnumerator() | ForEach-Object { $_.Key + '=' + $_.Value }) -join ';'
}
function Uninstall-Confirm {
    # Use the exact command Windows Settings runs.
    $command = (Get-ItemProperty -LiteralPath $uninstallKey).UninstallString
    if ($command -notmatch '^"([^"]+)" --uninstall$') { throw 'unexpected_uninstall_command' }
    $process = Open-Launcher $Matches[1] '--uninstall'
    $confirm = Wait-For { Find-Window $process.Id 'Remove VISION Community' } 'removal confirmation'
    Invoke-Control $confirm 'OK'
    return $process
}
function Find-RemovalMessage {
    foreach ($candidate in @(Get-Process -Name powershell -ErrorAction SilentlyContinue)) {
        $window = Find-Window $candidate.Id 'VISION Community'
        if ($window) { return $window }
    }
}

$treeShown = $false
Write-Output ("Session {0}, interactive {1}" -f [Diagnostics.Process]::GetCurrentProcess().SessionId, [Environment]::UserInteractive)
New-Item -ItemType Directory -Path $work | Out-Null
$copyA = Join-Path $work 'download-a\VISION-Community-Setup.exe'; $copyB = Join-Path $work 'download-b\VISION-Community-Setup.exe'
New-Item -ItemType Directory -Path (Split-Path $copyA), (Split-Path $copyB) | Out-Null
Copy-Item -LiteralPath $SetupA -Destination $copyA; Copy-Item -LiteralPath $SetupB -Destination $copyB
$worker = $null
try {
    # Synthetic private state an existing contributor would have.
    New-Item -ItemType Directory -Path (Join-Path $privateRoot 'indexes\scene'), (Join-Path $privateRoot 'indexes\object') -Force | Out-Null
    $fixtureNames = @('account.json', 'work-selection.json', 'indexes\submissions.sqlite', 'indexes\scene\checkpoint.json',
        'indexes\object\checkpoint.json', 'pc-check.json', 'desktop-failure.json')
    $fixtures = @{
        'account.json' = '{"url":"https://vision-community.visioncommunity.workers.dev","recoveryCode":"SYNTHETIC-LIFECYCLE-FIXTURE-NOT-AN-ACCOUNT"}'
        'work-selection.json' = '{"version":1,"workType":"both","next":"object","unfinished":"scene"}'
        'indexes\submissions.sqlite' = 'synthetic pending delivery fixture'
        'indexes\scene\checkpoint.json' = '{"completed":7,"synthetic":true}'
        'indexes\object\checkpoint.json' = '{"completed":1,"synthetic":true}'
        'pc-check.json' = '{"status":"COMPLETE","synthetic":true}'
        'desktop-failure.json' = '{"status":"INCOMPLETE","synthetic":true}'
    }
    foreach ($name in $fixtureNames) { [IO.File]::WriteAllText((Join-Path $privateRoot $name), $fixtures[$name]) }
    $privateBefore = Get-PrivateHashes
    # A registered automatic task that can never start (one trigger in 2099).
    $pythonw = Join-Path (Split-Path (Get-Command python).Source) 'pythonw.exe'
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $action = New-ScheduledTaskAction -Execute $pythonw -Argument ('-B "{0}" --root "{1}" --accept-contributions --work-type both' -f (Join-Path $work 'never-run.py'), $privateRoot)
    $task = New-ScheduledTask -Action $action -Trigger (New-ScheduledTaskTrigger -Once -At ([DateTime]'2099-01-01')) `
        -Principal (New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited)
    Register-ScheduledTask -TaskName $taskName -InputObject $task | Out-Null

    # 1. Interrupted setup: stop the installer at several points mid-install.
    foreach ($delay in @(0, 150, 400)) {
        $process = Open-Launcher $copyA
        $window = Wait-For { Find-Window $process.Id 'VISION Community' } 'setup window'
        if (-not $treeShown) { $treeShown = $true; Write-Output 'UI Automation view of the setup window:'; Start-Sleep -Seconds 1; Show-Tree $process.Id }
        $button = Wait-For { Find-Control $window 'Install VISION' } 'install button'
        $staged = @(if (Test-Path -LiteralPath $base) { Get-ChildItem -LiteralPath $base -Directory -Force })
        [LifecycleNative]::PostMessage([IntPtr]$button.Current.NativeWindowHandle, 0x00F5, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null
        Start-Sleep -Milliseconds $delay
        Stop-Process -Id $process.Id -Force; $process.WaitForExit()
        $after = @(if (Test-Path -LiteralPath $base) { Get-ChildItem -LiteralPath $base -Directory -Force | ForEach-Object Name })
        Write-Output ("interrupted after {0} ms: folders before={1} after=[{2}]" -f $delay, $staged.Count, ($after -join ','))
        Check "interrupted_${delay}ms_leaves_no_partial_program" ((-not (Test-Path -LiteralPath $programA)) -or (Test-Program $programA $copyA))
        # Undo a completed install so each later attempt really interrupts setup.
        if (Test-Path -LiteralPath $programA) { Remove-Item -LiteralPath $programA -Recurse -Force }
    }
    New-Item -ItemType Directory -Path (Join-Path $base ('staging-' + [Guid]::NewGuid().ToString('N') + '\project')) -Force | Out-Null
    [IO.File]::WriteAllText((Join-Path $base 'install.lock'), '')

    # 2. Install by button, then repeat by keyboard.
    $text = Install-With $copyA
    Check 'install_program_verified' (Test-Program $programA $copyA)
    Check 'install_shortcuts_target_program' (Test-Links $programA)
    Check 'install_removal_entry' (Test-Registry $programA)
    Check 'interrupted_setup_leftovers_removed' (((Get-ProgramFolders) -join ',') -eq $RevisionA.Substring(0,16))
    Check 'install_private_files_unchanged' ((Get-PrivateHashes) -eq $privateBefore)
    $null = Install-With $copyA -Keyboard
    Check 'repeat_install_by_keyboard_is_idempotent' ((Test-Program $programA $copyA) -and (Test-Links $programA) -and (Get-ProgramFolders).Count -eq 1)

    # 3. A changed program file is refused before any download consent, then repaired.
    $changed = Join-Path $programA 'project\community\desktop.py'
    $original = (Get-FileHash -LiteralPath $changed).Hash
    [IO.File]::AppendAllText($changed, "`nchanged fixture`n")
    $process = Open-Launcher (Join-Path $programA 'VISION.exe') '' $programA
    $window = Wait-For { Find-Window $process.Id 'VISION Community' } 'installed window'
    Invoke-Control $window 'Start VISION'
    $text = Wait-Text $window 'application files changed' 20
    Check 'changed_file_refused_with_repair_step' ($text.Contains('choose Install VISION to repair'))
    Check 'changed_file_asks_no_download_consent' (-not (Find-Window $process.Id "Allow VISION's downloads?"))
    Close-Launcher $process
    $process = Uninstall-Confirm
    $message = Wait-For { Find-Window $process.Id 'VISION Community' } 'changed removal message' 30
    Check 'changed_program_removal_refused' ((Get-Texts $message).Contains('repair') -and (Test-Path -LiteralPath $programA))
    Invoke-Control $message 'OK'; $process.WaitForExit(20000) | Out-Null
    $null = Install-With $copyA
    Check 'repair_restores_verified_program' ((Test-Program $programA $copyA) -and (Get-FileHash -LiteralPath $changed).Hash -eq $original)

    # 4. Update while the previous version is open, then after it closes.
    $open = Open-Launcher (Join-Path $programA 'VISION.exe') '' $programA
    $null = Wait-For { Find-Window $open.Id 'VISION Community' } 'previous version window'
    $null = Install-With $copyB
    Check 'update_installs_new_version' ((Test-Program $programB $copyB) -and (Test-Links $programB) -and (Test-Registry $programB))
    Check 'update_keeps_open_previous_version' (Test-Path -LiteralPath (Join-Path $programA 'VISION.exe'))
    Close-Launcher $open
    $null = Install-With $copyB
    Check 'update_retires_closed_previous_version' (((Get-ProgramFolders) -join ',') -eq $RevisionB.Substring(0,16))
    Check 'update_private_files_and_task_unchanged' (((Get-PrivateHashes) -eq $privateBefore) -and [bool](Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue))

    # 5. Active work refuses removal. A cooperative idle worker hands over.
    $ready = Join-Path $work 'worker-ready'; $workerReport = Join-Path $work 'worker-report.json'
    $workerScript = Join-Path $work 'fixture-worker.ps1'
    [IO.File]::WriteAllText($workerScript, @'
param($Root, $Ready, $Report)
$lock = [IO.File]::Open((Join-Path $Root 'desktop.lock'), 'OpenOrCreate', 'ReadWrite', 'ReadWrite'); $lock.Lock(0, 1)
[IO.File]::WriteAllText($Ready, '')
$deadline = [DateTime]::UtcNow.AddMinutes(10)
while (-not (Test-Path -LiteralPath (Join-Path $Root 'STOP-AFTER-BATCH')) -and [DateTime]::UtcNow -lt $deadline) { Start-Sleep -Milliseconds 200 }
$lock.Dispose()
[IO.File]::WriteAllText($Report, '{"observedStop":' + ([string](Test-Path -LiteralPath (Join-Path $Root 'STOP-AFTER-BATCH'))).ToLower() + '}')
'@)
    $statusPath = Join-Path $privateRoot 'background-status.json'
    [IO.File]::WriteAllText($statusPath, '{"state":"indexing"}')
    $worker = Start-Process -FilePath (Join-Path $PSHOME 'powershell.exe') -WindowStyle Hidden -PassThru `
        -ArgumentList @('-NoProfile', '-File', ('"' + $workerScript + '"'), ('"' + $privateRoot + '"'), ('"' + $ready + '"'), ('"' + $workerReport + '"'))
    $null = Wait-For { Test-Path -LiteralPath $ready } 'fixture worker lock'
    $null = Uninstall-Confirm
    $message = Wait-For { Find-RemovalMessage } 'active work refusal' 90
    $refusal = Get-Texts $message
    Invoke-Control $message 'OK'
    Check 'active_work_refuses_removal_with_next_step' ($refusal.Contains('Pause after this batch'))
    Check 'active_work_program_kept' ((Test-Program $programB $copyB) -and (Test-Links $programB) -and (Test-Registry $programB))
    Check 'active_work_not_interrupted' ((-not $worker.HasExited) -and -not (Test-Path -LiteralPath (Join-Path $privateRoot 'STOP-AFTER-BATCH')))
    Check 'active_work_task_and_private_files_kept' (((Get-PrivateHashes) -eq $privateBefore) -and [bool](Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue))
    [IO.File]::WriteAllText($statusPath, '{"state":"waiting_for_work"}')
    $null = Uninstall-Confirm
    $null = Wait-For { if (-not (Test-Path -LiteralPath $base)) { $true } elseif (Find-RemovalMessage) { throw 'idle removal refused' } } 'removal' 150
    Check 'idle_worker_stopped_itself' ($worker.WaitForExit(30000) -and (Get-Content -LiteralPath $workerReport -Raw).Contains('"observedStop":true'))
    Check 'removal_deletes_program_and_empty_folders' (-not (Test-Path -LiteralPath $base) -and -not (Test-Path -LiteralPath $menu))
    Check 'removal_deletes_desktop_shortcut_and_entry' (-not (Test-Path -LiteralPath $desktopLink) -and -not (Test-Path -LiteralPath $uninstallKey))
    Check 'removal_unregisters_automatic_task' (-not (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue))
    Check 'removal_keeps_account_indexes_checkpoints_deliveries' ((Get-PrivateHashes) -eq $privateBefore)
    Check 'removal_leaves_startup_stopped' (Test-Path -LiteralPath (Join-Path $privateRoot 'STOP-AFTER-BATCH'))
    $status = 'LIFECYCLE_PASS'
} catch {
    $status = 'INCOMPLETE'; $failure = $_.Exception.Message
    Write-Output "Lifecycle failed: $failure"
} finally {
    if ($worker -and -not $worker.HasExited) { Stop-Process -Id $worker.Id -Force }
}
$value = [ordered]@{ status = $status; revisionA = $RevisionA; revisionB = $RevisionB; checks = $checks
    accountsCreated = 0; serviceRequests = 0; nativeInference = $false; signed = $false
    productionQualified = $false; cleanDeviceVerified = $false }
if ($status -ne 'LIFECYCLE_PASS') { $value.failure = $failure }
[IO.File]::WriteAllText($Report, ($value | ConvertTo-Json -Depth 4))
if ($status -ne 'LIFECYCLE_PASS') { exit 1 }
