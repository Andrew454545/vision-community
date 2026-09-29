# Background processing on Windows

This is a maintainer preview. The worker must not be described as indexing
until its status says `processing` and an actual batch has completed.

Once enabled, the worker uses Windows Task Scheduler and ordinary Python. It
does not call Codex or any language-model API. It resumes after Windows sign-in,
reuses the account and batch folder, and retries unavailable work/service every
30 minutes. A separate 15-minute Windows recovery trigger restarts an exited
worker; a file lock prevents duplicate instances and conflicts with the guided
app when both use the same private folder.

The laptop must be powered on, connected, and signed in. The worker prevents
idle sleep only while checking/processing a batch; manual sleep, closing the
lid according to Windows settings, restart, and shutdown still suspend work.
No power plan, execution policy, antivirus, or system-wide installation changes
are needed. After a restart, sign into Windows. Resume before sign-in is not
implemented. Rejected qualification is never treated as permission to upload.

## Enable after explicit consent

Use the repository folder; setup downloads and verifies its own private Python:

```powershell
.\windows\Install-Background.ps1 -Source 'FULL_PATH_TO_REPOSITORY' -Root "$env:LOCALAPPDATA\vision-community-background" -AcceptContributions
```

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

## Pause, resume, and understand the status

Open the private folder named during setup. `background-status.json` describes
the worker. `account.json` is private; never share it or commit it to GitHub.

- To pause after the current batch, create a file named `PAUSE` with no extension.
  Remove it to resume within 30 minutes.
- `waiting_for_service`: the verified service is not available. No readiness
  check is bypassed. The worker waits without consuming Codex usage.
  Network failures and temporary HTTP 429/502/503/504 responses retry after
  30 minutes; an explicit verification rejection still requires review.
- `waiting_for_work`: the queue is empty. The worker waits for useful new work.
- `waiting_for_space`: free at least 5 GB; existing results remain in place.
- `needs_attention`: inspect `desktop-failure.json` and retained batch reports.
  Fix the cause, then remove `NEEDS-ATTENTION`. Failed PC checks are not rerun
  indefinitely. An interrupted batch resumes only while its lease and runtime
  identity remain valid; expired work is preserved, not blindly submitted.

To disable automatic startup, open **Task Scheduler**, select **VISION Community
Background Indexing**, and choose **Disable**. Use the pause file first to let
the current batch finish. Saved files are preserved. For removal, rerun the
installer with `-Remove` and the same paths; this stops the worker immediately
but does not delete results or credentials.

## Remaining validation

Unit tests cover unavailable services, restart/account reuse, empty queues,
rejected checks, low disk, pause, corrupt credentials and duplicate processes.
The installer test uses a mock scheduler and checks startup failure reporting,
including folder names with spaces and apostrophes. It does not prove that a
real scheduled task launches. PowerShell tests honor the host execution policy;
`VISION_TEST_POWERSHELL` can select an already configured PowerShell executable.
An actual qualified contribution, OS restart, sleep/wake, network interruption,
and extended thermal/resource run remain required before calling this production
ready. A finite queue cannot supply useful new locations forever.
