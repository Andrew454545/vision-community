# Larger controlled Mac/PC comparison

Andrew's unchanged supplied Mac executable processed 128 new locations, captured
512 image views and replayed them three times. The PC then replayed those exact
images nine times: three each at one, two and four requested inference threads.
All indexes completed with four views per location and zero native errors.
This establishes a larger controlled comparison, **not production approval**.

The cohort excludes both the earlier sixteen-location pilot and the historical
112-location starter check. The Mac capture and three replays have identical
packed indexes, 1,536 tensor transports and native query results. A separate
verification checked the completed private artifact before any PC replay.

## Search and numerical differences

All 108 PC/Mac native query comparisons returned identical top-ten and top-100
location sets. Full location order **and** selected view match in 81 comparisons.
Two adjacent location pairs reverse order in every PC repeat; one selected view
changes in every repeat. Exact full-ranking parity therefore does not pass.

| Query | Difference in each PC repeat | Mac score margin |
| --- | --- | --- |
| `a shop` | Ordinals 61 and 104 reverse order | 0.000091369 |
| `a desert` | Ordinals 61 and 72 reverse order | 0.000019034 |
| `a snowy landscape` | Ordinal 61 chooses view 2 instead of view 1 | 0.000043313 between the two best Mac views |

The selected-view margin was independently recalculated with the native
sequential float32 compressed-cosine expression. No ranking formula, tie rule,
quantizer or quality limit was changed to conceal these differences. Maximum
native query-score difference is `0.00012452`.

All 512 preprocessed tensors match Mac bytes. Worst raw normalized relative L2
is `0.000012561254`; minimum decoded cosine is `0.999993582813`, maximum decoded
relative L2 `0.003583078807`. Every view meets the previously declared finite
experiment bounds of `.9999` cosine and `.02` relative L2. Those bounds are
not silently promoted to a production acceptance policy.

Within each PC thread setting, all three repeats have identical raw tensor
hashes and semantic search results. Across settings, normalized floats differ
slightly, at most `0.000000194430` relative L2. Every PC packed index and native
semantic search result remains identical across all nine runs. Cross-platform
packed bytes differ.

## Measured resources

| Requested threads | Median index wall time | Median index CPU time | Highest peak job committed memory |
| --- | --- | --- | --- |
| 1 | 172.286 s | 164.891 s | 677.977 MiB |
| 2 | 109.276 s | 198.906 s | 677.855 MiB |
| 4 | 95.477 s | 326.781 s | 678.336 MiB |

Four threads reduce median elapsed time about 12.6% versus two while using
about 64% more cumulative CPU time. This supports investigating different
daytime and overnight profiles. It does not establish sustainable laptop heat
limits, shared scene/object capacity or an all-core maximum.

Runs were serial, with case order rotated across repetitions and private new
indexes, checkpoints and query caches. Windows accounting includes the private
wrapper and exited descendants. All eighteen index/search operations verified
owned descendant shutdown. **Committed memory is not resident memory.** The
instrumented times include model loading and tensor writes. The matrix uses
eight-image batches; the ordinary starter uses sixteen. A separate first-112
sealed replay at sixteen produced the identical packed bytes as the matching
slice of the eight-image PC index. This checks one setting, not all future batch
sizes. See [the accounting method](WINDOWS_SCENE_RESOURCES_20261004.md).

## Why refreshing a live starter reference is insufficient

A fresh ordinary 112-location live-source index completed but fell outside the
predeclared cosine limit: minimum `0.999840435671`, relative L2 `0.017863811758`.
The same sources were then isolated with two native sixteen-image-batch cases.
Replaying the original fixed images passes, with minimum cosine
`0.999993582813` and maximum relative L2 `0.003583078807`. Retrieving images again
changes 41 of 448 decoded RGB views and yields minimum `0.999791263602` and
maximum relative L2 `0.020433435522`. Both cases complete their masks/checkpoints
and all 1,344 tensor transports. No failed comparison is counted as approval.

Thus a recent source/reference pair alone cannot make a reliable identical-input
starter check. An immutable-input check must be developed separately, without
publishing private calibration imagery or weakening contribution verification.
The isolation receipt SHA-256 is
`1e3557e98e2ba4b573858b7c631dfab62a44a695431dbc758b208e5147e42f71`.

## Limits and private evidence

The reference ran on an arm64 macOS 26 GitHub runner using Andrew's supplied
binary. It is not attestation of his installed computer, provider-node choices
or internal arithmetic precision. Twelve text-only queries over 128 records do
not establish full-corpus ranking, example-query or map-export parity. No
accounts, credits or contributions were created by these comparisons.

| Evidence | SHA-256 |
| --- | --- |
| Supplied Mac executable | `e0c4dc80c848af33c76bcf0e82517839d131ad62a2013a247bd70e370984dfed` |
| Windows executable | `6ce8f5c9dbfeb8404da13daa71afecfd07a56f118fc61819d07c1d2330f191ba` |
| Mac reference receipt | `f183a8ec34b66e541528c0a0d585b7b04c74574255a8565963b7ed9f37daf6f7` |
| Sealed RGB manifest | `12710afd39e9b2711b4b255b2fef6edf0907df2ff6475b2db91236ab6bb97138` |
| Mac packed index | `7bb6866366f087030a7c27ab8a9bf22bd000dbfaf24bd72073defa6f2067114f` |
| All nine PC packed indexes | `be4401346f587576e7f1a493f80b28ae6884d0ed964b1803179acb18b5fada26` |
| Nine-run PC resource receipt | `52552e19e06b570abd9b91d91822eaeed413bd11f9469f873b7d59960d1dbb32` |

Original draft-asset permission and native-log parsing failures remain private.
The first could not read the draft with read-only release permissions; the
second combined native stderr with JSON stdout. A separate fixed-command asset
fetch and separate native streams resolved them without changing reference
bytes or loosening comparison checks. Raw imagery, tensors, signed download
links, indexes and logs remain outside Git.
