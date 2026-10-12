# Independent Scene and Object search pins

**Source only, disabled and undeployed.** The [cost hold](COST_STOP_20261012.md)
still applies. This closes the queue's single-binding limitation; it does not
approve an Object runtime, open Object admission or activate any owner process.

## Contract

The optional `SEARCH_QUEUE_BINDINGS` JSON setting supplies separate approved
identities for one or both lanes. It has exactly `version: 1` and `lanes`.
Each lane has exactly these fields:

| Field | Required value |
|---|---|
| `contractVersion` | Number `2` |
| `policyId` | The engine's approved policy ID; 1–128 letters, digits, `_`, `.` or `-` |
| `runtimeSha256` | SHA-256 of that engine's pinned runtime policy file |
| `snapshotSha256` | SHA-256 of that engine's independently sealed snapshot |

Only `scene` and `object` are allowed as lane names. At least one is required;
the entire setting is bounded to 2,048 characters. Hashes are 64 lowercase hex
characters. The Object policy file's hash is distinct from the native runtime
profile hash stored **inside** that file. Qualification and full source/model/
runtime/snapshot verification remain the engine's responsibility.

Independent bindings require `SEARCH_DELIVERY=queued-v1`, a separately provisioned
`SEARCH_AGENT_SECRET`, the existing optional queue schema and all normal account,
cohort, pricing and lane-admission gates. Dynamic snapshots are refused. Do not
also set the legacy `SEARCH_POLICY_ID`, `SEARCH_RUNTIME_SHA256` or
`SEARCH_SNAPSHOT_SHA256`: mixed configuration fails closed.

No checked-in deployment enables this setting. Future activation requires the
approved resources, budget, independently measured runtimes and actual catalogs.
Adding Object pins alone cannot open public Object searches or contributions.

## Owner capabilities and routing

Construct each native engine using its separately approved files, then supply
matching non-secret identities to the inert transport:

```python
engines = {"scene": scene_engine, "object": object_engine}
bindings = {lane: {
    "contractVersion": 2,
    "policyId": engine.config["policyId"],
    "runtimeSha256": engine.runtime_sha256,
    "snapshotSha256": engine.snapshot_sha256,
} for lane, engine in engines.items()}
agent = OwnerSearchAgent(coordinator, engines, private_state, bindings=bindings)
```

This is a library example, not a startup command. Construction does not start
a supervisor, contact the coordinator or register an OS task. Both native
engines keep their existing contracts and independent integrity checks.

Owner claims include `lanes` and `bindings`. The gateway atomically claims only
rows whose lane and complete saved identity match both the current coordinator
configuration and that owner's advertised capabilities. A stale lane receives no
query and consumes no claim attempt; another matching lane can continue. If all
configured requested lanes are stale, the gateway returns a fixed configuration
error. The transport maps this to operator repair and the supervisor latches
across restart, avoiding repeated probes until an explicit repair/reset.
An owner offering only lanes absent from the configuration receives idle status.
Old agents offering lane names without pins are refused by an independent-binding
configuration before any query is disclosed.

The owner rechecks the claimed identity before invoking an engine and checks the
result identity/digest before saving a completion. The gateway still performs
the authoritative contributor membership, Gen4, output and financial checks.
The once-only completion outbox is replayed before any new claim, including after
the operator changes current bindings; it is never rewritten using new pins.

## Saved work and rollback

Each job retains its original binding; it is never retargeted to a newer snapshot
or a different engine. Changing Object pins does not block Scene renewal or
settlement. A changed lane cannot renew, reclaim or settle its old unpaid work;
its hold remains recoverable/cancellable until expiry, with no debit. Starting
new work requires a new user request, preserving the original timestamp rule.

Existing single-binding configuration and saved rows retain their old behavior.
An explicit lane with the identical canonical identity can finish a legacy job.
Rollback to a different single identity cannot claim independently pinned jobs.
Paid replies replay before binding/configuration checks, and read-only recovery
and cancellation remain available without an owner. The queue tables/guards must
remain through rollback; this change needs no SQL migration or revision change.

## Offline evidence

Final Windows evidence includes **73 Node checks, 39 Python unit checks and one
Python/Object-to-gateway interop check**, with no skips. These cover separate lane routing/payment, cross-lane refusal,
stale owner/catalog isolation, renewal and rollback, configuration validation,
HTTP authentication, closed Object admission, exact query bytes, durable outbox
replay and a configuration-repair latch. Python-produced common/hot/semantic
Object packets also pass the actual JavaScript gateway/queue/SQLite ledger using
the new independent Object binding. Models, native results, coverage and initial
credit are synthetic. No authentic admission, earned credit, Mac execution,
Free-plan capacity or uninterrupted operation is established.

Private logs and hashes are retained in `work/owner-joint-search-20261012` on the
laptop. The first HTTP fixture omitted its required `accountId` and correctly
received `account_changed` before Object admission; the fixture was corrected.
Its original failure is preserved. A later supervisor test edit accidentally
moved an older assertion into the new test, where it contradicted the explicit
resume check. That fixture splice was corrected; its failed run also remains.
The [launch gates](PRODUCTION_ACCEPTANCE.md)
and [remaining implementation work](QUEUED_SEARCH_DELIVERY.md) still apply.
