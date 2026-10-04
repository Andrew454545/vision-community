# Windows scene memory observation

Three fresh fixed 112-location native runs completed, one each at one, two and
four requested inference threads. All 448 views, masks and 1,344 tensor byte
files per run were checked. Packed PC results match the previous same-input
diagnostic exactly; all preprocessed hashes match the unchanged Mac reference.
This remains **unqualified exploratory evidence**.

| Requested threads | Owned-operation wall time | Cumulative CPU time | Largest sampled sum of working sets | Peak job committed memory |
| --- | --- | --- | --- | --- |
| 1 | 158.368 s | 150.906 s | 796.504 MiB | 956.297 MiB |
| 2 | 96.977 s | 177.250 s | 797.109 MiB | 956.723 MiB |
| 4 | 83.135 s | 285.438 s | 797.414 MiB | 956.953 MiB |

Four threads saved about 14% elapsed time relative to two while consuming about
61% more CPU time. This is one instrumented run per setting, in 1/2/4 order,
including model loading, new text-query profile construction and tensor writes.
It cannot establish a sustained production profile or a maximum for other
devices. The earlier rotated photographic study is recorded separately in
[the controlled reference report](HELD_OUT_SCENE_REFERENCE_20261004.md).

## What the memory readings mean

The optional diagnostic observer samples only its own private Windows Job
Object every 250 milliseconds. Before reading counters, it verifies each
process is still a member and holds its process handle to prevent PID reuse.
It uses [Microsoft's process memory counters](https://learn.microsoft.com/en-us/windows/win32/api/psapi/ns-psapi-process_memory_counters)
through [K32GetProcessMemoryInfo](https://learn.microsoft.com/en-us/windows/win32/api/psapi/nf-psapi-getprocessmemoryinfo).
All four accounted processes were observed in each run: 614, 377 and 323 samples
respectively. Each observer stopped and all owned descendants were verified
stopped after native completion; the remaining console host was handled by the
existing private kill-on-close Job.

These are **sampled sums**, not an exact simultaneous peak or unique physical
RAM use. Reads across processes are sequential, shared pages can be counted
more than once, peaks between samples can be missed, and short-lived processes
can escape observation. Receipts explicitly report process coverage. GPU
memory, temperature, battery effects, overnight stability and simultaneous
scene/object pressure were not measured. Committed-memory accounting remains
a separate metric. Production budgets and maximum processing stay open.

The observer is opt-in for finite, isolated diagnostic commands. The background
worker gains no sampler or Codex check-ins; its installed files and schedule
were neither inspected nor changed. The diagnostic's own system-only sleep
request was accepted and its prior thread flags restored. Actual sleep/wake
and sign-in endurance remain separate tests.

## Integrity and validation

Every PC packed payload has SHA-256
`927c8c1609cd02c536d359035a5266cf8ba9880aef01c205aa5cf7124333c152`.
Minimum decoded cosine against Mac is `0.9999937272496635`; maximum relative L2
is `0.003543760549555531`. Existing experimental bounds were unchanged.
No account, contribution, credit or live imagery was used.

The private native receipt SHA-256 is
`744bfa6bf2ecb4279eae7fb0498effd0363bbdc195b41672c4ab08bdb93a5ee6`.
It records adapter SHA-256
`2ed0c536b99dcd76b7f2f357aafab7b8f32de9c4f1e3a3e25205be92ee437dd4`;
that exact adapter is retained with the evidence. Its preliminary receipt field
called the sampled sum a simultaneous lower bound. That wording was too strong
because reads are not atomic. The report remains unchanged; the interpretation
above supersedes that field. The current adapter explicitly describes these
limits and rejects an invalid process-wait result instead of treating it as live.
The observer also keeps its original private job identity and refuses periodic
samples after stopping, preventing fallback to the caller's job during cleanup.
These corrections change no models, inference, packing or numerical bounds.

All 51 calibration tests pass in 6.012 seconds, including actual touched-memory
children, timeouts, rejected process membership, unavailable counters, invalid
wait state, stopped-job isolation, owner cleanup and factory restoration. The
measured process-owner source was
`019fc3c055eb680dab4bfafd4851d3a082580f1a3a115b7ca6016a6433726f7f`.
A subsequent [Mac timeout cleanup repair](MAC_TIMEOUT_CLEANUP_20261004.md)
changes that helper; these measurements remain evidence for their original
bytes. New exact-runtime qualification is required before shipping the repair.
Raw inputs, tensors, receipts, source snapshot and logs remain private.
