# Saved Object handoff — 11 October 2026

The private candidate component now connects owned R2 quarantine to the saved
native audit protocol. It persists the exact payload and assignment/profile/
policy/source pins before dispatch. A lost start reply resends the same payload;
the native assignment fingerprint recovers the original job. Later requests
use its saved job ID and check every correlation field and manifest pin.

A short persisted claim prevents competing handlers from overwriting saved
state. Interrupted claims recover. Transport retries back off and stop after
eight failures for operator attention; failed native inference is not retried
automatically. Replies and payload streams share bounded reads/deadlines.
An approved historical receipt cannot be replaced or treated as a fresh reply.

Quarantine retains assignment ownership and cannot be leased to somebody else.
Account deletion or lease revocation cancels pending dispatch and defeats late
approvals. Existing account cleanup journals native assignment erasure, including
starts whose acknowledgement was lost. Rejection/revocation releases the rows.
The ordinary submission retry now counts actual published artifacts; uploaded
Scenes and Objects awaiting audit are reported as pending, never accepted work.

## Verification

[Pinned evidence](evidence/object-audit-dispatch-20261011.json) records:

- **194/197 affected Windows JavaScript checks passed**, zero failures and three
  existing file-symlink permission skips; 22 new dispatch cases are included.
- **10 actual local workerd/D1/R2 scenarios across four fresh processes** cover
  lost acknowledgement, recovered job, current deletion and fenced replay.
- **One actual Node/bridge-to-Python HTTP/SQLite interoperability test passed**.
  Two starts recover one native job and one attempt, preserve the exact native
  manifest/receipt pins, and erase it after account deletion. Inference is an
  explicit synthetic runner; its four calls are separately recorded.

The initial two-second interoperability observation ended while comparison was
still running. Both failures remain private and pinned. The finite observation
is now twelve seconds; cleanup keeps the synthetic runner installed until its
owned worker stops. A later pass does not rewrite either failure or the earlier
offline diagnostic. This is component evidence, not authentic qualification.

## Integration limits

The optional schema is installed only through an explicit operator helper.
Its checkpoint verifies the exact tables/indexes/deletion fences; HTTP installs
nothing. The deployed schema revision is unchanged. The finite cohort is bounded
to four locations per candidate, a request below 4 MiB, eight pending and 64
retained candidates. These are integration limits, not indefinite public capacity.

The public Object gate remains closed. The new functions are not wired to an
uploader-facing start/status route: their authority argument must come from a
trusted qualification/assignment registry. The existing local-only prototype
is not an audited contribution path. Fresh portable protection/runtime authority,
exact canary qualification, atomic publication/once-only credit and real Object
search still need integration and authentic acceptance. Explicit native retry
and connection resumption are now implemented in the [recovery follow-up](OBJECT_AUDIT_RECOVERY_20261011.md).
Durable abandon/cancel cleanup, retention and provider recovery remain work before deployment.
Every dispatch response reports zero accepted work/credit and no qualification.

Andrew reports the preceding native coverage/Windows repair merged as VISION
PR #16 at `a3e3bd0cc3897d7324e2177e786fe003587c42e4`; the narrow fresh-origin
export request remains in private PR #17. No new owner execution is requested by
this component. No provider deployment/schema change, Actions run, global install,
real credit or frozen Scene pilot/refresher change occurred.
