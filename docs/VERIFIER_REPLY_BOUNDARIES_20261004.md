# Private verifier reply boundaries

A malformed private verifier approval previously looked like a failed PC check.
The gateway now reports a retryable service error (`503`) when the reply is
missing, malformed, oversized or does not match the requested policy, runtime
profile, canary digest and expiry. Only an explicit negative decision is a PC
rejection (`422`). No broken reply is saved as a qualification.

Decision replies are limited to 65,536 actual bytes, independently of the
declared length. The reader requires JSON content, valid UTF-8 and an object,
limits reads including empty chunks and gives body reads a ten-second deadline.
Cancellation is requested without awaiting an unbounded cancellation callback.
The existing fetch deadline remains separate from the body-read deadline.
This endpoint transports decisions, never imagery or tensors.

Malformed or oversized audit approvals leave the contribution quarantined,
unpublished and uncredited. A subsequent valid audit can still publish and
award credit exactly once. Approval correlation and accounting checks remain.

## Evidence

All 206 JavaScript checks pass locally with the private Node 24.19.0 runtime.
Eleven new checks exercise split UTF-8, exact and excessive size, missing or
invalid length, invalid JSON/content/type, empty chunks, a stalled source with
non-resolving cancellation, malformed qualification correlation and audit retry.

Thirteen actual local workerd gateway cases use isolated D1/R2 and a synthetic
private verifier: exact size, malformed JSON, array, wrong content type,
wrong profile, missing decision, expired approval, oversized JSON, oversized
stream, two explicit rejections, a stalled response and valid retry.
Only the two valid replies create synthetic qualifications. Every case retains
zero balance, ledger entries and published records. These cases run in CI.

The local gateway accounting/privacy, staging-policy isolation, deletion
archive, maintenance, restore-SQL and independent verifier regressions also
pass using Miniflare 5.20260926.1-alpha. The Worker dry-run build succeeds.
An initial check selected an older installed Miniflare whose workerd could not
support the compatibility date; its failed log is preserved. The passing check
uses the already-installed matching runtime, without reducing that date.

These are local service-boundary checks. They perform no model inference,
real PC qualification, production deployment, cloud storage access or credit
change. Live imagery identity, runtime qualification, full comparison and
extended unattended processing remain open in
[the acceptance checklist](PRODUCTION_ACCEPTANCE.md).
