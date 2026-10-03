# Windows object calibration, 2026-10-02

The private Windows CPU candidate processed all three object model lanes and
completed a full six-face location index. This is exploratory evidence, not
production approval or a comparison with Andrew's installed Mac executable.

## Frozen-image thread study

Three repetitions used the same six saved views at each of 1, 2 and 4 threads.
Every process confirmed one shared inference pool with spinning disabled.
All 18 commands completed; the input checksums stayed unchanged. Every output
value and view ranking matched the single-thread baseline exactly in this sample.

| Model lanes | CPU threads | Median seconds | Peak memory, GB |
| --- | ---: | ---: | ---: |
| RF-DETR | 1 | 39.109 | 1.008 |
| RF-DETR | 2 | 24.141 | 1.008 |
| RF-DETR | 4 | 15.172 | 1.008 |
| YOLOE + OWLv2 | 1 | 168.468 | 2.186 |
| YOLOE + OWLv2 | 2 | 115.422 | 2.186 |
| YOLOE + OWLv2 | 4 | 66.359 | 2.186 |

Times include model loading in fresh processes. Memory is the measured peak
process working set in decimal GB. The laptop was not isolated from other work.
These are detector diagnostics on one location; they do not measure complete
index throughput, broad accuracy or Mac/reference parity.

## Actual Community command

The Community CPU command completed a new full location at one shared thread
and 25% duty in 817.953 seconds. Both native verification passes succeeded;
the index/checkpoint completed with zero fetch or inference errors. Indexing
and verification each confirmed the shared pool. The earlier candidate completed
a separate 100%-duty index in 47.875 seconds using unconfigured per-model pools;
that result is not an equivalent controlled resource comparison.

CPU jobs now checkpoint and end each native run after one location, then resume
through the existing bounded retry loop. That avoids hours between checkpoints
on slow PCs. Higher CPU thread counts remain a separate admission decision;
Mac reference batching/settings are preserved.

## Packaging and remaining gates

Both private CPU builds pass 49 native tests. Downloaded archives, binaries,
observed dependencies and source identities were independently checked.
All 11 model files matched their pinned checksums. Declared Windows imports
exposed four additional Microsoft compiler runtime DLLs. The updated private
package includes these beside the executable, with valid compiler-source
signatures and independent file checksums. Both new builds pass 49 native tests;
their archives, source and build-helper identities were independently verified.
On this laptop, real processing loaded all four compiler DLLs and DirectML.dll
from the package folder with matching checksums and a restricted environment.
RF-DETR and hybrid processing of the same six saved views again matched every
earlier Windows output value and ranking exactly. No global installation was
needed. This does not prove a clean-PC package or complete dynamic dependency
closure, and loading DirectML.dll does not establish GPU inference.

No accounts, accepted contributions or search credits were created by these
checks. Raw images, indexes, diagnostic outputs and build receipts remain private.
Production still needs frozen production-path/reference object comparisons,
broader locations, clean Windows/Linux inference, trusted historical Gen4
coverage and trusted inference audits. No production object gate was opened.
