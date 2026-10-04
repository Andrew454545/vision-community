# PC check storage and idle-sleep safeguards

The updated starter clears 337,182,720 bytes (about 322 MiB) of temporary files
after a freshly completed fixed-input PC check receives independent service
approval. It verifies the saved report, pinned source/reference/manifest,
completed index/masks and every native tensor transport before deleting any
file. Targets are only the exact 448 synthetic RGB files and 448 preprocessing
tensors in that attempt. There is no recursive deletion or old-folder scan.

Reports, logs, indexes, checkpoints, manifests and small normalized/pooler
tensors remain. A receipt lists omitted files and hashes. Failed, rejected,
diagnostic-only and legacy attempts retain their files. Changed/linked files
stop cleanup; interruption leaves an incomplete receipt and preserves service
approval. Contribution, delivery and account recovery files are outside this
cleanup. General retention and long-term disk growth remain open.

Forty targeted tests pass, including full-size synthetic filesystem fixtures,
late checksum failure, incomplete masks, path escape/link rejection, partial
deletion and guided service approval order. The complete local Windows suite
for this change passes 453 tests in 225.055 seconds, with two existing
filesystem-link permission skips. These fixtures do not simulate production
inference or grant qualification. Live approved-release cleanup remains open.

The worker now checks both Windows idle-sleep API return values, restores the
previous thread flags and preserves a failure report before stopping if either
call fails. Pacing-rest failures are caught as well. The status field
`idleSleepPreventionRequested` describes the chosen setting; it does not claim
that Windows accepted an unobserved request.

A finite diagnostic on this laptop invokes the real API on its own thread.
Request `0x80000001` succeeds with previous state `0x80000000`; restoring
`0x80000000` succeeds with previous state `0x80000001`. No power plan, display
or away-mode setting was changed. Thirty-one sleep/background tests pass,
including release after an exception, prior-state restoration, denied calls,
preserved reports and exit without another batch. The API's return and flag
semantics are documented by [Microsoft](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-setthreadexecutionstate).
After the sleep change, the complete local Windows suite passes 461 tests in
224.116 seconds, with the same two filesystem-link permission skips.

This diagnostic does not exercise actual sleep/wake, sign-in recovery or
overnight load. The installed worker was not changed or polled; existing
calibration and failed-check files were not compacted. No production profile,
runtime release, account, credit or contribution was created. See the
[remaining acceptance gates](PRODUCTION_ACCEPTANCE.md).
