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

## Remaining release work

Do not replace the distributed runtime manifest or enable admission using
build evidence. The current manifest still pins older Mac executables.
The exact candidates now pass this finite inference check. Prepare immutable
downloads, then verify guided native setup,
separate lane qualification, accepted work, shared scheduling and recovery.
Clean-device compatibility, real login/reboot/sleep and extended endurance
remain open on both platforms. See [platform acceptance](PLATFORM_ACCEPTANCE.md).
