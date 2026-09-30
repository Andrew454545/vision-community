# Object search snapshots for operators

`community.object_snapshot` prepares an offline, immutable bundle for a future
hosted object search engine. It does not enable public search, approve a device,
run inference, grant credit, download private indexes or change Cloudflare.
Volunteers do not need to run this command.

## Admission

The operator must supply two independently trusted, checksum-pinned inputs:

- A Community inventory exported using `INVENTORY_SQL` from
  `community/object_snapshot.py`. Each row must be published, credited to a
  contributor and joined to an `object_coverage` receipt from the pinned
  `official-gen4-historical-v1` validator. A client-supplied `gen4` label does
  not satisfy this requirement. The inventory envelope has `version: 1`, the
  confirmed Community resource identity and a `rows` array, like scene snapshots.
- An approval policy issued after trusted inference auditing of every complete
  object batch. Its digest is established through operator configuration,
  separately from the contribution. Do not construct approvals by copying
  volunteer checksums or by automatically approving old D1 publications.

An object's existing publication digest covers its global-location-ID record.
It does **not** cover RF-DETR, YOLOE or OWLv2 feature results. This tool therefore
requires approval of the entire feature bundle as well as its members and
coverage evidence. Altering features and recomputing their self-declared checksums
does not grant approval. Every location in a copied batch must pass admission;
partial batches cannot expose an unapproved neighbor's feature data.

The operator policy has these required fields:

```json
{
  "version": 1,
  "policyId": "OPERATOR_ASSIGNED_POLICY",
  "inputModel": "EXACT_D1_QUEUE_MODEL",
  "outputModel": "vision-object-index-v4",
  "verification": "independently-audited-object-inference",
  "runtimeIdentity": "PINNED_HYBRID_RUNTIME_IDENTITY",
  "coverageValidator": "official-gen4-historical-v1",
  "artifacts": [
    {
      "keySha256": "SHA256_OF_THE_R2_PREFIX",
      "bundleSha256": "INDEPENDENTLY_APPROVED_COMPLETE_BUNDLE_SHA256",
      "members": ["EXACT_MEMBER_OBJECTS_IN_LOCATION_ID_ORDER"]
    }
  ]
}
```

This is a schema illustration, not a valid approval policy. Runtime/model pins
are the constants in `community.object_index`; arbitrary runtime identities are
rejected. Each policy member must exactly match the object returned by
`row_member`: location ID, publication digest, trusted coverage-evidence digest
and public pose/capture metadata. No account identifier belongs in that policy.

`bundleSha256` is SHA-256 of `encoded(identity)`, where `identity` contains the
allowlisted `public_manifest`, the original TSV's byte count and SHA-256, and a
sorted map of every feature filename to its byte count and SHA-256. `load_bundle`
returns this digest after structural verification. Calculating the digest
identifies the batch; only a separate trusted inference audit approves it.

## Local cache and sealing

Each admitted R2 prefix is exactly `object-index-v4/<32 lowercase hex digits>/`.
The offline cache directory for it is SHA-256 of that entire prefix. Place
`manifest.json`, `locations.tsv` and every named binary feature file inside it.
`cache_directory` computes the path and refuses ambiguous prefixes or directory
escapes. Do not copy files from an unrelated bucket or follow source paths
embedded in a submitted manifest.

```text
python -m community.object_snapshot --inventory inventory.json --inventory-sha256 TRUSTED_INVENTORY_SHA256 --policy object-approvals.json --policy-sha256 TRUSTED_POLICY_SHA256 --artifact-cache object-cache --out new-object-snapshot
```

The destination must be new. Completed snapshots are never overwritten. Files
are flushed before the checksummed `snapshot.json` marker is published last.
On failure, the new directory retains a redacted `failure-report.json` and any
partial outputs, without a sealed marker. Existing snapshots remain intact.

To update, add `--previous PREVIOUS_DIRECTORY --previous-sha256 TRUSTED_PREVIOUS_SHA256`.
Old source ordinals, bundle ordinals, local offsets, public member metadata and
approved feature contents must remain unchanged. New batches append. Removing
or replacing old batches requires a separate reviewed replacement procedure;
this command refuses it even if the replacement has a new audit approval.

## Engine and privacy contract

Before opening a snapshot, an engine must call `verify_object_snapshot` with
its operator-configured snapshot digest. Verification checks file hashes,
native hybrid format, all member IDs/offsets, Gen4 evidence identifiers and
bounded paths. `members.json` maps stable `sourceIndex` values to a bundle and
local location offset. Per-batch native global IDs remain unchanged; do not
mistake those local IDs for global snapshot ordinals.

The exported manifest is allowlisted and its source path is `locations.tsv`.
The TSV is rebuilt from admitted public location metadata: account identifiers,
source-map labels, arbitrary manifest extensions and local paths are omitted.
Original opaque batch identifiers and coverage-evidence digests remain for
integrity. Road labels are replaced with `no road name`; the snapshot declares
road-name authority unavailable. A search engine must not infer verified road
absence from that replacement or claim road-name filtering support.

When a batch includes Andrew's per-view quality metadata, the snapshot preserves
its known policy, counters and evidence hashes while removing absolute Mac
paths. It checks the declared view accounting and feature-file integrity, but
does not copy or verify external tunnel/protected-authority documents. The
independent audit must establish those evidence identities and the quality
implementation. This export does not replace the reference application's
protected-index discovery or certify its view-quality behavior.

Current limits are 100,000 locations per snapshot, 1,000 per complete batch,
32,000,000 bytes per batch and 2 GiB of feature/TSV/manifest outputs per snapshot.
The member list and top-level manifest are each separately limited to 64 MiB;
the sealer enforces the same metadata limits as its verifier.
These are operator tool limits, not a promise of corpus-scale hosting capacity.
The live audit service, trusted Gen4 importer, portable object binaries, hosted
engine, reference-ranking comparison and storage/cost measurements remain
release requirements. Synthetic unit fixtures exercise admission and corruption
handling; they do not certify actual model outputs.
