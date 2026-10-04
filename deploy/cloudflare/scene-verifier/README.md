# Private scene verifier

This Worker is a private staging component. Both development and preview URLs
are disabled;
the Community Worker reaches it through a Cloudflare service binding named
`SCENE_VERIFIER`.

Before deployment, a reviewer must place two files in a **separate private R2
bucket**: `scene-policy.json` and the exact 112-record `canary-reference.i8`.
Set `SCENE_POLICY_SHA256` to the policy file's SHA-256. The policy must name the
approved runtime profile, fixture and reference hashes, explicit numerical
bounds, and evidence of three 1,024-location calibration repetitions.
The policy must set `scope: "staging-reference-only"`, and configuration must
set `VERIFIER_MODE` to the same value. Any other mode fails closed. This
implementation must not be used to enable general production indexing.

The verifier independently recomputes the PC canary's numerical comparison. It
does not trust client-reported metrics. It rejects all new scene submissions by
default; its optional submission-hash allow-list exists only to exercise one
approved and one rejected audit in staging. Connecting a real trusted inference
auditor is still required before public scene contribution can be enabled.

An allowed audit digest covers the exact ordered location metadata, a newline,
and the complete binary index. The verifier recomputes that digest and every
record digest before granting the staging approval. Copying a previously
allowed hash onto different data does not grant approval. Qualification binds
to an approved runtime profile but does not attest the contributor's hardware
or prove that it ran inference; independently checking new submissions remains
necessary.

Request and policy reads are bounded. Corrupt pins, unavailable storage and
invalid policies produce an unavailable response and grant no qualification.
Missing, truncated, checksum-invalid or zero-norm operator references return
503 so a client can retry without recording a failed PC qualification.
The test suite checks vector direction and scale, zero vectors, metadata and
payload tampering, storage failure, and oversized streamed requests.

`tools/check-local-verifier.mjs` also exercises the Worker with Cloudflare's
local R2 runtime. It uses only synthetic, disposable fixtures: exact comparison,
changed vectors, bound audit metadata, corrupt policy and corrupt reference.
Passing this check is storage/runtime evidence, not a Windows model approval.
