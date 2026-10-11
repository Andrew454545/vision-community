# Object retry recovery — 11 October 2026

Private Object handoff now has explicit recovery for exhausted connection
retries and failed native attempts. An interrupted request cannot silently
start another inference attempt. Original failure metadata and attempt files
remain preserved; account deletion and assignment revocation override replies.

`recoverObjectAudit` accepts an owned candidate and a saved opaque request ID:

- `resume-transport` resumes a candidate paused after eight connection failures.
  The old failure count, error, retry time and native receipt are journalled
  before the reset. Replaying that request ID cannot reset a later failure.
  Four explicit resume episodes per candidate bound this private component.
- `retry-native` journals the failed job ID and expected attempt before sending
  the private retry request. The Python service commits the request ID and
  queued state together. If the reply is lost, repeating the same request ID
  observes the current job; it cannot restart a later failed attempt. A new
  explicit intent is required for another retry. The existing three-attempt
  native limit, backoff, source validation and capacity checks remain enforced.

The Worker and native host both retain recovery across restart. A per-candidate
claim coordinates retries with ordinary status reads. A newer independently
observed attempt settles an uncertain retry without another POST. Wrong identity,
changed manifest, stale attempt, timeout and late replies cannot replace saved
state or create publication/credit. Recovery calls use at most twenty seconds;
uncertain replies leave a durable intent with bounded backoff. After eight such
failures the reply asks for operator attention; another call remains an explicit
operator action, not an automatic inference loop.

## Verification

[Pinned evidence](evidence/object-audit-recovery-20261011.json) records:

- **210/213 affected Windows JavaScript checks passed**, zero failures and three
  existing file-symlink permission skips. Fourteen new recovery cases and two
  retry-bridge cases are included.
- **Twelve actual local workerd/D1/R2 scenarios across four fresh processes**
  preserve failure history, replay a lost retry acknowledgement, avoid duplicate
  retries, and enforce current deletion and permanent storage fences.
- **42 Python regression checks passed**, including both actual Node/bridge-to-
  Python HTTP/SQLite protocol checks. A separate final five-case retry selection
  also passed, including the added concurrent-retry case. These groups overlap.
- The new protocol test deliberately fails the first synthetic native attempt.
  Two retry POSTs produce exactly one new attempt: the spool records failed
  attempt 1, approved attempt 2 and one retry intent. Later replay creates no
  attempt; account deletion erases the private payload. The fixture advances
  its clock for the existing retry delay; production timing is unchanged.

Inference is explicitly synthetic. Actual Python validation/comparison, SQLite,
HTTP framing, bridge checks and local Cloudflare transactions run. This evidence
does not establish authentic model quality or production qualification.

The first JavaScript run failed during module loading because the exact-schema
parser omitted `UNIQUE INDEX`. That failure is preserved and pinned; the parser
and affected checks were corrected. Existing historical reports are unchanged.

## Deployment limits and next work

Setup is explicit through `prepareObjectAuditRecovery`, which checks the complete
optional schema and existing dispatch contract. Requests do not install tables.
The native host adds its nonce journal at service startup and retains legacy
manual `{}` control calls; the new Worker always uses the stronger nonce and
expected-attempt protocol. Operators must upgrade the host/bridge together before
using this recovery component. Older hosts refuse the new body safely.

This is private integration code, with no uploader-facing route or production
deployment. Public Object admission remains closed; all recovery replies report
zero acceptance/credit and no production authorization. Trusted assignment and
canary qualification, current authentic protection/runtime authority, atomic
publication/once-only credit, real Object search, durable abandon/cancel cleanup
and indefinite retention/capacity still need integration. Full provider/secret
recovery, Mac acceptance and signed clean-device checks remain launch gates.

Andrew's fresh origin export request in private VISION PR #17 is unchanged; no
new source-side work or general approval is requested by this change. No live
schema/deployment, real contribution, Actions run, global installation or frozen
Windows Scene pilot/refresher change occurred.
