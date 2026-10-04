# Mac unattended-processing foundations — 4 October 2026

Mac idle-sleep requests and platform-specific guided processing paths are now
implemented. Mac automatic-processing controls and a qualified release are
still unfinished. The Mac preview continues to disclose that VISION must stay
open; these checks do not enable contributions or claim months of endurance.

## Implemented behavior

- During a background batch or deliberate pacing rest, macOS receives a
  process-owned `PreventUserIdleSystemSleep` assertion. Normal completion and
  errors release it. macOS removes the assertion when its process exits,
  including an abrupt exit. No helper process, polling or persistent power
  setting is needed. The display can sleep; lid closure, explicit sleep,
  shutdown and emergency sleep remain under macOS control.
- A denied sleep request stops work before indexing; a failed release stops
  the caller. Both preserve the fixed private report and completed work instead
  of claiming that sleep protection succeeded. Allow-sleep remains explicit.
- Guided processing uses the same native executable/model paths selected by
  setup and the computer check. It no longer hardcodes a Windows `.exe` on Mac.
- A shared per-user startup contract specifies sign-in launch and a 15-minute
  recovery interval, with a five-minute throttle and no permanent rapid
  `KeepAlive` loop. Its default schedule is Medium from 06:00 to 00:00 and
  Maximum from 00:00 to 06:00, using the computer's local clock. Maximum still
  controls rests; it does not grant an unverified thread profile.
- Startup arguments carry settings, never recovery codes. Paths stay inside
  the private folder, privileges stay with the signed-in user and stdout/stderr
  do not create an indefinitely growing log. Existing bounded private status
  and failure reports remain the worker's diagnostics.

The startup contract constructs a configuration; it is not an installer.
Before real work is enabled, the guided installer must verify the immutable
interpreter/entrypoint at every launch, perform idle handover, persist and read
back registration, and connect pause/resume/settings controls. Storage accounting
must also handle the verified Mac interpreter's internal links safely.

The API behavior follows [Apple's idle-sleep assertion documentation](https://developer.apple.com/documentation/iokit/kiopmassertiontypepreventuseridlesystemsleep)
and [per-user launchd guidance](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html).
The startup design operates while the user is signed in. It cannot compute
while the computer is asleep or powered off.

## Recorded evidence

Application source `6aa43b4` passes all seven Community CI jobs. Actual
Apple-silicon macOS job `111542183691`, using the checksum-verified private
Python 3.14.8, passes 41 sleep/background checks in 0.945 seconds without skips.
The checks read back the caller's assertions from macOS, verify nested requests
release independently after an exception, and confirm that a killed fixture
caller leaves no assertion while its saved checkpoint remains unchanged.
The private bootstrap, interrupted extraction, HTTPS, snapshot and local window
checks also pass in that job; 37 setup guards pass in 2.762 seconds.

Local Windows checks pass 53 sleep/background/storage tests in 1.326 seconds;
the two actual Mac tests are correctly skipped on Windows. The full application
suite at the sleep change passes 511 tests in 334.578 seconds, with those two
platform skips and five existing local link-permission skips. The platform-path
fix separately passes its targeted setup/processing guards.

Source `f0df8b9` adds a finite real-Mac scheduling check. It registers a random
temporary agent using an isolated fake batch and a three-second diagnostic
interval. It checks the loaded program scope before interrupting only that
agent's caller, then checks scheduled recovery, the same saved fake account,
retained failure/checkpoint identity and a single disposable SQLite award across
further launches. It removes the temporary agent and retains aggregate evidence.
Real accounts, native model inference, imagery, service requests, contributions
and banked production credits are absent. The short diagnostic interval is
disclosed; it is not the production interval or an actual sleep/reboot/sign-in
test.

Actual Mac job `111544826643` passes this check at `f0df8b9`. macOS's loaded
program scope matches the configuration, its interrupted caller recovers through
the schedule, and three starts produce two completed launches with exactly one
synthetic award. The fake account and earlier failure are unchanged; the same
batch checkpoint becomes complete. The temporary agent is removed. No OS
restart or sign-in is claimed. The same job passes 41 setup/platform guards in
2.316 seconds and all 41 sleep/background guards in 0.660 seconds, without skips;
the private local window and interrupted extraction checks pass again.

All seven Community CI jobs pass for final application source `f0df8b9`:
Windows job `111544826423` passes **515 tests in 327.094 seconds**, with only
the two actual-Mac tests skipped on Windows. Linux application, Mac ownership,
Mac private starter/recovery, complete Cloudflare regressions and both 80-test
calibration jobs pass. No current source check is failing. The subsequent
documentation commit changes evidence only; tested application bytes are fixed.

Initial restricted local tests could not access their newly created temporary
folders. Approved fixture access resolved that environmental failure. A new
configuration guard also found that an empty schedule could be silently replaced
by defaults; explicit `None` handling fixes it. The corrected 21 startup/setup/
processing guards pass in 2.034 seconds, with three existing local link skips.
Earlier failures are retained privately, not relabelled as passing runs.

## Still required

Mac background installer/controls, immutable startup verification and safe
storage accounting; current native Scenes/Objects downloads and separate trusted
qualification; accepted delivery/credit evidence; Both scheduling and measured
resource budgets; clean-device sign-in, sleep/wake, update/removal and extended
endurance. The private Mac native build jobs still await an Actions budget
change; their refusal before startup is not a native processing failure.

See [platform acceptance](PLATFORM_ACCEPTANCE.md) and
[production acceptance](PRODUCTION_ACCEPTANCE.md). Admission, the existing public
Windows download and confirmed Cloudflare resources remain unchanged.
