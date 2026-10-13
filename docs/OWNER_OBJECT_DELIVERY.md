# Outbound Object audit coordination

**Offline source only.** No configuration enables this path; the
[cost hold](COST_STOP_20261012.md), paused tasks and launch gates are unchanged.
This is an operator protocol, not a new contributor setup step.

The optional coordinator connects results from the
[direct owner verifier](OWNER_OBJECT_VERIFICATION.md) to the existing quarantine,
sanitized publication and once-only credit transaction. The owner's computer
initiates requests; the coordinator never starts a hosted model or contacts the
owner's computer. It reuses existing dispatch/settlement schema and writer fences;
HTTP requests do not install them.

The future setting is `OBJECT_AUDIT_DELIVERY=owner-outbound-v1`, with a distinct
`OBJECT_AUDIT_AGENT_SECRET` and independently reviewed `OBJECT_SETTLEMENT_POLICY`.
The hosted `OBJECT_VERIFIER` binding must be absent. Invalid or mixed configuration
fails closed. Only the already-confirmed Community environment/resource pair is
supported; a new Free account still requires an authorized migration and evidence.

All four private routes use POST under `/api/object-audit-agent/`. Owner-secret
authentication precedes body/database access. Account codes cannot authorize them.

| Route | Purpose |
|---|---|
| `claim` | Match the owner's independent policy/runtime/quality/protection/resource binding, then claim one eligible batch for at most 1,200 seconds. Return bounded metadata, not candidate bytes or account credentials. |
| `candidate` | Return the exact digest-bound quarantined candidate for the current live claim. Bound the existing native request to 4 MiB. |
| `complete` | Validate native identity and fresh full protection evidence, then use the existing guarded publication/credit transaction. Replies are bound to immutable accepted identity on recovery. |
| `fail` | Save bounded busy/outage backoff without financial changes. Busy slots do not consume failure attempts; eight transport failures require operator attention. |

Claims require submitted ownership and fresh current official Gen4 authority.
Accepted work releases its existing queue slot. Failed native jobs do not retry
themselves. Contributor status reads in this mode cannot start inference or
publish a cached approval. Scheduled retirement never falls back to a hosted
verifier in this mode.

An uncommitted expired proof returns `owner_object_evidence_refresh_required`.
The owner must recheck real current protection on the same saved native job;
changing timestamps or recomputing the whole batch is not recovery. First replay
the saved completion: a committed acceptance recovers without fresh inputs,
another award or R2 read. A stale/deleted/replaced claim returns
`owner_object_claim_lost`. Artifact interruption retains the saved native identity
for a new claim and fresh evidence. Cancellation, deletion, pose/coverage changes
and the database clock remain final settlement fences.

## Owner delivery and restart recovery

The inert Python `OwnerObjectAuditAgent` now connects the coordinator to the
existing `OwnerObjectVerifier` and durable native job spool. Each invocation
claims at most one batch and runs at most one saved audit step. It checks the
independent policy binding and exact candidate/source digests before submitting
native work. A saved job is read by identity; a failed or missing job is never
silently recreated or retried.

A bounded, flushed local outbox saves the completion before delivery. After a
restart it sends that exact completion first, before claiming or accessing native
files. This recovers an already committed award even when the old proof has
expired. Only the coordinator's explicit uncommitted-expiry response permits
full current protection revalidation on the same saved job. Refresh preserves
the first old proof and the native receipt; it never edits proof timestamps or
reruns inference. Completed pending writes recover after a rename interruption;
incomplete bytes and the first failure report remain private. Lost claims discard
only their delivery outbox, not native work or receipts.

`HTTPSObjectCoordinator` permits only the four fixed routes at one explicit HTTPS
origin, refuses redirects and bounds request/reply bytes. Its read-only OS vault
adapter uses the separate `VISIONCommunity.OwnerObjectAudit.` namespace and
`owner-object-audit-agent` account, never the search key. No real credential was
read or written. Dedicated Object key provisioning and a configured launcher
remain required; the existing search provisioner must not be used for this key.

The existing durable supervisor accepts a bounded coordinator wait hint and the
`native_verification_failed` category. Healthy queue capacity waits respect the
15-minute server delay without recording a fault. Authentication, protocol and
independent-policy errors latch for operator repair; outages back off across
restart. PAUSE/STOP win before calls. A future launcher must use an activation-only
guard so committed reply recovery does not require unavailable native assets;
native/protected-input guards still apply before all new work or proof refresh.
These finite interfaces install no task, listener or background loop.

[Windows synthetic evidence](evidence/owner-object-queue-20261013.json) records
64 passing Node checks with no skips, including real local SQLite transactions
and Worker handlers. Native results, storage and coverage are fictional. The
Python verifier component was checked separately; these checks do not establish
a complete live Python-to-cloud pipeline, authentic inference or Free capacity.
The [owner client supplement](evidence/owner-object-agent-20261013.json) checks the
assembled Python job/protection and Worker/SQLite publication path locally,
including lost acknowledgements, fresh proof recovery and changed protected
files. Its inference, coverage and storage are fictional; it does not qualify
an authentic Object cohort or replace actual Mac execution.

Still required: dedicated Object key provisioning, configured owner launcher and
startup, outbound cancellation/deletion/retirement acknowledgement, bounded batch
metadata, approved migration/recovery and all
[authentic launch gates](PRODUCTION_ACCEPTANCE.md). Quarantine relay and full
Object validation still need measured CPU/storage budgets. Nothing here authorizes
activation, provider/model tests, a data transfer or an account change.
