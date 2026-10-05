[CmdletBinding()]
param([string]$Root, [switch]$NoWindow)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$script:VisionBackgroundTask = 'VISION Community Background Indexing'
$script:VisionControlSource = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$script:VisionControlUtf8 = New-Object System.Text.UTF8Encoding($false)

function Assert-VisionControlPath([string]$Path) {
    $current = [IO.Path]::GetFullPath($Path)
    while ($current) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw 'Choose a regular local VISION folder. Linked folders cannot be used.'
            }
        }
        $parent = Split-Path -Parent $current
        if ($parent -eq $current) { break }
        $current = $parent
    }
}

function Read-VisionControlJson([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    Assert-VisionControlPath $Path
    $file = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
    try {
        if ($file.Length -gt 65536) { throw 'A VISION status file needs review. Your files were kept.' }
        $bytes = New-Object byte[] 65537
        $count = 0
        while ($count -lt $bytes.Length) {
            $read = $file.Read($bytes, $count, $bytes.Length - $count)
            if (-not $read) { break }
            $count += $read
        }
        if ($count -gt 65536) { throw 'A VISION status file needs review. Your files were kept.' }
        try {
            $strictUtf8 = New-Object System.Text.UTF8Encoding($false, $true)
            $value = $strictUtf8.GetString($bytes, 0, $count) | ConvertFrom-Json
        } catch { throw 'A VISION saved file could not be read safely. Your files were kept; ask the maintainer for help.' }
        if ($null -eq $value -or $value -is [array] -or $value -is [string] -or $value -is [ValueType]) {
            throw 'A VISION status file needs review. Your files were kept.'
        }
        return $value
    } finally { $file.Dispose() }
}

function Get-VisionTaskRoot($Task) {
    if (-not $Task -or @($Task.Actions).Count -ne 1) { throw 'The automatic VISION task needs review.' }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $owner = [string]$Task.Principal.UserId
    if ($owner -notin @($identity.Name, $identity.User.Value)) {
        try { $owner = (New-Object Security.Principal.NTAccount($owner)).Translate([Security.Principal.SecurityIdentifier]).Value }
        catch { throw 'These controls can only manage your own VISION task.' }
        if ($owner -ne $identity.User.Value) { throw 'These controls can only manage your own VISION task.' }
    }
    $arguments = [string]$Task.Actions[0].Arguments
    # Windows file names cannot contain a double quote. Do not accept a loose
    # substring match, several roots or an unrelated task with the same name.
    if ($arguments -notmatch '^-B "[^"\r\n]+" --root "([^"\r\n]+)" --accept-contributions(?: |$)' -or
        [IO.Path]::GetFileName([string]$Task.Actions[0].Execute) -ne 'pythonw.exe' -or
        $arguments -match '(?:^| )--url(?:=| |$)') {
        throw 'The automatic VISION task needs review.'
    }
    # The scope check above may update PowerShell's shared regex captures.
    $null = $arguments -match '^-B "[^"\r\n]+" --root "([^"\r\n]+)" --accept-contributions(?: |$)'
    return [IO.Path]::GetFullPath($Matches[1])
}

function Get-VisionControlRoot([string]$RequestedRoot) {
    $task = Get-ScheduledTask -TaskName $script:VisionBackgroundTask -ErrorAction SilentlyContinue
    if ($task) {
        $installedRoot = Get-VisionTaskRoot $task
        if ($RequestedRoot -and [IO.Path]::GetFullPath($RequestedRoot) -ne $installedRoot) {
            throw 'An automatic VISION installation already uses another folder. Use its controls; it was not changed.'
        }
        Assert-VisionControlPath $installedRoot
        return $installedRoot
    }
    if ($RequestedRoot) { $selected = [IO.Path]::GetFullPath($RequestedRoot) }
    else {
        if (-not $env:LOCALAPPDATA) { throw 'Your private VISION folder could not be found.' }
        $selected = Join-Path $env:LOCALAPPDATA 'vision-community\desktop'
    }
    Assert-VisionControlPath $selected
    return $selected
}

function Assert-VisionControlTask([string]$Folder) {
    $task = Get-ScheduledTask -TaskName $script:VisionBackgroundTask -ErrorAction SilentlyContinue
    if (-not $task -or (Get-VisionTaskRoot $task) -ne [IO.Path]::GetFullPath($Folder)) {
        throw 'Enable automatic processing first. No other installation was changed.'
    }
    return $task
}

function Set-VisionControlPause([string]$Folder, [bool]$Paused) {
    Assert-VisionControlPath $Folder
    $task = Assert-VisionControlTask $Folder
    $marker = Join-Path $Folder 'PAUSE'
    Assert-VisionControlPath $marker
    if ($Paused) {
        # Never overwrite a marker or force-stop the current batch.
        if (-not (Test-Path -LiteralPath $marker)) {
            $stream = [IO.File]::Open($marker, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
            $stream.Dispose()
        }
        return 'Pause requested. VISION will finish the current batch, then wait.'
    }
    if ((Test-Path -LiteralPath (Join-Path $Folder 'NEEDS-ATTENTION')) -or
        (Test-Path -LiteralPath (Join-Path $Folder 'STOP-AFTER-BATCH'))) {
        throw 'A saved stop or failure needs review. Resume cannot clear it. Your work and reports were kept.'
    }
    if ([string]$task.State -eq 'Disabled') { throw 'Automatic processing is disabled. Save and enable the schedule first.' }
    if (Test-Path -LiteralPath $marker) { Remove-Item -LiteralPath $marker }
    Start-ScheduledTask -TaskName $script:VisionBackgroundTask
    return 'Resume requested. The status below will show what VISION does next.'
}

function Save-VisionControlAccount([string]$Folder, [string]$Code) {
    $account = Join-Path $Folder 'account.json'
    Assert-VisionControlPath $account
    if (Test-Path -LiteralPath $account) {
        $saved = Read-VisionControlJson $account
        if (-not $saved -or [string]$saved.url -ne 'https://vision-community.visioncommunity.workers.dev' -or
            [string]::IsNullOrWhiteSpace([string]$saved.recoveryCode)) {
            throw 'The saved account needs review. These controls cannot replace it or move it to another service.'
        }
        return # Never replace another account or journal owner.
    }
    if ([string]::IsNullOrWhiteSpace($Code) -or $Code.Trim().Length -gt 256) {
        throw 'Paste your saved account code once. First create an account in Start VISION and keep its code safe.'
    }
    [IO.Directory]::CreateDirectory($Folder) | Out-Null
    $stage = Join-Path $Folder ('account-' + [guid]::NewGuid().ToString('N') + '.tmp')
    try {
        $payload = @{ url = 'https://vision-community.visioncommunity.workers.dev'; accountId = $null; recoveryCode = $Code.Trim() }
        $bytes = $script:VisionControlUtf8.GetBytes(($payload | ConvertTo-Json -Compress))
        $stream = [IO.File]::Open($stage, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
        try { $stream.Write($bytes, 0, $bytes.Length); $stream.Flush($true) } finally { $stream.Dispose() }
        # No overwrite: a racing setup cannot change the saved account.
        [IO.File]::Move($stage, $account)
    } finally {
        if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage }
    }
}

function Get-VisionControlStatus([string]$Folder) {
    Assert-VisionControlPath $Folder
    $task = Get-ScheduledTask -TaskName $script:VisionBackgroundTask -ErrorAction SilentlyContinue
    if (-not $task) { return 'Automatic processing is not enabled. Finish setup in Start VISION, then close it and enable the schedule here.' }
    if ((Get-VisionTaskRoot $task) -ne [IO.Path]::GetFullPath($Folder)) { throw 'The automatic task uses another folder.' }
    $taskState = [string]$task.State
    if ($taskState -eq 'Disabled') { return 'Automatic processing is disabled. Your saved work is kept.' }
    if ($taskState -ne 'Running') {
        if (Test-Path -LiteralPath (Join-Path $Folder 'NEEDS-ATTENTION')) {
            return 'Stopped: a saved failure needs review. Your work and reports are kept.'
        }
        if (Test-Path -LiteralPath (Join-Path $Folder 'STOP-AFTER-BATCH')) {
            return 'Stopped safely. A saved stop request needs review before restarting.'
        }
        return 'The worker is not running now. Choose Resume to request a start. Save and enable checks the automatic recovery settings again.'
    }
    $report = Read-VisionControlJson (Join-Path $Folder 'background-status.json')
    if (-not $report) { return 'The worker has started, but no progress report is saved yet. Check again shortly. Startup reports are kept in your VISION folder.' }
    $labels = @{
        running = 'Between batches'; processing = 'Processing a batch'; preparing = 'Checking processing files'
        checking_pc = 'Checking this PC'; paused = 'Paused'; scheduled_pause = 'Paused by your schedule'
        waiting_for_schedule = 'Paused by your schedule'; waiting_for_work = 'Waiting for more locations'
        waiting_for_service = 'Waiting for the service - retries automatically'
        waiting_for_verification = 'Waiting for saved batches to be checked - retries automatically'
        retrying_indexing = 'Recovering after a processing problem - retries after a rest'
        waiting_for_space = 'Paused for storage - check free space and your chosen allowance'
        needs_attention = 'Stopped processing: a saved failure needs review'; stopped = 'Finishing a safe stop'
    }
    $state = [string]$report.state
    $label = if ($labels.ContainsKey($state)) { $labels[$state] } else { 'A saved progress report needs review' }
    try { $updated = ([DateTimeOffset]::Parse([string]$report.updatedAt)).ToLocalTime().ToString('g') }
    catch { $updated = 'time unavailable' }
    # A saved report is historical evidence, not a live progress heartbeat.
    return "Worker running. Last saved status: $label.`r`nLast saved report: $updated. Changes appear after the current step."
}

function Show-VisionBackgroundControl([string]$Folder) {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    [Windows.Forms.Application]::EnableVisualStyles()
    $form = New-Object Windows.Forms.Form
    $form.Text = 'VISION - Automatic processing'
    $form.Size = New-Object Drawing.Size(720, 740)
    $form.MinimumSize = New-Object Drawing.Size(650, 700)
    $form.StartPosition = 'CenterScreen'
    $form.Font = New-Object Drawing.Font('Segoe UI', 12)
    $form.AutoScroll = $true
    $layout = New-Object Windows.Forms.FlowLayoutPanel
    $layout.Dock = 'Fill'; $layout.FlowDirection = 'TopDown'; $layout.WrapContents = $false
    $layout.AutoScroll = $true; $layout.Padding = New-Object Windows.Forms.Padding(20)
    $form.Controls.Add($layout)
    function Add-ControlLabel([string]$Text) {
        $label = New-Object Windows.Forms.Label
        $label.Text = $Text; $label.AutoSize = $true
        $label.MaximumSize = New-Object Drawing.Size(620, 0)
        $label.Margin = New-Object Windows.Forms.Padding(0, 0, 0, 14)
        $layout.Controls.Add($label)
        return $label
    }
    $null = Add-ControlLabel 'Let VISION help automatically. You can close these controls while it works.'
    $statusLabel = Add-ControlLabel ''
    $statusLabel.ForeColor = [Drawing.Color]::DarkSlateGray
    $null = Add-ControlLabel 'Work to process. Each type needs its own approval; Both takes turns.'
    $workChoice = New-Object Windows.Forms.ComboBox
    $workChoice.DropDownStyle = [Windows.Forms.ComboBoxStyle]::DropDownList
    $workChoice.Width = 350; $workChoice.AccessibleName = 'Work to process'
    $workCodes = @('scene', 'object', 'both')
    $workChoice.Items.AddRange(@('Scenes', 'Objects', 'Both - one batch at a time'))
    $workChoice.SelectedIndex = 0; $layout.Controls.Add($workChoice)
    $null = Add-ControlLabel 'Times follow this PC clock. Medium rests between batches; Maximum skips extra rests. Both use approved processing settings.'
    $scheduleRow = New-Object Windows.Forms.FlowLayoutPanel
    $scheduleRow.AutoSize = $true; $scheduleRow.WrapContents = $false
    $scheduleRow.Margin = New-Object Windows.Forms.Padding(0, 0, 0, 14)
    $layout.Controls.Add($scheduleRow)
    $choices = @('Slow', 'Medium', 'Maximum', 'Paused')
    $paceCodes = @('slow', 'medium', 'max', 'pause')
    function Add-SchedulePeriod([string]$Name, [string]$Time, [int]$Choice) {
        $panel = New-Object Windows.Forms.FlowLayoutPanel
        $panel.FlowDirection = 'TopDown'; $panel.WrapContents = $false; $panel.AutoSize = $true
        $label = New-Object Windows.Forms.Label
        $label.Text = "$Name starts (24-hour time)"; $label.AutoSize = $true
        $panel.Controls.Add($label)
        $clock = New-Object Windows.Forms.DateTimePicker
        $clock.Format = 'Custom'; $clock.CustomFormat = 'HH:mm'; $clock.ShowUpDown = $true; $clock.Width = 160
        $clock.Value = [DateTime]::Today.Add([TimeSpan]::Parse($Time))
        $clock.AccessibleName = "$Name start time"
        $panel.Controls.Add($clock)
        $pace = New-Object Windows.Forms.ComboBox
        $pace.DropDownStyle = 'DropDownList'; $pace.Width = 200; $pace.AccessibleName = "$Name processing speed"
        $pace.Items.AddRange($choices); $pace.SelectedIndex = $Choice
        $panel.Controls.Add($pace); $scheduleRow.Controls.Add($panel)
        return @{ Clock = $clock; Pace = $pace }
    }
    $settings = Read-VisionControlJson (Join-Path $Folder 'background-settings.json')
    $dayStart = '06:00'; $nightStart = '00:00'; $dayChoice = 1; $nightChoice = 2; $limit = 20; $keepAwake = $true; $retryMinutes = 30
    if ($settings) {
        if ($settings.PSObject.Properties['workType']) {
            $chosenWork = [Array]::IndexOf($workCodes, [string]$settings.workType)
            if ($chosenWork -lt 0) { throw 'The saved work choice needs review.' }
            $workChoice.SelectedIndex = $chosenWork
        }
        $dayStart = [string]$settings.dayStart; $nightStart = [string]$settings.nightStart
        $dayChoice = [Array]::IndexOf($paceCodes, [string]$settings.dayPace)
        $nightChoice = [Array]::IndexOf($paceCodes, [string]$settings.nightPace)
        if ($dayChoice -lt 0 -or $nightChoice -lt 0) { throw 'The saved schedule needs review.' }
        $limit = [int]$settings.storageLimitGB; $keepAwake = [bool]$settings.keepAwake
        $retryMinutes = [int]$settings.retryMinutes
    }
    $day = Add-SchedulePeriod 'Day' $dayStart $dayChoice
    $night = Add-SchedulePeriod 'Night' $nightStart $nightChoice
    $storageLabel = Add-ControlLabel 'Space allowance (GB). Processing pauses at this amount; files are kept. 0 means no allowance. A batch can temporarily exceed it.'
    $storage = New-Object Windows.Forms.NumericUpDown
    $storage.Minimum = 0; $storage.Maximum = 4096; $storage.Value = $limit; $storage.Width = 160
    $storage.AccessibleName = 'Saved file space allowance in gigabytes'; $layout.Controls.Add($storage)
    $awake = New-Object Windows.Forms.CheckBox
    $awake.Text = 'Keep the PC awake while processing'; $awake.AutoSize = $true; $awake.Checked = $keepAwake
    $layout.Controls.Add($awake)
    $codeLabel = Add-ControlLabel 'First time? Paste the account code you saved in Start VISION. This keeps your contributions and credits in the same account.'
    $code = New-Object Windows.Forms.TextBox
    $code.UseSystemPasswordChar = $true; $code.MaxLength = 256; $code.Width = 600; $code.AccessibleName = 'Private saved account code'
    $layout.Controls.Add($code)
    $hasAccount = Test-Path -LiteralPath (Join-Path $Folder 'account.json') -PathType Leaf
    $codeLabel.Visible = -not $hasAccount; $code.Visible = -not $hasAccount
    $consent = New-Object Windows.Forms.CheckBox
    $consent.Text = 'Allow automatic downloads, imagery and verified contributions'
    $consent.AutoSize = $true; $layout.Controls.Add($consent)
    $buttons = New-Object Windows.Forms.FlowLayoutPanel
    $buttons.AutoSize = $true; $buttons.MaximumSize = New-Object Drawing.Size(620, 0)
    $layout.Controls.Add($buttons)
    function Add-ControlButton([string]$Text) {
        $button = New-Object Windows.Forms.Button
        $button.Text = $Text; $button.AutoSize = $true; $button.MinimumSize = New-Object Drawing.Size(120, 46)
        $buttons.Controls.Add($button); return $button
    }
    $enable = Add-ControlButton 'Save and enable'
    $pause = Add-ControlButton 'Pause after batch'
    $resume = Add-ControlButton 'Resume'
    $refresh = Add-ControlButton 'Check status'
    $remove = Add-ControlButton 'Turn off automatic processing'
    $openFolder = Add-ControlButton 'Open saved files'
    $null = Add-ControlLabel 'After a restart, sign into Windows to resume. Sleep, power-off or a closed laptop lid stops computation until the PC is awake again. Plug the PC into power for long runs.'
    $null = Add-ControlLabel 'Internet or service problems retry after a rest. Rejected checks, unsafe files or other lasting problems stop for review. Keep saved files; this preview has not passed a months-long endurance test.'
    function Refresh-ControlStatus {
        try { $statusLabel.Text = Get-VisionControlStatus $Folder }
        catch { $statusLabel.Text = 'The status could not be checked safely. Your files were kept. Ask the maintainer for help.' }
    }
    function Show-ControlError {
        param($Failure)
        # Fixed user-facing errors contain no account codes or native output.
        [Windows.Forms.MessageBox]::Show([string]$Failure.Exception.Message, 'VISION needs attention', 'OK', 'Warning') | Out-Null
    }
    $refresh.Add_Click({ Refresh-ControlStatus })
    $pause.Add_Click({ try { $statusLabel.Text = Set-VisionControlPause $Folder $true } catch { Show-ControlError $_ } })
    $resume.Add_Click({ try { $statusLabel.Text = Set-VisionControlPause $Folder $false } catch { Show-ControlError $_ } })
    $openFolder.Add_Click({
        try {
            Assert-VisionControlPath $Folder
            if (-not (Test-Path -LiteralPath $Folder -PathType Container)) { throw 'Enable VISION first. Its files will be kept in this private folder.' }
            Start-Process -FilePath explorer.exe -ArgumentList ('"' + $Folder + '"')
        } catch { Show-ControlError $_ }
    })
    $enable.Add_Click({
        $enable.Enabled = $false
        try {
            if (-not $consent.Checked) { throw 'Tick the permission box to allow automatic processing.' }
            if ($day.Clock.Value.ToString('HH:mm') -eq $night.Clock.Value.ToString('HH:mm')) { throw 'Choose different day and night start times.' }
            # Validate a complete setup before persisting any supplied code.
            if (-not (Test-Path -LiteralPath (Join-Path $Folder 'runtime/bin/mma-vision.exe') -PathType Leaf)) {
                throw 'Finish Set up this PC in Start VISION first, then close VISION and return here.'
            }
            $null = Get-VisionControlRoot $Folder
            Save-VisionControlAccount $Folder $code.Text
            $code.Clear(); $code.Visible = $false; $codeLabel.Visible = $false
            $statusLabel.Text = 'Checking and saving the schedule. Please wait.'
            $form.Refresh()
            $options = @{ Source = $script:VisionControlSource; Root = $Folder; AcceptContributions = $true
                DayPace = $paceCodes[$day.Pace.SelectedIndex]; NightPace = $paceCodes[$night.Pace.SelectedIndex]
                WorkType = $workCodes[$workChoice.SelectedIndex]
                DayStart = $day.Clock.Value.ToString('HH:mm'); NightStart = $night.Clock.Value.ToString('HH:mm')
                StorageLimitGB = [int]$storage.Value; RetryMinutes = $retryMinutes; AllowSleep = -not $awake.Checked }
            $null = & (Join-Path $PSScriptRoot 'Install-Background.ps1') @options
            Refresh-ControlStatus
        } catch { Show-ControlError $_ } finally { $enable.Enabled = $true }
    })
    $remove.Add_Click({
        try {
            $null = Assert-VisionControlTask $Folder
            $null = & (Join-Path $PSScriptRoot 'Install-Background.ps1') -Source $script:VisionControlSource -Root $Folder -Remove
            Refresh-ControlStatus
        } catch { Show-ControlError $_ }
    })
    Refresh-ControlStatus
    if ($NoWindow) { return $form }
    try { $null = $form.ShowDialog() } finally { $code.Clear(); $form.Dispose() }
}

if ($MyInvocation.InvocationName -ne '.') {
    try {
        $selectedRoot = Get-VisionControlRoot $Root
        Show-VisionBackgroundControl $selectedRoot
    } catch {
        Write-Error 'The VISION controls could not open safely. Your account and work were kept. Ask the maintainer for help.'
        exit 1
    }
}
