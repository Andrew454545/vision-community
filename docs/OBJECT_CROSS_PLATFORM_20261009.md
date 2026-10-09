# Saved-input Mac and Windows comparison — 9 October 2026

Fresh Windows indexing now agrees closely with the instrumented Mac reference
on three distinct saved locations. Detection presence, classes, view/support
selection, quality masks, search hit sets and order agree. Stored PQ codes also
agree. Floating-point scores and aiming differ slightly, so the outputs are
not byte-identical. These are exploratory measurements, not production approval.

## What ran

The private Mac handoff includes 27 one-location cases: CPU build/CPU,
CoreML-enabled build/CPU and CoreML-enabled build/CoreML, each at 1/2/4 threads
with three repeats. Every case completed indexing, four actual searches and full
native verification before/after search. All 3,209 supplied files were checked
against the independently supplied archive and file-manifest checksums.

A fresh Windows CPU/four-thread build passes all 64 native tests and indexes
the exact same saved location in 64.250 seconds. Comparing that output with
the 27 Mac cases, and comparing each Mac case with the first Mac CPU case,
produces 54 comparison pairs. These reuse one location, not 54 independent
location trials. The two Hot searches are empty on this location.

A separate saved pair exercises nonempty Common, Hot nest, Hot clock and
diagnostic zero-floor Semantic searches. Its source IDs are explicitly mapped
from two rows of the original cohort; exact TSV, PNG, decoded pixels and query
pins match on both platforms. Fresh Windows indexing finishes in 126.531
seconds and passes native verification before/after search. Query hit counts
are `[2, 1, 1, 2]` on both platforms, with identical hit sets/order. Hot hits
are model observations, not human-confirmed true positives.

| Measurement | One-location Windows/Mac comparisons | Separate two-location pair |
| --- | ---: | ---: |
| Missing/extra detections or search hits | 0 | 0 |
| Discrete detection or quality-mask differences | 0 | 0 |
| Maximum stored detection score difference | 0.000017204 | 0.000033692 |
| Maximum returned search score difference | 0.0000000103 | 0.000015270 |
| Search order changes | 0 | 0 |
| Stored PQ code differences | 0 | 0 |

Returned confidence is quantized; the pair's clock-score difference is
approximately one 16-bit confidence step. This observation does not justify
a universal production tolerance. The aggregate values are preserved in
[the evidence record](evidence/object-cross-platform-20261009.json).

## Repairs and preserved failures

Windows checkout previously converted native source to CRLF. Because the
quality implementation identity embeds four exact source files, this changed
the identity despite matching Git code. The private repository now enforces LF.
The new build uses byte-identical Mac native source and matching quality identity.
Old binaries, manifests, failed comparisons and their raw source pins remain;
no identity check or manifest was altered to make a comparison pass.

Before this repair, the Windows one-location 1/2/4-thread matrix completed all
nine cases with matching stored files and replies within that Windows build.
Its larger 16-location case timed out at the unchanged 900-second indexing
limit after ten rows. It remains failed and its partial output is not compared
as a complete index. The successful separate pair does not replace that failure.
Batch size, lease timing and sustained throughput still need qualification.

A separate Windows readback of a copied Mac index refused its original absolute
Mac source-path binding. The original manifest and failure remain intact; that
attempt did not complete a Windows search on the 16-location index. Portable
bundle materialization must preserve independently verified content and make
local path mappings explicit rather than silently rewriting reference evidence.

## Limits

Only three locations have completed cross-platform comparisons. All their
views were kept: no positive blur rejection, protected location or tunnel
authority was exercised. The historical Gen4 labels are not current independent
official-coverage evidence. Source/build correspondence to the historical
installed gold executable remains unattested. The new source and builds have
explicit identities and are not claimed as that installed executable.

Mac execution traces report CoreML nodes for all four model roles and some CPU
fallback; arithmetic precision and ANE/GPU/CPU hardware placement remain
unattested. Single-model traces are not proof of placement throughout indexing.
Timings include loading/cache costs on used development computers and are not
exclusive-machine benchmarks or endurance evidence. No GitHub Actions, fresh
imagery, Community submission, credit or device approval was created.

Trusted admission, broader reference/tolerance evidence, accepted-work endurance,
signing, clean-device onboarding and production recovery remain open in the
[acceptance checklist](PRODUCTION_ACCEPTANCE.md).
