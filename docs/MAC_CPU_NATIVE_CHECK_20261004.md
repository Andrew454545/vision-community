# Current Mac CPU programs — 4 October 2026 local

The private Actions budget block is resolved. Both current Apple-silicon CPU
programs pass their locked native tests, release build and index-layout startup
in [private run 37236127846, attempt 2](https://github.com/Andrew454545/VISION/actions/runs/37236127846).
Scenes passes all 69 native tests in 0.35 seconds; Objects passes all 49 in
3.71 seconds, with no native test skips or failures. The original budget-refused
attempt is retained. This is build evidence, not
contribution approval or a finished Mac release.

| Program | Exact candidate SHA-256 | Bytes |
| --- | --- | --- |
| Scenes | `b48e9e020e5e052c9c8c5fe91d0643551be255eeeaa36cba74f975dd801394a9` | 35,526,000 |
| Objects | `d7fbe9fe4ced47762218786547511b40d6d13bc296e45ba404d6dbe6815bf5b7` | 23,709,904 |

Private source revision `e5b990b4b3a12952cdebaa9ec095fb8cefb5154f` is unchanged
by these builds. Rust 1.96.0 is confined to temporary runner directories.
Scenes uses `four-view-index`; Objects disables its default CoreML feature.
The source inventories match all 17 Scenes and 14 Objects committed inputs.
The Objects receipt records the actual PR merge commit separately.

Both binaries are arm64 Mach-O files. Their load commands declare macOS 11.0
and SDK 26.5; actual startup was observed on macOS 26.6.2. This declaration is
not proof that older macOS versions work. The observed linked libraries are
Apple system libraries, including CoreML from the bundled ONNX library; no
adjacent `.dylib` is needed in this build. Linking CoreML does not establish
that inference runs on CoreML or that every model node uses a particular
provider or precision.

The independently downloaded Actions ZIPs match GitHub's exact digests:

- Scenes artifact `11322461099`: `86a0344513ba2272c5188951e075156f316c97e6e0adabf7b71054b2f38cd3a4`.
- Objects artifact `11322650500`: `95e82aa6290f836e8e53386448eced55daca36c4573522d2a8e0414c2ca334ed`.

## Finite actual inference

Private revision `038d5d5e5a308f113f73a8430bac355b26c2ec91` adds
[finite run 37255958802](https://github.com/Andrew454545/VISION/actions/runs/37255958802).
It reuses those exact candidates, checks their source and binary identities,
and preserves failure receipts. Both actual inference jobs pass. Their private
ZIPs were downloaded independently, matched to GitHub's digests and checked
against the retained source, model and reference identities.

Scenes uses Andrew's unchanged frozen 16-location packet and the pinned,
non-photographic 112-location synthetic reference. At each of 1/2/4 shared
threads it checks full native indexing, complete masks, every preprocessing
and vector transport, decoded comparisons and actual native search. It reports
rank/view differences and uses the existing experimental cosine/L2 limits;
it cannot grant production approval. Native children run through the existing
caller-owned process wrapper with bounded commands and separated private logs.

All six complete indexes and 18 query comparisons pass. The three thread
settings produce identical packed index and search bytes within each case.
All 18 query orders and selected views match Andrew's supplied binary. Candidate
bytes differ from that binary, despite matching preprocessing hashes:

| Fixed input | Minimum decoded cosine | Maximum relative L2 | Maximum search score difference |
| --- | --- | --- | --- |
| Original 16 locations | 0.9999926663 | 0.0038298157 | 0.00010592 |
| Synthetic 112 locations | 0.9999936228 | 0.0035717019 | 0.000016236 |

Independent local checking validates all 3,072 normalized/pooler transports,
1,536 preprocessing hashes, complete masks/checkpoints and native thread
markers. The retained receipt SHA-256 is
`a2779eeadbc436626d49f6665ba4ef371023f0f067caa8f6c90841120b8726be`.
The reduced artifact `11323179136` is 10,728,594 bytes, ZIP SHA-256
`f8909dfd0aadc8d0bf5de85cc19e96ebd3d89fe701ffa0591f5c93427b90bd8d`.

The 112-location indexing commands take 256.746 / 123.508 / 132.398 seconds
at 1/2/4 threads respectively. Two threads are fastest in this one sample;
four is not automatically the best Maximum setting. These are single-run
observations on a hosted Mac, including model startup. They do not measure
sustained throughput, memory/thermals or approve a user's parallel profile.

Objects uses all 11 pinned assets for RF-DETR, YOLOE and OWLv2, two repeats of
the same six views, an independently fetched complete one-location index and
full native verification. Its live diagnostic fixture has no independently
attested official Gen4 coverage and cannot become a contribution.

All seven actual Object commands pass at one shared CPU thread. Both common
detector repeats have the same reduced output hash and 154 detections; both
hybrid repeats have the same hash and 12 detections. The independently fetched
one-location index completes in 155.287 seconds. Full native verification checks
87 files and 38 records with no indexing errors. The result's source/model pins,
repeat identities, thread markers and full verification output were independently
checked after download. This establishes execution and repeatability, not a
comparison with Andrew's Object gold or official coverage.

Object artifact `11323208539` is 5,723 bytes, ZIP SHA-256
`4a19127cae19812b0fa5ba6ab596e3427090dc3a35cd56ad84417de6aece7289`.
Its receipt SHA-256 is
`82c70c4eae0d980b3b2acc2f722cd8d475f3b12b9e8039e56068a663d0d83fcf`.

The workflow creates no account, credit, publication or production change.
Private retained evidence excludes models, raw imagery and caches. Seven
duplicate workflows triggered by the cumulative PR changes were cancelled;
the new inference run was retained. No repeated full reference captures or
unchanged native recompilation were needed. All 31 local candidate/reference
guards pass in 0.667 seconds. The existing nine Object inference guards are
also exercised on the actual Mac runner.

## Full current-runtime comparison

[Full candidate run 37271532675](https://github.com/Andrew454545/VISION/actions/runs/37271532675)
uses private source `552c292` and the exact current Scene binary above. Three
separate Apple-silicon CPU jobs each run three complete 1,024-location indexes
and twelve-query searches, at one, two or four shared threads. They reuse the
unchanged, independently verified full reference archive; they do not capture
new reference imagery. All three jobs complete all nine full trials and pass
independent checking on 5 October 2026 UTC.

Independent checking validates all 73,728 normalized/pooler transports,
36,864 preprocessing hashes, exact source/model/profile pins and all 108
query comparisons. Packed indexes, raw tensor hashes and native query results
agree across all nine repeats at one, two and four threads. Every
top-ten/top-100 location set matches the reference. Eleven of twelve queries
reorder close scores, and one selected view differs in each repeat. Minimum
decoded cosine is 0.9999800294 and maximum relative L2 is 0.0063844681; maximum
reference score difference is 0.00022419. Mac and Windows packed/query bytes
remain different; agreement on these summary metrics is not byte identity.

| Shared CPU threads | Three full index durations (seconds) | Median seconds | Median locations/hour |
| --- | --- | --- | --- |
| 1 | 2,400.166 / 2,169.706 / 2,156.399 | 2,169.706 | 1,699 |
| 2 | 1,324.191 / 1,267.693 / 1,335.248 | 1,324.191 | 2,784 |
| 4 | 955.038 / 883.973 / 940.193 | 940.193 | 3,921 |

Four threads are about 2.31 times faster than one in this complete frozen
evidence workload. These hosted Mac observations do not select a production
Maximum setting. The smaller study above has a different fastest setting;
live-image retrieval, memory, thermals, sustained scheduling and internal
precision remain outside this check.

Private artifact `11330176750` is 91,465,911 bytes, ZIP SHA-256
`c3aa9d0da83697e2464560dadd5e5b32ce9818421437725e85c53766d12ec502`.
Native receipt SHA-256:
`5aa3bd959a6c53912421d19d9130aa7cc60d81fc89ce3a0755f028fdca95f1e4`.
Independent receipt SHA-256:
`d077e8984ee758572ee108f71ae4e132d50f773eef64a5019ec3f6553d1badd1`.
Two-thread artifact `11330314673` is 91,466,184 bytes, ZIP SHA-256
`da8ff8cf282653d60709806c9526e4f11c29c599131b92772ac22a7b7c68ae0b`.
Its native receipt SHA-256 is
`56f98509b49846d7702bf288d19cd639eb317bc2cad632809d05c1717e0e8d52`;
independent receipt SHA-256 is
`becd921202569b9e5a32a9b35e1b5a607215c90eb85a1f427deb5117086666ce`.
One-thread artifact `11332087983` is 91,466,125 bytes, ZIP SHA-256
`01ecb16837a567e7f7311a2d1b5ddb76e757790755b50604606a31e60735dc67`.
Its native receipt SHA-256 is
`2ff345bdff3ede9fc8f49a48ef05c22c2ac16d02a4523df869ce51534272df1f`;
independent receipt SHA-256 is
`b5660cd741be12b94cb3c5ae173e96b12542784a357d0a3c03d002153e3bf57f`.
The complete one/two/four-thread identity receipt SHA-256 is
`a196f3880f065903f2195f7cd185dc4bf90f04aa41b229fb5f015d6aa28c21c6`.
The first local checker used Windows' thermal default while reconstructing
a Mac profile and stopped before checking cases. That failure is retained;
the corrected checker uses the unchanged Mac defaults and retains all byte
and identity checks.

Forty-two local candidate/reference guards pass. Each job has a finite
180-minute internal budget, 90 minutes per index, ten minutes per search and
200-minute outer limit. Source/model/binary pins, preprocessing hashes, complete
vector transports and repeat identities remain mandatory. Successful exports
omit raw RGB/preprocessing bytes and models; failures retain private reports.
Eight redundant cumulative-PR workflows were cancelled once, preserving this
full candidate run and the earlier complete supplied-reference evidence.
The separate [ranking-gap assessment](SCENE_RANKING_GAP_ASSESSMENT_20261005.md)
measures every inverted pair and recalculates all full-reference winning
scores before evaluating changed-view margins. It does not change admission.

## Remaining release work

Do not replace the distributed runtime manifest or enable admission using
build evidence. The current manifest still pins older Mac executables.
The exact candidates now pass this finite inference check. Prepare immutable
downloads, then verify guided native setup,
separate lane qualification, accepted work, shared scheduling and recovery.
Clean-device compatibility, real login/reboot/sleep and extended endurance
remain open on both platforms. See [platform acceptance](PLATFORM_ACCEPTANCE.md).
