# Full reference verification — maintainer only

Before new PC repeats, obtain the completed private Mac artifact and its exact
byte count and SHA-256 from authenticated GitHub metadata. Keep its original
archive. Use a new output folder outside the public checkout:

```powershell
python -m calibration.verify_full_scene_reference --archive <private.zip> --bytes <GitHub-byte-count> --sha256 <GitHub-SHA-256> --out <new-folder>
```

This offline tool downloads nothing and runs no native program. It bounds ZIP
size, entry count, paths, links and disk use before extraction. It checks the
unchanged supplied Mac binary pin, original control, complete 1,024-location
fixture, exact RGB bytes/pose/model inventory, FP32 evidence, masks, saved
vectors, twelve full query results, observed one-thread pool and all three
repeat identities. Failed or incomplete references cannot be called complete.

The receipt preserves failure codes and marks raw preprocessing tensors as
**hashes only**; those bytes are omitted from the artifact. The original
control's RGB bytes are also omitted and were checked in the Mac runner.
Full-cohort RGB and retained normalized/pooler tensors are checked locally.
No reference receipt grants production qualification, contribution credits or
official Generation 4 coverage.

The 43 calibration tests pass in 3.683 seconds. A separate read-only check on
the existing three Mac 112-location repeats verifies all 448 regenerated RGB
files and 2,688 retained normalized/pooler transports with this verifier.
Its 1,344 preprocessing entries remain hashes only. These checks establish
format compatibility; the running full 1,024-location reference and subsequent
PC comparison remain open. See [the acceptance checklist](PRODUCTION_ACCEPTANCE.md).

The first full attempt preserved a failed receipt during the second repeat,
near its two-hour allowance. Its private archive is 475,604,211 bytes with
SHA-256 `16eb0d9f1989fb51cdc424946f58ac1eb8cb96bbb085d82a7f93c40cb6be810d`.
The original control, full capture and one full repeat are recorded complete;
three repeats are not. The receipt records `PermissionError`, without enough
detail to attribute its cause. The archive was downloaded, hash-checked and
retained; this verifier correctly rejects it as
`full_reference_not_complete_or_pinned`. It cannot approve a runtime.

The corrected private run now uses a four-hour overall bound and validated
temporary preprocessing cleanup. It is running; neither change alone proves
completion or fixes a cleanup permission failure. A separate short Mac CI job
now exercises actual process ownership, timeout and abrupt-parent-exit fixtures
without models or imagery. Retain its evidence before making a Mac cleanup claim.
