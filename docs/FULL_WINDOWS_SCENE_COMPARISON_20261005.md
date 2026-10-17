# Full identical-input Windows Scenes comparison — 5 October 2026 UTC

**All nine full trials are complete and independently verified. Production
qualification remains separate.** Each thread setting (1, 2 and 4) has three
complete 1,024-location indexes and twelve-query native searches, using the
same frozen 4,096 RGB views as Andrew's supplied Mac reference.

Four previously executed native indexes were retained and independently
reverified; five remaining indexes were newly executed. The fourth retained
case uses a fresh measured search because its original resource report failed.
Neither that failure nor the older time-limit/inventory failures were erased
or relabelled as passing. See [the accounting recovery](WINDOWS_MATRIX_ACCOUNTING_RECOVERY_20261004.md).

## Identity and independent verification

The supervisor uses an isolated, byte-checked snapshot of public source
`741c6da3870b6b70a737c4c798aae43eb3e2de28`: 276 tracked files plus two operator
helpers. The final packaged Windows executable remains
`6ce8f5c9dbfeb8404da13daa71afecfd07a56f118fc61819d07c1d2330f191ba`.
Inputs, models, helpers, exact thread profiles and reference remain unchanged.

A separate offline verifier rechecks all nine original cases, all **110,592 raw
tensor files**, including 36,864 preprocessing files, complete masks/checkpoints,
packed payloads, source/runtime/model pins, the complete Mac reference and
every numerical/query comparison. It starts no native command. Every
preprocessing hash matches Mac; omitted Mac preprocessing bytes cannot be
compared directly.

All nine PC packed indexes have SHA-256
`817cc2f592e954582a60359261c706c536f0e2b0a302286546e218de58d9ef47`.
Their native query results also agree exactly across the nine runs. Repeated
raw tensors agree within each thread setting. Four threads differ from one
thread in 712 of 12,288 first-run tensor hashes; two threads have no differences.
Packed-index identity does not establish raw floating-point identity.

The completed native receipt SHA-256 is
`88ef92613ca5254ca3e44ba27c67b11b2184586f5d3f38d7166074e4a7b36173`.
The independent verifier receipt SHA-256 is
`ce83a777fea953b496f905cbc2b9e4a52508d0bc60e87ab2bb19f180f564f6e9`.
The verifier's first local attempt stopped on integer/string JSON key types
before checking cases; that failure is preserved. The corrected verifier
normalizes only these thread-key representations and retains all file checks.

## Comparison with Andrew's reference

All 108 PC/reference query comparisons match the top-ten and top-100 location
sets. Only the road query preserves the complete order and selected views:
eleven of twelve queries reorder some close scores, with a maximum displacement
of six positions. The snowy-landscape query selects one different view in each
repeat. Maximum score difference is 0.00022419.

Minimum decoded view cosine is **0.9999800294**; maximum relative L2 is
**0.0063844681**. Maximum normalized/pooler tensor relative L2 is
0.0000163785 / 0.0000163858. These fall within the unchanged exploratory
0.9999 cosine / 0.02 relative-L2 bounds. They do not themselves define a
production tolerance or approve live contribution inputs.

## Full-trial processing observations

| Shared CPU threads | Trial indexing seconds | Median seconds | Median locations/hour |
| --- | --- | --- | --- |
| 1 | 8,142.7 / 7,813.2 / 8,092.0 | 8,092.0 | 455.6 |
| 2 | 4,184.9 / 4,228.2 / 4,021.9 | 4,184.9 | 880.9 |
| 4 | 2,246.7 / 2,225.0 / 2,234.7 | 2,234.7 | 1,649.6 |

Four threads are about 3.6 times faster than one in this full frozen workload.
Median measured cumulative CPU seconds per wall second are 0.965 / 1.896 /
3.659. Every index records successful caller-owned descendant cleanup.
Maximum sampled working-set sums are approximately 788 / 788 / 789 MiB;
peak job committed memory stays below 961 MiB. These are different memory
metrics; samples are not atomic and shared pages can be counted more than once.
This is useful sustained scene evidence on this laptop, not an all-device
maximum, thermal test or shared Scenes/Objects capacity approval. Its evidence
export workload also differs from ordinary live contribution processing.

No account, contribution, credit, new imagery retrieval or production change
is made by the trials or offline verification. The installed contributor is
not inspected or modified. Qualification, trusted live input identity,
accepted background recovery and both-platform release requirements remain in
[production acceptance](PRODUCTION_ACCEPTANCE.md).
