# Simple controls and saved recovery settings

The Windows source preview adds **Background VISION.cmd**. After guided setup,
users close Start VISION, paste their saved account code once and enable a
schedule. New defaults are Medium during the day and Maximum midnight–06:00,
with a 20 GB saved-file allowance. Existing installations retain their folder,
account, times, speeds and allowance. The worker operates independently of the
control window and Codex.

Pause/resume, status, schedule changes and turning off automatic processing use
plain buttons. Account codes are masked and never printed. An existing account
is never replaced or moved to another service. Status distinguishes an exited
Windows task from its historical progress report. Resume cannot clear a lasting
failure or an interrupted-installation stop. Active batches are never killed
to apply settings.

Setup retains a stop marker until saving and independently reading back the
task's executable, arguments, owner, limited privileges, enabled state, unlimited
execution time, sign-in trigger and unexpired 15-minute recovery trigger. Battery
continuity and absence of idle-only/network-profile conditions are checked too.
A mismatch keeps the stop and failure report. Windows can omit default XML fields
and use both a name and SID for the same user; effective settings are checked.
The receipt distinguishes verified saved settings from actual start/endurance.
Microsoft documents [indefinite repetition when duration is omitted](https://learn.microsoft.com/en-us/windows/win32/taskschd/repetitionpattern-duration)
and the [default enabled setting](https://learn.microsoft.com/en-us/windows/win32/taskschd/taskschedulerschema-enabled-settingstype-element).

The delivery journal adds partial indexes for pending and lost-lease rows.
Recovery queries use those indexes with 10,000 completed receipts, preserve all
history and payloads, and avoid sorting/scanning accepted history. Migration of
an older journal preserves pending output. This improves recovery as the journal
grows; it does not cap disk growth or establish months of endurance.

## Checks and limits

- The full local Windows suite passes 477 tests in 402.016 seconds with two
  existing filesystem-link permission skips. A final nine-case control run also
  passes, including the subsequently added cross-service/account guard.
  The final seventeen-case installer run passes in 107.039 seconds, including
  saved-setting mismatch cases and preserved stops/accounts/failures.
- Real Windows task registration/readback passes with a temporary diagnostic
  task. It was removed without starting inference or touching the installed
  contributor. Original XML/default-representation failures are preserved.
- Windows PowerShell 5.1 parses all three starter/control scripts. Direct
  execution of a separate 5.1 test was blocked by the host script policy; that
  failure is preserved and no policy was changed. Configured PowerShell tests
  construct the real native form without showing it or starting work. Off-screen
  layout was reviewed; a clean-device beginner walkthrough remains required.
- Existing sign-in recovery, owned native checkpoint/process cleanup, delayed
  retries, bounded pending delivery and disk-space guards remain in place.

The source-only preview does not open production contributions or search, grant
qualification, change the installed worker or claim uninterrupted computation.
A sleeping or powered-off PC cannot process. Windows sign-in is required after
restart. General contribution-file retention, real sleep/wake and restart,
qualified accepted work, sustained temperature/memory/disk growth and an extended
endurance run remain release gates. Keep pending, rejected and failed files.
