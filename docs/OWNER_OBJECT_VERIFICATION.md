# Owner-local Object verification

**Offline source only; the cost hold continues.** No service, task, listener,
model, provider or cloud account was activated. Contributors have no new command.

[`OwnerObjectVerifier`](../community/owner_object_verifier.py) lets a future
authenticated outbound worker use the existing saved Object auditor directly,
without an incoming HTTP connection to the owner's computer. It takes an
already-pinned `ObjectAuditJobs` instance and a required activation guard.
The guard must raise if the pinned configuration or activation is revoked.
Construction does not start a loop or listener. The existing private HTTP service
uses the same [finite command dispatcher](../community/object_audit_protocol.py).

`handle(method, path, raw)` stages candidates, reads status, cancels, requests
erasure/retirement, or obtains fresh settlement evidence. It preserves original
submission bytes. Only fixed audit routes and opaque IDs are accepted; callers
cannot supply a URL, executable, private file path, model, tolerance or approval
authority. Submissions stay at the existing 4 MiB limit, controls at 1 KiB and
replies at 64 KiB. Owner-delivered retries require the existing durable request
nonce and expected attempt; replaying one cannot queue another attempt.

`work_once()` is a separate bounded owner action. It performs at most one existing
audit/erasure/retirement step, without starting the old background worker. Native
process ownership, finite deadlines, spool capacity and preserved attempts remain
with the existing auditor. PAUSE/STOP prevent commands and new work. Guard failure
does not disclose an approval; a staged job remains recoverable. Unexpected faults
return fixed codes and retain the first redacted local failure report.

The pinned registry chooses assignments. Source/runtime/model/numerical parity,
official Gen4, Scene membership and protected-source checks remain unchanged.
Fresh settlement evidence rechecks current authority on every call and expires
after 30 seconds; a saved historical approval cannot replace it. The native
response grants no publication, device qualification or search credit.

The [Windows synthetic receipt](evidence/owner-object-local-20261012.json) records
**26 passing checks, no skips**, including the existing private HTTP/process
recovery endpoints and actual Python-to-JavaScript evidence compatibility. The
initial suite timeout and sandbox socket failure are preserved. Native inference
and source artifacts are fixtures. This is not authentic Mac/PC qualification, live provider recovery,
measured capacity, activation or endurance evidence. New source pins require
separately measured runtime approval; existing real policies are not refreshed.

Next: connect authenticated outbound claims and exact reply replay, propagate
current deletion authority, and consume fresh evidence through guarded
publication/once-only credit. Bounded batch metadata, admission, owner startup,
migration/recovery and the remaining [launch gates](PRODUCTION_ACCEPTANCE.md) also
remain required. This adapter alone is not an operating cloud queue.
