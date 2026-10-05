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
and preserves failure receipts. At this checkpoint the jobs are queued;
native model inference has not yet been observed in this run.

Scenes uses Andrew's unchanged frozen 16-location packet and the pinned,
non-photographic 112-location synthetic reference. At each of 1/2/4 shared
threads it checks full native indexing, complete masks, every preprocessing
and vector transport, decoded comparisons and actual native search. It reports
rank/view differences and uses the existing experimental cosine/L2 limits;
it cannot grant production approval. Native children run through the existing
caller-owned process wrapper with bounded commands and separated private logs.

Objects uses all 11 pinned assets for RF-DETR, YOLOE and OWLv2, two repeats of
the same six views, an independently fetched complete one-location index and
full native verification. Its live diagnostic fixture has no independently
attested official Gen4 coverage and cannot become a contribution.

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
After actual inference, record the candidate/provider/model identity and
differences, prepare immutable downloads, then verify guided native setup,
separate lane qualification, accepted work, shared scheduling and recovery.
Clean-device compatibility, real login/reboot/sleep and extended endurance
remain open on both platforms. See [platform acceptance](PLATFORM_ACCEPTANCE.md).
