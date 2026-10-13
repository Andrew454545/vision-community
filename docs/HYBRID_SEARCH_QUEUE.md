# Shared search allocation and local fallback

**Source only, disabled and undeployed.** This implements queued-search claim
routing for the [approved hybrid plan](HYBRID_LAUNCH_DECISION_20261013.md).
It starts no executor, model, provider call, service or background task.

A trusted cloud executor reserves its conservative whole-job cost from one D1
authority before receiving a query. Scene and Object searches share that
allocation. Calendar-month and rolling 31-day limits both apply, at most 300
cents, with sealed cost weights and prior-usage floors. Concurrent executors
cannot claim the same request or each obtain a separate allowance. Local claims
reserve zero compute cents. Failed or uncertain cloud reservations are retained.
This is application admission accounting, **not a provider invoice cap**.

Local processors wait a short, configured cloud preference window. If the
allocation is exhausted or unavailable, they can claim new waiting work
immediately. If no cloud executor responds, the preference window expires and
local work can proceed. Claims preserve the original request key, query bytes,
credit hold, lane and runtime/snapshot pins; no new user search is submitted.

Once a cloud claim is granted, its execution deadline cannot be renewed beyond
the original bound, at most 240 seconds. An expired or ambiguously started
cloud claim is **not** reassigned automatically. The separately authenticated
cloud executor must first acknowledge shutdown and supply the SHA-256 of its
saved shutdown receipt. The coordinator records that first receipt, invalidates
the old claim and releases the same job for local processing. Conflicting
receipts are refused. This acknowledgement is a trusted executor assertion;
the coordinator does not independently observe the provider's processes.

Without shutdown acknowledgement, the job waits until user cancellation or its
original one-hour expiry, with no credit debit. This deliberately prefers a
safe wait to uncertain duplicate execution. Local claims retain the existing
bounded restart recovery. Actual publication/search-result validation and
once-only debit still use the original guarded settlement. Already paid replies
remain recoverable after service/configuration closure without another charge.

## Operator contract

The optional [migration](../deploy/cloudflare/tools/prepare-search-hybrid.mjs)
adds the shared budget, bounded executor metadata and SQL claim fences. Requests
never install it. Running legacy claims must be reconciled first. The migration
creates a retained initial seed; requests never recreate a missing budget row.
Missing/corrupt history blocks cloud work while otherwise valid local work can
continue. Rerunning setup cannot erase or reseed consumed budget. Preserve all
tables/triggers and the latest cost authority during rollback and recovery.
An older queue writer cannot bypass the installed claim fence.

`SEARCH_DELIVERY=queued-v1` remains the queue protocol. Future explicit setup
also requires a distinct `SEARCH_CLOUD_AGENT_SECRET` and `SEARCH_HYBRID_POLICY`,
a JSON object with exactly these fields:

| Field | Meaning |
|---|---|
| `version` | `1` |
| `limitCents` | Shared queued-search allocation, 0–300 |
| `openingCents` | Conservative earlier-usage floor, at most the limit |
| `sceneCents`, `objectCents` | Reviewed maximum cost per whole cloud job, 1–300 each |
| `cloudGraceSeconds` | Cloud preference window, 0–300 seconds |
| `maxExecutionSeconds` | Nonrenewable cloud claim bound, 1–240 seconds |

These fields are not measured prices. Before activation, reconcile a consistent
prior-usage cutoff and measure startup, corpus hydration, execution and shutdown
tail. Clear obsolete configured opening floors only against that authority.
The budget history is one bounded record with at most 300 active reservations;
executor metadata follows the existing 512-row queue retention/deletion rules.
Deleting an account clears its queued private claim metadata, while aggregate
cost reservations remain without account/query identifiers.

The existing `/api/search-agent/` routes remain local and retain the five-field
job reply expected by the installed owner client. Separate authenticated
`/api/search-cloud-agent/` routes provide `claim`, `authorize`, `renew`, `complete`,
`fail` and `stopped`. Cloud claims additionally return `executionDeadline` and
`reservedCents`. Account credentials and local-agent credentials cannot use
cloud routes. A caller-supplied executor field cannot change its role.

The read-only [offline preflight](../deploy/cloudflare/tools/check-search-hybrid.mjs)
checks exact schema guards, claims, retained budget and shutdown evidence on a
closed private database copy. It does not refund, reset or migrate anything,
and cannot prove that an old backup is the latest spending/deletion/financial
authority. Those independent recovery requirements remain.

## Evidence and remaining activation work

[Windows evidence](evidence/hybrid-search-20261013.json): **109 Node checks**
passed without skips. The actual local Cloudflare runtime passed **8 checks
across two separate processes**, including concurrent D1 reservations, exhausted
allocation fallback, preserved uncertain claims, identical-request handoff,
stale completion refusal, durable cost history and once-only paid recovery.
Costs, accounts, contributor features and native scores are synthetic. This is
not authentic Object admission, measured provider cost or hosted capacity.

Original failures remain private in `work/hybrid-search-20261013`: a test cleanup
closed its database too late on Windows; the first installed runtime was too old
for the existing compatibility date; the first HTTP fixture expected 200 instead
of the API's existing 202 queued acknowledgement. Cleanup/fixture expectations
were corrected and the already installed compatible runtime was used. No runtime
download or deployed API/configuration change was needed.

The [one-shot native Scene runner](NATIVE_QUEUED_SEARCH.md) now implements durable
claim recovery, deadline shutdown and completion/stop outbox replay in source.
Its additional local evidence does not establish actual provider shutdown or
native capacity. Still required before activation: approved trigger/binding setup,
real price/capacity/shutdown evidence, Object cloud execution, and
participation or disjoint sealed allocations for **all other paid work**, including
initial device qualification. The private native host's existing allowance is
an additional fence, not permission to bypass this shared search allocation.
The complete $10 processing envelope and all real launch gates remain open.
The [operational hold](COST_STOP_20261012.md), zero native allowances, disabled
endpoints/crons and paused indexing/pilot tasks are unchanged.
