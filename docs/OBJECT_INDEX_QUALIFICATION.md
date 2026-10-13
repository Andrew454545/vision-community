# Object sample: scores and saved index features

**Source only, inactive.** The read-only
[sample comparator](../community/object_index_qualification.py) now combines the
[detector score check](OBJECT_SCORE_QUALIFICATION.md) with complete native v4
indexed-feature and quality comparison for the **same 100–112 locations**.
It fetches nothing, runs no models and cannot qualify an account, publish work
or create search credit. No human object-presence labels are needed.

The trusted operator pins a separate index policy and reference bundle. That
bundle names the detector fixture, its reference provenance, ordered case IDs,
exact source TSV, native `vision-object-frozen-rgb-v1` manifest and reference
index. Each native row hash must match the exact TSV bytes; each ordered face
must name the actual PNG already pinned by the corresponding detector case.
Both index manifests must declare that native frozen manifest's hash. Changing
the rows, face order, fixture, reference provenance or input marker fails closed.

The new policy pins the existing score policy and source files. The score
policy still supplies the confirmed environment/resource pair, individually
pinned Mac/Windows profiles, models, validity and conservative detector bounds.
The sample must retain at least 100 usable locations; native fetch/inference
errors and permanently invalid locations cannot pass the combined check.

The comparator revalidates every indexed file's hash, complete v4 envelope,
checksums, finite values, location offsets, metadata and global IDs. It measures
common/hot scores, confidence and aiming coordinates; packed semantic boxes
and float16 logit calibration; selected faces and quality rejection masks.
Missing/extra hits, changed discrete selections/support, changed quality masks
or changed PQ code bytes cannot pass. Numeric bounds can be stricter than the
existing native audit ceilings, but cannot be widened by a client or policy.
In particular, matching average scores cannot hide a quantization difference.
Exact PQ codes are the existing conservative starting rule, **not** an assertion
that measured Mac/PC output already meets it. Changing that rule would require
separate measured compatibility evidence.

The trusted caller supplies a saved local candidate manifest and checksum. The
comparator never follows a client JSON path. Reference/candidate/source files
and policies are rechecked after measurement, with a finite 60-second request
budget and the score comparator's 20-second sub-budget. Index files are bounded
to 32 MB, manifests/source to 1 MiB, and the detector packet remains at most
8 MiB. Errors expose fixed codes rather than private paths or submitted data.

`sampleCompatible` combines independently recomputed `scoreCompatible` and
`indexCompatible`; the result binds the policy, fixture, runtime profile,
detector submission and candidate manifest hashes. It still returns
**`qualified:false`**, zero contributions/credits and no `approved` field.
`identicalInputBindingVerified` describes checked files and declared input
identity. It does not attest that an untrusted machine executed those pixels;
RGB decoding, authentic inference and native search rankings are not attested.
The nested offline index comparison retains its false provenance/pixel/search
approval flags. No frozen diagnostic artifact becomes publishable.

Next connect this complete numerical result to authenticated reusable
account/profile qualification and revocation. Routine Object publication still
needs fresh official Gen4, Scene membership and protected-source authority,
distinct qualification-based provenance and atomic once-only credit. Keep the
fully audited route separate. Real platform qualification and the remaining
[launch gates](PRODUCTION_ACCEPTANCE.md) remain open; activation is still held.

[Windows evidence](evidence/object-index-qualification-20261013.json): **118
checks passed without skips**: 17 new combined-sample checks, 27 existing index
comparison checks and 74 feature-content checks. The exact synthetic sample
compares 100 locations, 600 views, 9,600 detector values and 1,600 semantic
records. All images, reference outputs and runtime/model identities are test
fixtures; no actual Mac execution, model inference, provider/cloud access,
deployment, Actions or indexing restart occurred. The first 180-second test
harness stopped before completion; its log and timeout receipt remain private.
The completed suite took 309.761 seconds under a finite 600-second test harness.
This harness limit is separate from each comparator request's 60-second budget.
