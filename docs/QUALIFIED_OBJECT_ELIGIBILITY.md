# Qualified Object eligibility

**Source only, inactive and undeployed.**
[`inspectQualifiedObjectUpload`](../deploy/cloudflare/src/qualifiedObjectEligibility.js)
connects reusable account/profile qualification to the existing upload inspector,
current contributed Scene membership and a fresh private protection check. It is
read-only: no assignment, native audit, publication, credit, task, endpoint or
binding is enabled. Public Object capability remains closed.

## Current authority

The optional mode is `OBJECT_QUALIFIED_UPLOAD_MODE=qualified-device-v1`.
`OBJECT_ELIGIBILITY_POLICY` and its separately supplied SHA-256 pin are required.
The exact policy selects the contribution policy ID, numerical qualification
policy, protected verifier policy, quality implementation, protected authority,
original-source handoff, Scene input model, confirmed Community resource and
validity. It must match the active qualification policy and resource. No
checked-in configuration supplies these settings.

The checker reads the existing owned quarantined candidate and reuses all
[upload integrity checks](QUALIFIED_OBJECT_UPLOADS.md): exact source/pose/model,
bounded files, checksum and artifact ownership, finite feature values and fresh
trusted exact-panorama official Gen4 coverage. Fetch/inference/permanent-invalid
counters must be zero. A complete profile must have a current registry record
under the exact numerical policy and revocation generation.

For each Object row it requires a published contributed Scene in the configured
input model with matching panorama, capture, coordinate, country and Gen4 camera
identity. Its contributor must be active and its current output/four-view digests
must agree. Merely listing a panorama in an arbitrary file is insufficient.
This first adapter uses current D1 membership; sealed corpus membership at larger
scale remains separate work.

The private `OBJECT_ELIGIBILITY` binding receives only account/lease/profile/
qualification identity, a fresh challenge, pinned assignment/source/policy hashes
and the captured database snapshot digest. Its reply must bind those fields,
the exact protected policy/resource/quality and the assignment's location IDs
and coverage digests. A service cannot assert Scene membership, official coverage
or account qualification on behalf of the coordinator.

After the private call, the checker repeats upload integrity, account/profile
qualification, Scene membership and policy checks. Revocation, deletion, expiry,
changed coverage/pose/files or a replaced policy invalidates the read. One shared
20-second budget bounds asynchronous operations and response reads; late service
bodies are cancelled. Missing or malformed private evidence is an outage, not a
device rejection.

## Original-source protection

[`LiveObjectProtection`](../community/object_eligibility.py) consumes an existing
owned `ObjectAuditJobs` instance, a separately pinned context and a caller-supplied
activation guard. It does not start its auditor, create a job or open a port.
Only the independently pinned registry selects assignment/source paths.

It reuses `NativeObjectVerifier`'s original-source protected snapshot and live
fingerprint checks, including the separately pinned origin handoff. The original
files must still exist unchanged on the machine that produced the capture.
Fully verified source hashes must already exist; intermediate checks retain the
native file identities without repeatedly hashing gigabytes of Arrow data.
The assigned points must satisfy the existing 25-metre exclusion rule. Paused,
stopped or revoked assignments are refused, even without a saved native job.

The check repeats guards before returning a receipt valid for at most 30 seconds,
capped by the original capture's one-hour expiry and context validity. A new
challenge cannot renew an expired capture. No database bytes are copied and no
portable import authority, inference, Scene/coverage approval, account admission
or credit is asserted by this producer.

The result remains private in-memory evidence with
`verificationScope: qualified-object-upload-eligibility-only`, no server
authorization and zero accepted work/credit. It is **not** a portable permission
to publish later. The future writer must revalidate qualification generations,
lease/coverage/Scene state, receipt expiry and artifact ownership inside the same
transaction that records distinct acceptance and once-only credit. The existing
fully audited writer and its immutable native approval requirements are unchanged.

## Evidence and next work

[Windows local evidence](evidence/qualified-object-eligibility-20261013.json):
28 Node checks, eight targeted Python checks and one actual Python-to-JavaScript
protection contract check pass. SQLite and file guards execute locally; all
accounts, qualifications, runtime/model declarations, source databases/Arrow files,
coverage and outputs are synthetic. Original failed/discovery attempts are retained.
No actual Mac/model execution, cloud read, deployment, Actions or indexing restart
occurred.

Next implement distinct qualified Object staging/assignment, atomic publication
and once-only credit with current authority and financial/deletion recovery.
Do not manufacture an approved audit job or relabel routine uploads independently
recomputed. Actual approved private binding/setup, authentic platform qualification,
budget activation and the remaining [launch gates](PRODUCTION_ACCEPTANCE.md) remain open.
