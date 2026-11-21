# Object publication metadata — 12 October 2026

The unfinished Object publisher copied arbitrary manifest extensions into its
stored final manifest. Hosted Object admission was already closed; this was a
source gap in the local prototype and eventual publication path, not evidence
of an exposed live index.

`publicObjectManifest` now retains only the native snapshot's public fields,
uses `locations.tsv` for the source filename, and removes unknown metadata from
the manifest, contract versions and every feature/quality entry. Nested retained
values and invalid counters fail safely. When per-view quality is present, its
current policy, counts, blur/tunnel settings and protected-authority checksum
shape must be consistent. Darkness alone never establishes tunnel rejection.
Sealed tunnel evidence retains its independent evidence identities.

The prototype publisher validates and projects before creating an artifact
intent, R2 object, publication or credit. The private settlement integrity check
also produces this separate `publicManifest` after full feature validation and
before requesting a fresh native receipt. The original quarantined candidate
remains unchanged and private. Neither a projected manifest nor a checksum
string proves authentic protected/runtime/quality authority or qualifies a
computer. An actual qualified, guarded publication transaction is still needed.

Source TSV and feature bytes are unchanged, preserving their hashes, row offsets,
native record identities and exact audit correlation. This change sanitizes
manifest metadata; it does not normalize source labels or replace the existing
searchable-snapshot privacy normalization. Only the projected manifest should
be used as publication metadata, never the full private check result.

## Verification

[Pinned evidence](evidence/object-public-manifest-20261012.json):

- Windows Node: **203/203** related tests pass, zero skips/failures. Seven new
  grouped checks cover projection, malformed metadata, diagnostic markers,
  quality policy, sealed tunnel evidence and publication refusal before writes.
- Python: **114 distinct checks pass** across the original regression and the
  repaired new parity check. The latter compares **32 shared cases** with
  `community.object_snapshot.public_manifest`, including exact projections,
  quality refusals and Unicode. The original 113 passing checks were not rerun
  merely to replace their receipt after a fixture-only repair.
- Actual local Cloudflare workerd/D1/R2: **24 cases across five fresh processes**
  pass. Thirteen exercise private candidate integrity/revocation. Eleven use
  the full bundled Worker, read every actual stored feature/source file, verify
  the sanitized manifest's write-intent digest and recover/replay in a new
  process. The isolated prototype awards 20 synthetic units once; replay adds
  nothing. Hosted Object admission remains closed. **No real contribution or
  earned credit is created.**

Original failed fixture attempts remain preserved: the first Python parity
test used the ownership helper's reserved stdin argument; two initial local
runtime configurations failed to start; a later fixture read readiness from
the status endpoint instead of the capabilities endpoint. The repaired file
argument, explicit module/root configuration and correct endpoint pass. These
failures were not rewritten or counted as successful runs.

No live deployment, model inference, imagery retrieval, private upload, Actions
job or hosting spend was started. The frozen Scene pilot/refresher and earlier
failure reports were neither polled nor changed. Authentic Object admission,
atomic publication/credit, Mac execution and the other launch gates remain open.
