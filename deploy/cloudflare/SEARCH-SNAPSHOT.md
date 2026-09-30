# Sealing a contributed scene snapshot

This is a private operator tool, not a volunteer setup step. It performs no
network access, imagery retrieval, database writes, account creation or uploads.
It cannot approve a Windows runtime, infer a quality tolerance, or run the hosted
search engine. Object snapshots are not supported yet and fail closed.

## Inputs and trust

Use only the confirmed Community account/database/bucket named by
`community.search_snapshot.CONFIRMED_RESOURCE`. The excluded image bucket is
never an input. The builder refuses different resource identifiers.

1. Export the eligible rows with `community.search_snapshot.INVENTORY_SQL` from
   the authoritative Community D1 database through an operator-controlled
   read-only export. Wrap the results as
   `{ "version": 1, "resource": { "accountId": "...", "databaseId": "...", "bucket": "vision-community" }, "rows": [...] }`.
   Keep this file private: it contains anonymous contributor identifiers.
   Verify the inventory against D1 and pin its SHA-256 separately.
2. Independently audit every selected output against the reference quality
   policy. Prepare an `ApprovedSceneReferences` policy as described in
   [REFERENCE-VERIFICATION.md](../../docs/REFERENCE-VERIFICATION.md), and pin
   its SHA-256 through trusted operator configuration. Never generate approvals
   from the inventory or from contributor-supplied checksums. The historical
   live-image calibration packet is not such an approval policy.
3. Retrieve **only the inventory's exact eligible artifact keys** from the
   confirmed `vision-community` bucket into a private cache. Name each local
   file `SHA256(UTF8(R2_KEY)).i8`; `cache_file(cache, key)` returns that path.
   Contributor labels are never used as filesystem paths. The downloader and
   live export adapter are still pending; this tool accepts prepared local files.

The builder checks publication/contributor state, both publication digests,
exact independently approved panorama/capture/pose/input-model identity, and
each selected record's bytes. It finds records by their digest within the
artifact; it never assumes that D1 row order equals the order in an upload.
Zero-norm views, missing records, malformed files and duplicate IDs are rejected.

## Build and verify

Run with the application's private Python from the repository root:

```text
python -B -m community.search_snapshot --inventory PRIVATE_INVENTORY.json --inventory-sha256 INVENTORY_SHA256 --policy PRIVATE_APPROVALS.json --policy-sha256 POLICY_SHA256 --artifact-cache PRIVATE_CACHE --out NEW_PRIVATE_SNAPSHOT_FOLDER
```

This creates `scene-records.i8`, `members.json`, and finally `snapshot.json`.
The command returns the manifest's SHA-256. Payloads are durable before the
manifest is published. A new directory is required; existing results are never
overwritten. A failure retains partial files and a redacted `failure-report.json`
without a sealed manifest. Failure before a new directory can be created is
reported in the command result instead.

Verify with `verify_snapshot(folder, expected_sha256)` before opening it in an
engine. The manifest transitively pins the membership and record bytes. The
membership contains ordered Community IDs/digests and output poses, but no
contributor IDs, bearer tokens, recovery codes or operator filesystem paths.
Keep snapshots private: distributing the full index would bypass online credits.

For an update, add `--previous PREVIOUS_FOLDER --previous-sha256 PREVIOUS_SHA256`.
Existing members retain their ordinals; new members are appended. All members
must still be approved under the current independent policy. Removed or changed
historical members fail closed rather than silently reusing or changing an
ordinal. Revocation/deletion needs an explicitly versioned replacement policy
and cutoff handling; do not force an incompatible bundle into the same registry.

The flat records/membership bundle is an **input contract for the pending engine
adapter**, not a native VISION index directory. Road-name authority is marked
unavailable because the present D1 inventory cannot attest it. An engine must
reject unsupported road-filter requests until trusted road evidence is added.
No deployment, live export, inference parity, throughput or cost claim follows
from a successful build. Tests use synthetic, disposable policies only.
