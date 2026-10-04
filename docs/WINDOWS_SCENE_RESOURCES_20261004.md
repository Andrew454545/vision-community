# Frozen Windows scene resource check

Nine fresh sixteen-location replays completed: three each at one, two and four
requested inference threads. All 27 native query orders and selected views
matched Andrew's supplied sample. The observations remain **unqualified** and
do not establish sustained throughput, a production thread profile or thermal
limits.

| Requested threads | Median index wall time | Median index CPU time | Highest peak job committed memory |
| --- | --- | --- | --- |
| 1 | 23.856 s | 22.609 s | 671.863 MiB |
| 2 | 15.754 s | 26.750 s | 672.395 MiB |
| 4 | 14.396 s | 43.672 s | 672.613 MiB |

Four threads reduced median elapsed time by about 9% relative to two, while
using about 63% more CPU time. Actual cumulative CPU/wall ratios increased
with the requested threads, providing evidence of parallel execution within
these operations. This small instrumented study includes model loading, tensor
writes and new query profiles. It is not a long-running speed or heat test.

Every run used the same 64 sealed RGB views, canonical model pins and unchanged
Windows executable SHA-256
`6ce8f5c9dbfeb8404da13daa71afecfd07a56f118fc61819d07c1d2330f191ba`.
Case order rotated across repetitions. Each case had separate indexes,
checkpoints, evidence and native search caches. Complete masks, checkpoints,
192 tensor transports and all native hits were checked independently.

All preprocessed image tensors matched Mac bytes. Maximum raw normalized
relative L2 was `0.00003617043123671944`; minimum decoded cosine was
`0.9999926663366517`, maximum decoded relative L2 `0.0038298156673653686` and
maximum native query-score difference `0.00010595`. Packed index bytes differ.
These are measured differences, not newly fitted production tolerances.

## Accounting and retained failures

[The diagnostic adapter](../calibration/windows_resource_measurement.py) queries
Windows' private Job Object once, before owned cleanup, and keeps kill-on-close
protection. Cumulative accounting includes exited native descendants and the
private Python wrapper. Peak **committed memory is not working set or total
physical-memory pressure**. No recurring sampler or Codex check-in is added.
The structures and units follow [Microsoft's accounting API](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-queryinformationjobobject).

Windows' console host could remain active after the native program exited.
Its executable name was recorded without its path. The adapter retains process
handles and verifies shutdown after Job Object close, with a three-second total
wait bound. All eighteen operations passed owned cleanup. Before-close activity
and after-cleanup verification are separate fields, including for a timeout.
CPU counters end at the recorded before-cleanup cutoff.

The first measurement guard exposed cleanup interruption during an injected
accounting error and an incorrect user-only CPU assertion. Both were repaired;
total user-plus-kernel CPU is required. Regression checks exercise actual owned
subprocess CPU/memory, exited and living descendants, nonzero exit, timeout and
unavailable accounting. An isolation guard refuses concurrent callers. A later
guard injects a failed descendant wait and requires repeated close to retain
that failure. Measurement errors are reported after ownership cleanup.

Two private matrix failures remain: a relative diagnostic path prevented the
first native start; the next completed inference but incorrectly required the
console host to exit before owned cleanup. Neither failure changed model,
numerical, ranking or completeness checks. The corrected run uses absolute
paths and verifies owned shutdown explicitly. Receipt SHA-256:
`9993882963f7f090b3b4aec00ab810546c8e3beccd2ae96c956e1a1a3debaab9`.
Resource adapter SHA-256:
`1b0cf3e7c8ad3b8a9915820c4224ad9ddf33f9c9c3b59cd7f270ca76983fc5fc`.

No accounts, contributions, credits or live imagery were used. Raw imagery,
tensors, output indexes and process logs remain private, outside Git.
