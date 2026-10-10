# Audited Community Scene source

The private source exporter now connects genuine accepted Community Scene work
to its original location rows without claiming membership in the owner's MMA
index. The real saved eight-location trial passes: all eight credited, native-
audited completions match the authentic supplied 100-row source and their original
row bytes are preserved. No imagery retrieval, upload, native inference, balance
change or live service change was needed for this export.

## Evidence chain

The exporter first uses the existing publication sealer to check independently
pinned inventory, native audit/control, accepted runtime/profile authority,
qualification, exact published vector bytes and once-only earned credit. It then
matches original source rows by exact pano, country, camera generation and every
binary64 pose value. It rejects missing completions, ambiguous matches, repeated
source IDs, altered bytes and changes during sealing. Unprocessed source rows
are excluded. Original source IDs, local IDs, numeric spellings, road labels,
line endings and row order are preserved; the catalog separately maps them to
Community location IDs and output hashes. Original row ordinals are zero-based.

The authentic source uses `has-road` / `no-road`, whereas the owner's native
Scene pool builder expects `has road name` / `no road name`. The exporter records
that dialect explicitly and refuses mixed dialects. It does **not** silently
normalize the evidence or claim that the existing native builder accepts it.
The first real attempt's dialect rejection and complete failure report remain
preserved separately from the successful corrected export.

The resulting private catalog has the distinct scope
`vision-community-audited-scene-source-v1`. Its receipt and all input/output pins
are recorded in [the evidence](evidence/community-scene-source-20261010.json).
The catalog has no account credentials or account-owner fields; original location
rows and the private control-plane input files remain private.

## Operator use

Use the existing private runtime and independently trusted export hashes:

```text
python -B -m community.community_scene_source --inventory <private-inventory.json> --inventory-sha256 <pin> --control <private-control.json> --control-sha256 <pin> --authority <private-authority.json> --authority-sha256 <pin> --cache <private-published-cache> --source <original-source.tsv> --source-sha256 <pin> --environment <staging-or-production> --output <new-private-folder>
```

The finite cohort limit is 4,096 source rows and 1 MiB of original TSV. Existing
outputs cannot be overwritten. An unsuccessful export keeps a redacted failure
report; a partial proof directory is not a completed catalog. Require successful
exit, the final receipt and matching pins. This is not a contributor setup step.

## Import boundary

The producer is complete and exercised on real accepted Scene data. The consumer
is still required: an explicit native Community catalog adapter must verify the
independently trusted catalog and publication proof, preserve exact source/pose
mapping and define any road-label conversion as a separate, pinned transformation.
It must not turn this catalog into an owner MMA catalog.

Current official Gen4 validation, protected-location authority, runtime/model
qualification, native per-view Object quality and current hosted membership
remain independent checks. The catalog explicitly sets those Object approvals
to false. It cannot be used directly as an inline Object import seal, runtime
policy or contribution/credit decision. Do not bypass the current native guards
to consume it. The original invalid historical candidate remains rejected.

Local Windows publication/export and policy-source checks are recorded separately
from authentic saved-data export. Fixtures use synthetic inference. Actual Mac
execution, native Object admission/search and the other launch gates remain open.
Adding a source module changes development policy source fingerprints; any future
deployment must reseal and qualify its actual source/runtime bytes. The running
Scene pilot and refresher use separate frozen copies and were not changed.
