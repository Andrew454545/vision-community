# Full reference verification — maintainer only

The [completed full Mac reference](FULL_MAC_REFERENCE_20261004.md) now passes
independent transport verification. The finite laptop matrix has started.

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
format compatibility. The completed full 1,024-location reference is now
independently verified; its subsequent PC comparison is running and remains
unqualified. See [the acceptance checklist](PRODUCTION_ACCEPTANCE.md).

The first full attempt preserved a failed receipt during the second repeat,
near its two-hour allowance. Its private archive is 475,604,211 bytes with
SHA-256 `16eb0d9f1989fb51cdc424946f58ac1eb8cb96bbb085d82a7f93c40cb6be810d`.
The original control, full capture and one full repeat are recorded complete;
three repeats are not. The receipt records `PermissionError`, without enough
detail to attribute its cause. The archive was downloaded, hash-checked and
retained; this verifier correctly rejects it as
`full_reference_not_complete_or_pinned`. It cannot approve a runtime.

The corrected private run now uses a four-hour overall bound and validated
temporary preprocessing cleanup. It has now completed all three repeats and
passed independent offline verification; neither change alone establishes
the cause of the earlier failure. A separate short Mac CI job
now exercises actual process ownership, timeout and abrupt-parent-exit fixtures
without models or imagery. Its first attempt passed actual timeout and parent
exit but exposed a test-only macOS temporary-path alias (`/var` versus
`/private/var`). The test now resolves its temporary directory before launch;
the original failed log is retained. That corrected CI rerun passes all seven
applicable process fixtures, with two Windows-only GUI tests skipped.

A separate actual supplied-executable probe then reproduced a redundant second
group stop hiding a successful timeout. Its failure remains preserved. The
[cleanup repair and bounded native recheck](MAC_TIMEOUT_CLEANUP_20261004.md)
are separate from the original full-run failure, whose receipt lacks a causal
stack. Neither short Python fixtures nor a native timeout check complete the
full reference or attest protected macOS service lifetime.

## Full Windows comparison

After completed Mac gold is available, the maintainer can run the finite matrix
using an independently recorded one-thread starter runtime-profile digest:

```powershell
python -m calibration.run_full_scene_matrix --archive <private.zip> --bytes <GitHub-byte-count> --sha256 <GitHub-SHA-256> --binary <pinned-mma-vision.exe> --models <pinned-model-folder> --runtime-profile-sha256 <independent-profile-SHA-256> --out <new-private-folder> --sample-working-set
```

The tool rechecks the entire pinned archive before inference. It uses exactly
the reference's study/search settings and saved RGB, then runs three fresh
1/2/4-thread repeats in rotated order. Each native command records private Job
CPU/committed-memory accounting, optional working-set samples, observed shared
threads and verified owned cleanup. Six hours bounds the whole matrix; every
command has its own shorter bound. A failure preserves its receipt, logs and
partial tensors; it is not silently retried or resumed.

Allow at least 32 GiB free. All PC preprocessing, normalized and pooler bytes
remain, alongside indexes and full query results. The report separates packed
vector differences, raw hash/numerical differences, score changes, selected
views, rank inversions and top-ten/top-100 sets. Runtime profiles identify the
starter's files/thread settings; the separate matrix settings record the
actual 1,024-location study configuration. Helpers and input pins are checked
again after processing. Fifteen new failure/transport guards and all 66 local
calibration tests pass; the full native matrix is now running, with no case
recorded complete at 09:26 UTC on 4 October.

All six Community CI jobs pass at `5d1bb33`. A separate private compatibility
check verifies a copy of the earlier actual 128-location PC results, all 512
views, 1,536 tensor files and twelve queries. Original hashes stay unchanged;
no new native command runs. The finite local Windows task has downloaded the
exact completed Mac artifact, verified its independent GitHub byte/hash pins,
completed offline verification and started the matrix. It checks immutable helper/runtime pins and preserves
failure instead of silently retrying inference. It neither supervises nor
changes the contributor worker. Registration alone is not restart/endurance
evidence or completed native comparison.

This is a private controlled diagnostic. It creates no account, contribution,
credit or approval policy, retrieves no live imagery and does not inspect or
change the installed background worker. It cannot settle trusted live-image
identity, protected service lifetime, provider node assignment, thermal limits
or long-running endurance.
