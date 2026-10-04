# Fixed starter check evidence

The new starter path generates fixed test images locally. It does not download
calibration photographs. Andrew's unchanged supplied Mac executable completed
three fresh 112-location indexes on these inputs; this laptop completed one
fresh index at each of one, two and four shared inference threads. All six runs
finished with 448 views, complete masks and zero native errors.

These are readiness diagnostics, **not production qualification**. A release
still needs completed full-runtime qualification, independently trusted policy
and service admission. No account, contribution or credit was created here.

## Comparison

All 448 preprocessed tensor hashes match the Mac reference in every PC case.
All three PC packed indexes are identical. Every decoded view meets the
previously declared experimental `.9999` cosine / `.02` relative-L2 bounds:
minimum cosine `0.999993727250`, maximum relative L2 `0.003543760550`.
Worst raw normalized relative L2 is `0.000001839576`.

PC one- and two-thread cases have identical raw tensor hashes. Four threads
change 41 pooler and 41 normalized tensor hashes, without changing any
preprocessed tensor or packed index. The three Mac repeats have identical
packed indexes and saved native query results. This diagnostic does not compare
PC/Mac query rankings or establish sustained throughput and laptop heat limits.
The [larger photographic study](HELD_OUT_SCENE_REFERENCE_20261004.md) separately
records its near-score ranking and selected-view differences.

The Mac job first passed the original sixteen-location frozen control with
unchanged bounds and query order/views. It ran on a standard arm64 macOS 26
GitHub runner using Andrew's supplied binary. His installed hardware, provider
node choices and internal arithmetic precision remain unattested.

## Verified private evidence

The reduced Mac artifact contains normalized/pooler tensor bytes, packed indexes,
masks, source/specification, queries, logs and full tensor hash inventories.
RGB inputs were regenerated independently from pinned code and their manifest
matches byte for byte. Raw preprocessing tensors were checked in the Mac runner
and omitted from the downloaded artifact; only their hashes were compared here.
All 4,032 PC tensor transports and 2,688 downloaded Mac normalized/pooler
transports were independently checked against their inventory hashes.

| Evidence | SHA-256 |
| --- | --- |
| Generator code | `252f155e7c8d18fa1d50a4c412a10a350d2fa450b673f1318a5a2d710406120c` |
| Source fixture | `e648c1e84ee6f79cbf04f467243b66293c1e229b7046d9e64d91399e6a62baa5` |
| Generated RGB manifest | `7d1f3154b0cd29b5eb8219a13864e78ac09391738e925ce6e7e8f6e78009de24` |
| Reduced Mac artifact | `38f42d73428b3c10e4668fb82868e92f95e3116fcf1721074f52c63f16df9792` |
| Mac reference receipt | `5c0cae8ea4a00175d6fd41b6f4549d0a37c45876f03b307e5a62d159d0cf728f` |
| Mac packed reference | `dbb7fa8e92247baa12e6cfce96c771eabd4c38be891246f5a425720fc6b1e5b0` |
| All three PC packed indexes | `927c8c1609cd02c536d359035a5266cf8ba9880aef01c205aa5cf7124333c152` |
| Completed three-case PC diagnostic | `5aaeee8580886af7e3984ac9e1b656bb58f93b0083fc11ab0af7058908ebeedf` |

The supplied Mac binary remains `e0c4dc80c848af33c76bcf0e82517839d131ad62a2013a247bd70e370984dfed`;
the Windows binary remains `6ce8f5c9dbfeb8404da13daa71afecfd07a56f118fc61819d07c1d2330f191ba`.
Neither binary, model, ranker, quantizer nor numerical bound was changed.
All jobs at private commit `977c20a` pass, including the
[fixed Mac workflow](https://github.com/Andrew454545/VISION/actions/runs/37173438583).

The first PC attempt completed native indexing but the Python helper rejected
it for an ordinary-command log message absent from the study command. Its
failure report and complete native files remain private and were not counted
as a successful check. The helper now checks structured graph/model/source,
all views/tensor events, requested shared pool and native completion instead.
The three reported successful attempts used fresh output folders after this
repair. The Windows starter now includes the generator in its immutable private
source snapshot; its installed-copy guard imports and runs that generator.
The complete local Windows suite passes 441 tests in 205.074 seconds, with two
existing filesystem-link permission skips. Fifty-three targeted canary,
release, verifier and guided-flow tests also pass.
The first post-push Windows CI ran 441 tests and failed only the installed-copy
path guard on a shortened Windows temporary path. Its log remains private.
The guard now resolves the snapshot and module paths before checking containment;
all fifteen local launcher/recovery tests pass after that test-only repair.
Full CI validation of the repaired commit is tracked separately.

No production policy or updated runtime package was published. Fixed input
success cannot verify later live contributions or remove live imagery drift;
those audits still require independently trusted input identity. See the
[operator setup](RELEASE_CANARY_DATASET.md) and
[remaining release gates](PRODUCTION_ACCEPTANCE.md).
