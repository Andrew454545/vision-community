# Object submission cancellation — 11 October 2026

An owned, unpublished Object submission can now be cancelled without deleting
the contributor's account or spending banked credit. This is private integration
code; the public Object route remains closed.

Cancellation first commits an immutable receipt of the original job, audit
receipt, failure and retry state. The same transaction revokes the candidate,
expires its lease and releases its quarantined locations. Replaying the saved
request cannot create another cancellation or erase the original evidence.
A changed owner or any published lease member refuses cancellation.

A durable cleanup outbox independently revokes the native assignment and fences
the private R2 upload. It addresses the assignment by lease, so a lost start
reply or unknown native job ID cannot strand the upload. A native job already
running loses approval immediately; cleanup waits for its bounded work and file
erasure. The account remains active. Subsequent account deletion can share the
cleanup safely using its separate deletion receipt.

Cleanup confirms the exact policy and assignment hash in the native erasure
reply, and both the R2 write and bounded byte-for-byte fence readback. Partial
success survives restart. Neither native erasure pending nor an R2 outage
prevents the other independent step. A thirty-second claim prevents concurrent
drivers; each cleanup call has a shared maximum twenty-second deadline and
durable 30–900 second retry backoff. Eight transport failures request attention.
Damaged ownership becomes `needs_review` without provider actions. Late audit
replies cannot revive the candidate; create-only delayed uploads cannot replace
the permanent privacy fence. No path here publishes work or awards credit.

## Verification

[Pinned evidence](evidence/object-audit-cancellation-20261011.json) records:

- **248/251 affected Windows JavaScript checks passed**, zero failures and three
  existing file-symlink permission skips. Eighteen cancellation cases, strict
  expected-erasure checks and the storage-recovery refusal case are included.
- **Ten actual local workerd/D1/R2 scenarios across four fresh processes**
  preserve revocation, partial cleanup and original failures; completion and
  replay retain the active account and unchanged credit.
- **One actual Node/bridge-to-Python HTTP/SQLite test passed** with a native
  attempt running before its start reply was deliberately lost. Hosted state
  never receives the job ID. Assignment erasure still completes, the saved job
  becomes erased, its private input/attempt directories disappear, and replay
  starts no additional job. The fixture has one synthetic native attempt, one
  assignment revocation and one completed erasure. Its clock advances only to
  exercise retries quickly; production backoff is unchanged.

Inference is explicitly synthetic. Ten initial units are fixture data, not
earned credit. The real local Cloudflare runtime, Python validation, HTTP,
transactions, native saved-job state and file cleanup execute; this does not
establish authentic model quality, Mac acceptance or production qualification.
Every finite run passed. Private logs/receipts and all older failures remain
preserved. The original terminal offline diagnostic checksum is unchanged.

## Remaining integration

Optional setup is explicit through `prepareObjectAuditCancellation`; it checks
the complete schema and dispatch contract. Requests never install tables. A
private operator must drive pending cleanup; a public owner route, scheduled
cleanup driver and beginner-facing cancellation control are not yet connected.
The retained candidate/event capacity remains bounded, so indefinite retention
and compaction still require an explicit policy.

The existing native and R2 recovery tools attest account deletion only. They now
refuse any current submission-cancellation records, including a remembered
`erased` row, instead of issuing an incomplete recovery certificate. Full
recovery still needs independently current cancellation authority, application
to an older D1/native backup, provider fence readback and reconciliation. This
refusal is a safety guard, not completed post-backup recovery; an old copy cannot
be represented as a current authority source.

Authentic protection/runtime authority, trusted qualification, public admission,
atomic publication/once-only credit, real Object search, provider/secret recovery,
Mac/signed clean-device checks and the full accepted-work soaks remain launch
gates. Andrew's fresh source export request in private VISION PR #17 is unchanged.
No live deployment/schema, real upload, Actions run, global installation or
frozen Windows Scene pilot/refresher change occurred.
