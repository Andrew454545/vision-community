# Fixed-input Object score comparison

**Source only, inactive.** The trusted
[score comparator](../community/object_qualification.py) now checks actual
submitted numerical values against Andrew's independently pinned reference
fixture. It runs no native inference, fetches no imagery, creates no listener
and cannot qualify an account, publish a location or award credit.

The operator pins the reference fixture, current source files, exact Windows/Mac
CPU profiles, model hashes, resource pair, policy validity and tolerances. The
sample must contain **100–112 locations**, with all six frozen faces and every
reference query in the same order. A three-location exploratory diagnostic cannot
be relabelled as this sample. This count is a conservative engineering choice,
not evidence that an authentic cohort has already run.

Windows and Mac binaries, libraries and source-package bytes may differ. Their
complete profiles are independently pinned by the operator; a Mac profile is
not required to have the Windows package's file hashes. The model hashes must
match the frozen reference, and the actual outputs are compared numerically.

The comparator recomputes common-detector, hot-concept and semantic score/box
differences from the submitted values. It refuses missing/extra/reordered cases,
queries, identities, support counts and detections. Nonfinite numbers, unknown
profiles, changed files, invalid resource pairs, expired policies and malformed
or oversized requests cannot create a compatibility result. It rechecks the
frozen inventory and source/policy after comparison under a finite 20-second
budget; the request is at most 8 MiB.

Operator-selected bounds may be stricter, but cannot exceed the existing Object
audit's conservative engineering ceilings: **0.001 for scores** and **2/65535 for
normalized boxes**. These are not new measured Mac/PC tolerances or permission
to change an approved runtime. No human confirmation that objects are visible is
required; this checks corresponding numerical outputs and identities.

The [local Object diagnostic](../community/object_canary.py) can now opt in to
saving `submission={profileId,canary}` with actual portable outputs through
`include_submission=True`. The ordinary diagnostic remains unchanged and saves
no submission packet. The optional packet contains no local image paths or
client-computed approval summary. It is bounded, stays private and is never
uploaded by this diagnostic. Failed/incomplete runs cannot emit it.

The result deliberately uses `scoreCompatible`, **`qualified:false`**, scope
`fixed-input-detector-score-parity-only`, and zero acceptance/credit. It has no
`approved` field. Detector scores alone do not demonstrate full Object index,
quantization/quality or current Scene/protected authority. A future coordinator
must not store this result as complete device qualification. Qualification-based
routine uploads remain the approved product direction; every uploaded location
does not need another native recomputation once the complete initial check passes.

Still required: complete indexed-feature/quantization and quality comparisons for
the same sample, trusted qualification storage/revocation, current Scene/protected
eligibility and distinctly marked qualified publication/once-only credit. The
existing [Object upload integrity component](QUALIFIED_OBJECT_UPLOADS.md) is ready
for that writer. Public Object qualification and assignment remain closed; no
deployment, provider test or background task was started.

The original failed fixture runs are preserved in
`work/object-score-qualification-20261013`. It exposed an existing contract that
ordinary diagnostics must not emit submission packets; the new packet is now
explicitly opt-in, preserving that contract and the original failure evidence.
The byte-budget fixture initially expected exhaustion one detector call too early;
its packet ceiling is now independent of the fixture JSON ceiling, with the
expected boundary derived from actual encoded sizes. The failed attempt remains.
The synthetic sample tests cannot establish actual Mac execution, authentic
inference or production qualification.

[Windows evidence](evidence/object-score-qualification-20261013.json): **136
regression checks passed without skips**. After the packet bound and independent
platform-profile refinements, **31 focused checks** passed; a final **17-check
canary run** confirmed ordinary diagnostics retain their prior streaming behavior.
There are 138 distinct checks across these overlapping stages. They include the
100-location/600-view synthetic comparison, opt-in packet, existing native Object
verifier, indexed feature validation and guided lane gates. No model, imagery, cloud or Actions execution
occurred. The complete real release gates remain open.
