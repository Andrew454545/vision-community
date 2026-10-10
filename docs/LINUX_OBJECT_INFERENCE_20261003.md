# Linux object inference: 3 October 2026

A fresh Ubuntu 24.04 x86-64 runner completed real CPU object processing,
repeatability and a full location index. This closes the missing Linux inference
check; it does not approve production Objects or establish Mac/reference parity.

All 11 models matched the pinned Community manifest, SHA-256
`b086083e00e527164b0433579a34d7a8141b05ed492081a4c1aa2f14a9164e87`.
The locked CPU build passed 49 native tests. Its binary SHA-256 is
`418642ee24cdf964cf8a6a74c0752d3c9bc76ffca96edf9525d06e59bc3293b4`.

Six freshly retrieved 640×640 views were captured once. RF-DETR and
YOLOE/OWLv2 each ran twice on those same files. Every output value repeated
exactly; input and output hashes stayed unchanged. Each native command confirmed
one shared ONNX thread with spinning disabled.

| Check | Seconds |
| --- | ---: |
| RF-DETR repetition 1 / 2 | 24.735 / 24.281 |
| YOLOE + OWLv2 repetition 1 / 2 | 93.633 / 92.512 |
| Complete six-face location index | 117.236 |
| Native full verification | 0.032 |

Index and checkpoint completed with zero fetch/inference errors. The index used
its own imagery retrieval; it was not a replay of the captured detector fixture.
Peak child RSS was 2,852,812 KiB, measured across the run. These timings include
model loading and are not a representative throughput or parallel benchmark.

The first Linux guard check detected an unexpected system-information subprocess
before pin validation. That failed job is preserved. Removing that subprocess
made all nine diagnostic guards pass on Windows and Linux. The corrected private
workflow at `3214c92df3a04cb1a66ac0b5cd3038883186d7a2` completed successfully,
including actual Linux inference job `111184519420` in run `37116601316`.

The small private inference artifact was independently downloaded and its
GitHub-recorded SHA-256 verified:
`4813616fceb5167326cde3912998082532745867ce458a3a4bb1cc5f7b146b2f`.
The receipt SHA-256 is
`ed29d427539ff15221b17e7737f0f2d19cc6cc4b2296ea45ff04875f9dc566be`.
Only hashes, diagnostics and logs were retained in that private artifact;
imagery, models and native indexes were excluded. No contribution, account,
search credit, R2 write or global installation was created by this check.

Clean-device dependency closure, distributed packages, broader identical-input
reference comparisons, trusted historical official Gen4 coverage, independent
object inference audits and measured parallel budgets remain release gates.
