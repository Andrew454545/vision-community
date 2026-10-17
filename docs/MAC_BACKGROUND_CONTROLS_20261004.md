# Verified Mac background controls — 4 October 2026

The Apple-silicon maintainer preview now includes `Background VISION.command`.
Its private window saves a day/night schedule, enables per-user automatic
startup, pauses/resumes work and removes its own startup job. The defaults are
Medium from 06:00 to midnight and Maximum from midnight to 06:00, using the
computer's local clock. See [the short instructions](../macos/BACKGROUND.md).

Maximum controls pacing until a parallel native profile is qualified. This
source change is not a signed Mac release or permission to contribute.

The 9 October source follow-up displays the saved report's time using the
computer's clock, separately from the owned job's running state. Missing or
invalid times display as unavailable. Saved settings/status reads enforce their
64 KiB limit on the bytes actually read, including when an earlier size check
would be stale. The page explains Medium/Maximum pacing and keeps the required
per-type approval message. These changes still need actual Mac acceptance;
see the [Windows component evidence](evidence/mac-control-clarity-windows-20261009.json).

## Startup and ownership

Each startup runs the saved system-Perl guard before private Python. It verifies
the pinned source verifier, complete immutable public-source tree and complete
private interpreter inventory. A changed source/interpreter stops before the
worker starts and preserves a private report and attention marker. A later
startup respects that marker instead of repeatedly performing the same work.
The worker uses isolated Python and a cleared inherited environment.

Saved registration receipts and loaded-job readback must match the root, user,
label, program, arguments and interval. Unfamiliar jobs are refused. Replacing
or removing a job requests a stop between batches and waits for the owned
worker's lock; it does not force-kill inference. Account, checkpoint, delivery,
pause and failure state remain in the private data folder. Changing the account
or service through these controls is refused.

Storage accounting accepts only the nine exact same-folder interpreter links
listed in the byte-pinned Python inventory, with regular targets. Unknown,
external, directory and chained links remain rejected; their bytes are not
silently ignored. The loopback control window requires its private token and
matching host/origin, bounds requests, avoids account-code logging and does not
poll after opening. Closing it leaves the separate worker registered.

## Actual evidence

Source `e9c3130` passed all seven Community CI jobs. The source-equivalent Mac
rerun at `a698313` also passes its job, including 41 setup/platform, 41 sleep/
background and 12 control guards without skips. The guarded-control fixture
reports `MAC_GUARDED_BACKGROUND_CONTROLS_VERIFIED` on `darwin-arm64`:

- verified per-user registration starts the real worker in a pre-saved pause;
- idle settings replacement preserves the same account and pause;
- all nine pinned interpreter links are accounted for;
- private window authentication, assets and quit work, with the worker separate;
- a changed isolated source is blocked before Python, with a retained report;
- attention prevents repeated launches, and the temporary job is removed.

The private interpreter is Python 3.14.8. The starter source digest is
`90688e2e56b44f579010d4d041eb53f60a73b0469c6d1d57e53dfc25bc011016`.
The deliberately separate control-fixture source digest is
`a90645da3f5c008076a97e443bbff9cd5e7466916afd4b1bdf72361779d4b8b5`.
Its negative mutation leaves the original starter and private interpreter intact.

No real account, service request, native command, imagery or contribution is
used. The earlier finite scheduled-recovery fixture additionally verifies an
interrupted offline worker resumes its saved batch/account and retains exactly
one synthetic award. Neither fixture establishes actual OS restart/sign-in,
sleep/wake, native accepted work or long-term endurance.

## Still required

Complete current native Mac downloads/dependencies and reference qualification;
finish Scenes / Objects / Both; exercise handover during actual work and real
schedule boundaries; verify sleep/wake, sign-in/restart and sustained accepted
delivery on clean Macs. Private native build jobs are currently refused before
startup by the GitHub Actions budget. Keep the [platform matrix](PLATFORM_ACCEPTANCE.md)
and [production gates](PRODUCTION_ACCEPTANCE.md) open until that evidence exists.
