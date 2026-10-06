# Native Windows automatic processing and removal

Windows automatic controls, task registration and detached removal now use
native C#. The installed app does not need PowerShell, an administrator account
or an execution-policy change for these operations. The earlier extracted
script launcher remains a separate legacy download; this source change does
not update it or qualify a public release.

Automatic controls offer Scenes, Objects or Both, day/night speeds, a storage
allowance and keeping the PC awake while processing. Defaults are Medium from
06:00 and Maximum from 00:00, using the PC's clock. Each lane still needs its
own trusted computer check; Maximum uses approved parallel settings and does
not grant an unqualified profile extra workers.

## Startup and saved-work protections

- Every schedule has an immutable native executable, source payload and
  configuration under the user's private folder. Its exact configuration hash
  is saved in the scheduled action. Source files, inventory, executable and
  paths are checked before trusting that action. Settings changes create a new
  copy; older entrypoints and work are preserved.
- Every autonomous launch verifies the complete pinned Python archive and all
  extracted runtime files, and the complete source snapshot, before Python
  executes. Python uses isolated imports and a small environment. Changed,
  extra, missing or redirected files stop safely and retain a redacted report.
- Task Scheduler uses the current user's interactive token and limited
  privileges. Its saved settings are read back: no execution-time limit, no
  trigger expiry, sign-in recovery, 15-minute recovery attempts, three
  five-minute failure retries and no overlapping tasks. Registration and a
  start request do not prove processing began. These follow
  [Microsoft's Task Scheduler API](https://learn.microsoft.com/en-us/windows/win32/taskschd/taskfolder-registertaskdefinition).
- A shared setup lock serializes changes. The same byte-range writer lock as
  the guided and background applications protects handover. Active work
  refuses replacement/removal. Idle work receives a stop-after-batch request;
  setup waits up to 60 seconds for it to relinquish its own lock. No worker is
  force-stopped. A verified open guided page also refuses handover.
- Existing accounts are kept and cannot be switched to another service or
  overwritten by these controls. Pause markers are preserved during schedule
  replacement. Resume cannot clear a saved stop or attention marker. A
  terminal startup failure keeps its first report; later recovery triggers
  stay stopped without accumulating repeated reports.
- Removal uses a byte-identical native helper outside the installed program.
  It authenticates its parent, waits for that application to exit, shares
  setup's installation lock, verifies the program and owned task, and uses
  cooperative handover. It removes only this program and its matching
  shortcuts/registry entry. The account, indexes, checkpoints, delivery
  journal, pause/stop requests and previous failures remain private.
- The temporary removal executable cannot delete itself while running. Its
  bounded temporary directory and fixed-code receipt are retained together;
  no shell or policy workaround is used. Legacy Python/script task actions
  are refused by the new controls rather than silently adopted or rewritten.

Sleep, power-off and a closed lid suspend computation. Automatic recovery
requires waking the PC and signing in after a restart. This implementation
does not promise computation while the computer is off or asleep.

## Verification

Local unsigned builds pass the existing 28 native setup guards, package
verification and native detached-helper fixture under inherited process-only
Restricted policy. An additional **46 native background checks** pass, including
actual temporary Task Scheduler COM registration/readback/deletion, changed
configuration/source/executable refusal, foreign owner/elevation/action/root
refusal, expiring/restricted recovery settings, account preservation, an actual
competing process lock, cooperative idle handover, pause preservation,
stop/failure/disabled resume refusal, native turn-off, actual form construction
and preservation of the guided work choice and default schedule. The unique temporary
task is stopped and has a timer in 2099; it is never requested to start.

The real private-Python fixture starts Both while paused, observes the actual
paused status, requests a safe stop and verifies complete exit. A damaged
Python configuration is refused before Python starts and keeps a redacted
report. The guided-page fixture independently verifies authenticated page
reuse, complete close reply and imports from its copied snapshot. No real
account, service request, native inference, imagery or contribution is used.

The laptop's process sandbox refused the initial scheduler access and the
empty local page. Those failures and their fixture trees were preserved;
unchanged assertions pass with authorized ordinary Windows access. The
linked-folder staging test similarly needs ordinary access for its temporary
junction. Thirty targeted Python tests pass without skips. No security setting
was weakened, and the installed contributor was not inspected or changed.

The first CI run for application `1172df271dcb9b570aa765fb0201cefe04060a55`
passes Windows fresh-download/private-Python/paused-worker and Mac package
checks, but the real-window lifecycle times out finding the owned automatic
window. That run is not an overall pass. Its complete failure log is retained.
The automation lookup now searches descendants scoped to the exact process
because owned modal forms can appear beneath their owner; it waits for the
controls to finish their status check before closing them, and retains window
diagnostics on a failed lookup. The native form also preserves the guided work
choice when no schedule has been saved. The 46 local guards pass after these
changes; actual CI window/removal evidence must still be recorded.

The disposable Windows lifecycle workflow now tests the actual native
automatic window under Restricted, two-revision owned registration, safe
removal, update/repair and retention of synthetic private work. CI results
for this change must be recorded after the immutable source is pushed.

## Remaining release evidence

These are finite unsigned fixtures. They do not establish signed distribution,
clean nontechnical PC installation, actual accepted Scene/Object/Both work,
trusted Object admission, active native-batch handover, sleep/wake/sign-in/reboot
recovery, thermal/resource limits, disk retention or months of operation.
The broader [production checklist](PRODUCTION_ACCEPTANCE.md) remains open.
