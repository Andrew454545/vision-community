# Background processing on Windows

The background worker is intended for ongoing processing over days or weeks,
with different daytime and nighttime activity. It runs without Codex or
language-model API calls and can wait for the service or new locations without
repeated prompts.

**This remains a maintainer preview.** A registered or running task is not proof
of completed indexing. The service must approve the PC and verify contributions
before results join the shared pool. A finite queue cannot provide useful new
locations forever, and failures requiring review still stop processing.

Once enabled, the worker uses Windows Task Scheduler and ordinary Python. It
does not call Codex or any language-model API. It resumes after Windows sign-in,
reuses the account and batch folder, and retries unavailable work/service every
30 minutes by default. A separate 15-minute Windows recovery trigger can restart an exited
worker; a file lock prevents duplicate instances and conflicts with the guided
app when both use the same private folder.

The computer must be powered on, connected, and signed in. By default, the worker
asks Windows to prevent idle sleep during processing and deliberate pacing
rests between batches. A manual pause, scheduled pause or unavailable-service
wait releases that request. Manual sleep, closing the lid according to Windows
settings, restart and shutdown still suspend work. A sleeping or powered-off
computer cannot process locations; the day/night schedule does not wake it.
No power plan, execution policy, antivirus, or system-wide installation changes
are needed. After a restart, sign into Windows. Resume before sign-in is not
implemented. Rejected qualification is never treated as permission to upload.

## Enable after explicit consent

Use the repository folder; setup downloads and verifies its own private Python:

```powershell
.\windows\Install-Background.ps1 -Source 'FULL_PATH_TO_REPOSITORY' -Root "$env:LOCALAPPDATA\vision-community-background" -AcceptContributions
```

The default schedule uses **medium from 08:00 to 22:00**, then **max from 22:00
to 08:00**, every day according to the PC's local clock.

The consent covers private model downloads, live imagery, creation/reuse of an
anonymous account, and ongoing verified contributions. The installer snapshots
the code before registering a per-user task. Updating the development checkout
does not silently replace that running snapshot; reinstall after review.
An optional `-Python` override is available for a maintainer's already verified
private runtime. By default the worker does not depend on a calibration folder.

Registration is not evidence that Windows successfully launched the worker.
Check Task Scheduler's last result and a fresh timestamp in
`background-status.json`. The hidden Python launcher preserves startup exceptions
in `startup-failure.json`; failures before Python starts appear only in Task
Scheduler. Do not disable Windows security settings to work around a launch error.

## Choose daytime and nighttime activity

Each period can use any of these settings:

| Setting | What happens between batches |
| --- | --- |
| `slow` | Process a batch, then rest for three times its processing duration: approximately one-quarter active time. |
| `medium` | Process a batch, then rest for the same duration: approximately half active time. |
| `max` | Continue to the next available batch without a deliberate pacing pause. |
| `pause` | Wait for a period that allows processing. |

These settings control the gaps between 16-location batches. They are not exact
CPU-percentage limits: a batch can still be busy while it runs. They keep the
same single inference thread and qualified processing profile. Day/night
changes take effect at a safe batch boundary; a running batch finishes first.
`max` currently means continuous batches at the conservative single-thread
profile. It does not yet use every processor core. Parallel inference must be
measured against controlled reference inputs and approved by the trusted service
before it can replace that profile; a faster label cannot grant that approval.

For example, use less activity from 09:00 to 23:00 and continuous batches
overnight:

```powershell
.\windows\Install-Background.ps1 -Source 'FULL_PATH_TO_REPOSITORY' -Root "$env:LOCALAPPDATA\vision-community-background" -AcceptContributions -DayPace slow -NightPace max -DayStart '09:00' -NightStart '23:00'
```

For overnight processing only, use `-DayPace pause -NightPace max`. Times use
24-hour `HH:MM` format and the local Windows clock. Both periods repeat daily;
there is no separate weekday or weekend schedule.

The normal retry interval is 30 minutes. `-RetryMinutes 15`, for example,
checks an unavailable service or empty queue every 15 minutes; the supported
range is 1–1,440 minutes. This is separate from Windows' fixed 15-minute
recovery trigger. Recognized indexing interruptions use increasing retry
delays, capped at six hours and preserved across restarts.

Add `-AllowSleep` to the installer to let normal idle-sleep settings apply
throughout. This does not change the Windows power plan. The corresponding
direct-worker arguments are `--day-pace`, `--night-pace`, `--day-start`,
`--night-start`, `--retry-minutes` and `--no-keep-awake` on
`python -m community.background`.

To change settings, rerun the installer with the same private folder and the
desired options. It uses `STOP-AFTER-BATCH` to request a safe handover and does
not force-kill a batch to apply settings. If it cannot complete the handover
while the worker is busy, let the batch finish and rerun setup. Editing the
development checkout does not update an installed worker automatically.

## Pause, resume, and understand the status

Open the private folder named during setup. `background-status.json` describes
the worker, chosen pace, day/night settings and last update. Its accepted count
is for the current worker process, not a lifetime balance; the service holds
the account's credits. `account.json` is private; never share it or commit it
to GitHub.

- To pause after the current batch, create a file named `PAUSE` with no extension.
  Remove it to allow processing again at the next wake or retry, under the
  chosen schedule. A scheduled pause still prevents starting new work.
- `waiting_for_schedule`: the current day/night period is set to pause.
- `running`: the last batch was saved; the worker is resting for the selected
  pace or moving to the next batch. This state alone is not a verified credit.
- `waiting_for_service`: the verified service is not available. No readiness
  check is bypassed. The worker waits without consuming Codex usage.
  Network failures and temporary HTTP 429/502/503/504 responses retry after
  the configured retry interval; an explicit verification rejection still
  requires review.
- `waiting_for_work`: the queue is empty. The worker waits for useful new work.
- `waiting_for_verification`: saved batches need the service's verification.
  A local delivery journal retries interrupted submissions and audits after a
  restart without processing their images again. It is bound to the original
  anonymous account and service, and contains no account code or bearer token.
  At most 64 unresolved batches are allowed before claiming more work pauses;
  verification is retried at the configured interval. A rejected batch stops processing
  for review and retains its evidence.
- `waiting_for_space`: free at least 5 GB; existing results remain in place.
- `retrying_indexing`: a recognized indexing interruption is waiting for a
  later attempt. Increasing delays, capped at six hours, survive a restart;
  this does not override rejected qualification or rejected work.
- `needs_attention`: inspect `desktop-failure.json` and retained batch reports.
  Fix the cause, then remove `NEEDS-ATTENTION`. Failed PC checks are not rerun
  indefinitely. An interrupted batch resumes only while its lease and runtime
  identity remain valid; expired work is preserved, not blindly submitted.

To disable automatic startup, open **Task Scheduler**, select **VISION Community
Background Indexing**, and choose **Disable**. Use the pause file first to let
the current batch finish. Saved files are preserved. For removal, rerun the
installer with `-Remove` and the same paths. Saved work and credentials are
preserved; follow any busy-worker message before retrying removal.

## Saved work and disk space

Batch indexes, logs and failure evidence accumulate over long runs. The 5 GB
free-space check is a guard before work, not a storage quota or automatic
cleanup policy. The pending-batch limit also does not cap all historical files.
Keep the installation folder in place, preserve pending or failed work, and
monitor free space. Do not delete recovery files merely to clear a warning;
resolve storage pressure without discarding unsent work or account recovery.

## Remaining validation

Unit tests cover unavailable services, restart/account reuse, empty queues,
rejected checks, low disk, pause, corrupt credentials and duplicate processes.
Delivery tests cover lost responses, restart recovery, service/account
isolation, bounded backlog, fairness and preserved rejected results.
The installer test uses a mock scheduler and checks startup failure reporting,
including folder names with spaces and apostrophes. It does not prove that a
real scheduled task launches. PowerShell tests honor the host execution policy;
`VISION_TEST_POWERSHELL` can select an already configured PowerShell executable.
These checks do not establish unattended operation over days or weeks. An
actual qualified contribution, active-batch interruption, OS restart,
sleep/wake, network interruption, day/night transitions and an extended
thermal/resource run remain required before calling this production ready.

On the maintainer's Windows host, a native scheduled diagnostic confirmed that
the task could not see the initially prepared application folder. A fresh
private installation in the shared local workspace passed native startup,
single-worker presence, idle forced-exit recovery and pause/resume on
2026-09-30 UTC. That installed version was observed with `waiting_for_service`,
zero accepted locations and no qualification bypass. The old files were
preserved. This proves startup in that folder, not model quality, completed
indexing. The updated day/night worker was then installed on the same native
host: a fresh paused startup, automatic return to `waiting_for_service`, and
exactly one worker were verified. A second installation exercised the actual
graceful handover without force-stopping the new worker. It preserved the
schedule and resumed waiting with zero accepted locations. All 233 Python
checks and 37 server/browser checks passed. Simulated clocks test schedule
boundaries and restart-persistent cooldown; real overnight and active-batch
recovery remain unverified.
Keep the installed folder in place; source checkout updates do not replace its
versioned application snapshot. No repeated Codex status checks are needed.
