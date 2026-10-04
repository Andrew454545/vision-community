# Scene contribution verification

For new-location native auditing, use the [private native host](../deploy/cloudflare/native-container-host/README.md).
It independently recomputes submissions under a pinned runtime and measured
operator policy. The finite [staging experiment](STAGING_SCENE_ADMISSION_20261003.md)
passed; production admission remains closed. Engineering policy decisions are
delegated and do not require a separate Andrew sign-off.

The instructions below describe the older, **preapproved-locations-only** gate.
It remains useful for a small reviewed pool; it does not replace native auditing.

Public scene contributions are blocked until an operator installs a trusted
reference policy. The previous path checked layout and a contributor-supplied
checksum and then published and credited that output. Those checks detect
corruption, but do not establish that the contributor ran VISION or matched
Andrew's results. This change closes that path, including submissions from an
already active lease and attempts to switch to the prototype model.

## What this release enables

This is a limited, independently approved reference pool, **not general public
indexing or automatic approval of the Windows calibration profile**. A policy
allows one or more already reviewed output digests for each exact panorama,
capture, pose, input model and output model. More than one digest can be approved
when independently checked outputs have acceptable differences. The policy does
not require that every output equal Andrew's bytes, and does not invent a
similarity threshold.

The present gate cannot approve unseen locations or unseen output variants.
Do not copy hashes from an untrusted submission into the policy to make it pass.
Andrew or a trusted reviewer must establish quality independently. Live imagery
changes and absent original run provenance prevent treating the historical
calibration reference as an automatic production acceptance policy.

## Operator workflow

1. Freeze the input imagery and pose, model files, preprocessing, precision and
   runtime identity for reference validation. Compare per-view vectors and
   representative retrieval rankings to Andrew's gold standard. Establish and
   record an acceptance policy from the reference evidence; a good average can hide failed views.
2. Independently review each allowed output under that policy. Record the
   policy identifier and SHA-256 of each accepted 3,080-byte location record.
3. Store the manifest below privately, outside contributor-writable storage.
   Pin its entire file SHA-256 in server configuration. Keep the review evidence
   and policy history separately with restricted operator access.
4. Prepare a queue containing only covered locations with matching poses and
   input model. An uncovered candidate is rejected before work is issued.
   Cloudflare rejects a catalog-backed scene pool with
   `scene_reference_pool_unprepared`; it does not consume catalog cursors to
   discover unknown references. Python catalog materialization rolls back if
   any candidate lacks approval.
5. Check `GET /api/capabilities`, then test a known approved submission and an
   altered one in staging. The approved record earns credit once; the altered
   record earns none and is not published. This change does not deploy a server
   or migrate previously published indexes. Audit that existing data separately.

Example schema (placeholder digest, not an approved fixture):

```json
{
  "version": 1,
  "policyId": "andrew-reviewed-policy-id",
  "inputModel": "community-visual-v1",
  "outputModel": "vision-four-view-v4",
  "references": [{
    "assetId": "operator-reviewed-panorama-id",
    "capture": "2026-01",
    "lat": 10,
    "lng": 20,
    "heading": 90,
    "pitch": 0,
    "zoom": 0,
    "approvedSha256": ["replace-with-64-lowercase-hex-characters"]
  }]
}
```

Python operators load `ApprovedSceneReferences.load(path, expected_sha256)` and
pass it as `scene_references` to `CommunityService(..., operational=True)`.
The loopback demonstration retains its synthetic extractor for existing tests;
its capability endpoint still reports scene contributions unavailable without a
reference policy, and it cannot accept VISION four-view submissions without one.

Cloudflare operators bind a private R2 bucket as `SCENE_REFERENCES` and set
`SCENE_REFERENCE_KEY` and `SCENE_REFERENCE_SHA256` in deployment configuration.
The bucket must not be the contributor-writable `INDEX` bucket. No binding or
production approval is supplied by this repository. Missing, corrupt,
oversized or unavailable policy objects fail closed. The reference file limit
is 4 MB; this mechanism is intended for a small reviewed pool.

The public capability response includes `version: 1` and
`sceneContributions: {ready, reason, model, policyId, verification, scope}`.
`scope` is `preapproved-locations-only`; `ready` means the reference gate is
configured, not that every queued location is approved or that the deployment
has passed all production requirements. A client must check before starting
work and handle lease rejection without starting image processing.

## Remaining release gates

General new-location indexing needs a trusted audit/verification service and
a measured tolerance policy tied to frozen reference provenance. It
also needs abuse/rate limits and atomic concurrency checks, failure recovery,
backup/restore exercises and operational monitoring. The object lane still
validates the index contract, not independent object-model correctness; this
scene gate does not qualify it for public production. No production deployment
or automatic numerical acceptance is authorized by calibration diagnostics.
