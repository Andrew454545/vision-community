# Windows matrix accounting recovery — 4 October 2026

Four complete 1,024-location native indexes are independently verified and
retained. The first cohort took 135.711, 69.748 and 37.445 minutes at one, two
and four threads respectively: about 1.95× and 3.62× faster than one thread.
A second two-thread index took 70.470 minutes. All four packed indexes are
identical. These are individual controlled runs, not sustained throughput or
production approval.

The second two-thread search finished all twelve queries and exited with code
zero, but the old Windows resource reporter failed afterwards. Its original
failed report, native output and resource receipts remain unchanged. The old
helper did not save the failing API or error number, so the exact original
cause is unknown.

The reporter now handles a demonstrated process-exit race: a process name
read can fail after the process exits. It checks membership in the owned job
before reading the name and accepts this case only when the same held process
handle confirms exit. A live process name failure, failed state check, foreign
process or oversized process list still rejects the measurement. Failures
record their stage and Windows error; descendant cleanup remains mandatory.
This follows Microsoft's [process-name API](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-queryfullprocessimagenamew)
and [process-wait states](https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-waitforsingleobject).

Twenty resource guards and all 80 calibration tests pass locally. Five added
Windows fixtures cover actual owned-process exit with a failed name read,
live failure, failed wait, membership rejection and process-list overflow.
These demonstrate the repair; they do not establish the old failure's cause.
The first Windows CI attempt failed the timed exit fixture; that log is retained.
The fixture now requests exit only after ownership is checked, rather than
depending on a short sleep. All 80 local guards pass again in 9.651 seconds.

Twenty-four fresh native readers of the retained second two-thread index also
finish all twelve queries with exact original results, complete resource
receipts and verified descendant cleanup. They use fresh cache/output folders
and change no original index. None observed the injected fixture's name-read
race. The new receipt explicitly uses a newly measured read-only search for
the fourth case; it never relabels the original failed measurement as passing.

The separate offline recovery verifies every original native tensor and result
file in all four cases, the unchanged runtime profiles and the complete Mac
reference. No new indexing command runs during recovery. Preprocessing hashes
match Mac for all 4,096 views in each case; Mac preprocessing bytes are absent,
so this remains hash-only comparison. All twelve top-ten and top-100 sets
match Mac, with the score, rank and selected-view differences already disclosed
in the [earlier recovery report](FULL_PC_MATRIX_RECOVERY_20261004.md).

The first PC query results are identical across thread counts. One and two
threads have identical raw tensor hashes; four threads differ in 712 of 12,288
tensor files while preserving the packed index and query results. The repeated
two-thread case has no tensor or query differences from its first run. Raw
floating-point identity must not be inferred from packed-index identity.

The private recovery receipt has SHA-256
`964fa7438144c5c30861d035655fe6b1a6b56672ddc829e97880068fa44e7eaf`.
Twelve private continuation safeguards pass, including configuration/source
pins, exact retained execution provenance, verified launch permission and no
automatic repetition after a started attempt. Five fresh rotated trials remain.
An isolated version adds a thirteenth guard rejecting foreign source imports.
All 276 tracked public files were copied and byte-checked in a new private tree;
278 pins cover that tree and its two operator helpers. A fresh interpreter
imports only this copy and passes all 80 calibration tests in 9.688 seconds.
Further repository edits cannot change this trial source.

The limited own-user Windows task is registered after actual settings readback,
with one-instance protection, no automatic native retry and a 40-hour outer
limit. Its supervisor started at 20:23:12 UTC and rechecks the four retained
cases before five new trials: four/one threads for replica two, then four/one/two
threads for replica three. It has a 36-hour internal limit, four hours per index
and ten minutes per search. A started supervisor is not proof of new inference.
The installed contributor remains unchanged; this finite comparison is separate
from ongoing contribution recovery.

All six Community CI jobs pass at `741c6da`, including both 80-test calibration
jobs and all 482 Windows application tests. The initial timed-fixture failure
and private test-discovery setup failure remain retained. Neither was counted
as a passing run.
The full repeats, held-out tolerances, trusted live contributions and actual
restart/endurance checks remain release gates. No accounts, submissions,
credits or uploads are created by this recovery; the installed contributor is
not inspected or modified.

Follow-up on 5 October: all five remaining native trials complete. A separate
offline verifier checks all nine retained/new cases, 110,592 raw tensor files
and every reference/query/repeat comparison. See [the completed full
comparison](FULL_WINDOWS_SCENE_COMPARISON_20261005.md). This closes the finite
trial continuation; production qualification and the earlier failures remain
separate.
