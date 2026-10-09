# Windowless Windows work — 9 October 2026

The owned-process runner now suppresses a console for its Windows wrapper and
direct console child even when a caller omits launch flags. A conflicting
new-console flag is removed; priority flags, argument handling, private logs,
exit codes and kill-on-close ownership remain in effect. POSIX launch behavior
is unchanged. [Microsoft documents](https://learn.microsoft.com/en-us/windows/win32/procthread/process-creation-flags)
that a new-console flag overrides no-window behavior. Test subprocesses for ownership, resource fixtures and the legacy
PowerShell launcher also avoid opening consoles.

An actual private `pythonw.exe` parent exercised three launches: omitted flags,
background priority and an explicit new-console request. Each child reported
**no console handle**, returned its expected exit code 7 and retained output;
the priority case kept its background priority. Timeout, abrupt parent death,
checkpoint preservation and owned descendant cleanup checks also passed.

| Local Windows check | Passed | Failures/errors/skips |
| --- | --- | --- |
| Process ownership, Scene indexing and resource accounting | 69 | 0/0/0 |
| Object verifier/canary, Scene search and HTTP restart recovery | 62 | 0/0/0 |
| Windows launcher and background controls | 26 | 0/0/0 |

The initial restricted invocation failed because its host temporary directory
denied writes/cleanup; its aggregate and truncated tool output remain retained.
A subsequent 69-test attempt had two resource assertions fail because a headless
`conhost.exe` remained until owned cleanup. Private probes retained that exact
state. The corrected assertions allow only the named console host at that
measurement boundary and still require verified descendant termination and
complete owned cleanup. They do not rewrite `completeAfterExit: false`, accept
an unexplained live worker or change production accounting code. Both earlier
attempts remain failures in their own receipts.

Four finite Scene test tasks from 4 October were still enabled for sign-in
despite having terminal results: one complete/unqualified and three failed.
Their current-user ownership, exact actions, configuration pins, terminal state
and absence of active runner processes were checked before disabling future
triggers. Before/after registration XML and original result hashes are retained.
No process was force-stopped. The contributor's scheduled registration was
verified unchanged; its last saved report was waiting for the unavailable
verified service with medium/day and maximum/00:00–06:00 settings.

The exact source of the user's reported random pop-up is **not yet attributed**.
The initial visible-console inspection found none. A separate, read-only,
windowless visibility trace was started with a fixed **20-minute** lifetime.
It records only terminal show/foreground events and process names/parent IDs;
it collects no titles, command arguments or typed text and closes/hides no
windows. Its result stays private and is not polled by Codex. Inspect its one
final receipt on a later work session if further attribution is needed.

These fixes do not repair the preserved round-4 diagnostic failure, start an
accepted-work soak, qualify model output or open public admission. No GitHub
Actions, imagery retrieval, production export or unrelated task/window changes
were performed. See the
[aggregate evidence and retained-file hashes](evidence/windows-console-recovery-20261009.json).
