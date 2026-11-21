# Reusable Object qualification

**Source only, disabled and undeployed.** The optional
[registry](../deploy/cloudflare/src/objectQualification.js) connects authenticated
account requests to a private saved-sample comparator, expiring qualification,
status and revocation. It does not open Object assignments, publication or search,
create contribution credit, fetch images or run models. The fully audited Object
path remains separate.

The account submits only `requestId`, `profileId` and `artifactSetSha256`, within
4 KiB. A client cannot submit an approval, choose a filesystem path or send raw
sample data through this route. Account authentication, same-origin and rate
limits apply. Checked-in configurations do not enable it. Actual setup still
needs an approved private artifact transfer and trusted host binding. The
[private owned-sample host](OBJECT_QUALIFICATION_HOST.md) now implements bounded
local delivery and pinned account/job lookup in source; actual setup stays inactive.

## Trusted saved sample

The private binding `OBJECT_QUALIFIER` must provide the bounded
`trusted-saved-object-sample-evidence-v1` contract. The new read-only
[Python adapter](../community/object_qualification_evidence.py) implements that
evidence producer from an operator-pinned artifact manifest. The caller must
locate the manifest through trusted account/job state; the request never selects
its path. No incoming listener, startup task or upload is installed here.

The manifest binds the account/request/profile to actual saved detector output,
candidate index and a separately pinned execution-identity receipt. Both saved
runs must declare the same complete approved runtime profile and shared execution
settings. The settings digest is the existing canonical fingerprint of
`{execution:"cpu",threads:1}`; the complete profile separately pins binary,
libraries, models and pipeline files. This does not approve a different CoreML,
parallel, runtime or model profile.

The adapter recomputes the [combined numerical comparison](OBJECT_INDEX_QUALIFICATION.md),
rehashes the saved artifacts afterward and returns a fresh 30-second challenge
envelope. It never consumes a saved pass flag or manufactures an execution
receipt. The trusted host must retain original runs, artifacts and failures.
Pinned run metadata describes the saved execution identity; this is not remote
attestation or a new independent native recomputation.

The registry requires the complete score-and-index scope, exact policy/reference/
input/profile hashes, same-profile/settings bindings, all sample locations/views,
and current request/account/challenge correlation. Detector-only evidence cannot
qualify an account. Invalid or malformed negative replies are service failures,
not device rejections. A valid incompatible numerical sample revokes the current
profile generation. Compatible replies must also have consistent finite scores,
discrete/quality/PQ metrics and native counters.

The comparator's report still says `qualified:false`, zero accepted work/credit,
and no current coverage/protected or inference-provenance authority. The registry
creates a **separate** qualification record with explicit
`trusted-reference-sample-comparison` provenance. Routine uploads are not called
independently recomputed. Qualification only authorizes a compatible processing
profile once the separate contribution/eligibility path is implemented.

## Durable authority and revocation

An explicit operator migration installs the optional schema and exact fences.
Public requests never create or repair it. Missing revision state with retained
authority, or weakened tables/indexes/triggers, fails migration rather than
silently reseeding. The existing required schema and release protections remain.

Each authority context hashes the complete coordinator policy: numerical policy,
reference/input hashes, environment/resource pair, allowed profiles/settings and
validity. Changing settings or other pinned context cannot reuse an older record.
Only confirmed Community staging/production resource pairs are accepted.

Requests keep an immutable identity and challenge, a 10-minute deadline and a
90-second exclusive claim. At most four unexpired pending requests per account
are allowed. A bounded service wait cannot start native work; failed delivery
keeps the same request retryable. Expired requests are not silently submitted as
new work. Saved successes replay without another comparison or TTL extension,
including when the verifier is unavailable.

Revocation advances a retained account/profile/context generation. A late older
reply cannot restore it. Replaying an older revocation or incompatible result
cannot revoke a newer successful generation. Account deletion cancels pending
requests, advances the generation and blocks access; original qualification
history remains immutable. Final decisions and revocation fences are atomic.
The registry stores hashes and scalar summaries, not arbitrary raw report paths
or metadata. Original full evidence remains in the approved private producer.

## Evidence and remaining integration

[Windows evidence](evidence/object-account-qualification-20261013.json): 69 local
Node checks and four Python adapter checks pass without skips. Actual local
workerd passes 13 checks across three fresh processes using real D1 storage and
Worker authentication. A further Python-to-JavaScript check consumes a full
100-location synthetic comparison through the saved adapter and registry.
All samples, profiles, runtime/model identities, accounts and numerical outputs
are synthetic. No real Mac/model execution, cloud account access, provider test,
deployment, Actions or indexing restart occurred. Original failed attempts remain
private; their runtime/fixture corrections are recorded with the evidence.

The [private host/delivery component](OBJECT_QUALIFICATION_HOST.md) now connects
trusted job lookup and a separately approved local file copy in source. Actual
private transport, host activation and real exact platform evidence remain open.
Next connect fresh current
official Gen4, Scene membership and protected-source authority, qualified Object
assignment/publication and once-only credit. Bound retained metadata and include
these authorities in offline migration/recovery. Qualification/other paid work's
allocation, activation, signing, capacity and accepted-work endurance remain
launch work. No operational hold or destination-specific approval is lifted.
