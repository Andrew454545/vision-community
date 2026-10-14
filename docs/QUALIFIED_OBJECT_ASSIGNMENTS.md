# Qualified Object assignments

**Source only, inactive and undeployed.** The internal allocator now automatically
reserves and delivers exclusive batches from an operator-prepared Object pool.
It connects those assignments to the existing qualified upload/publication path.
Public routing, contributor-client integration, automatic fresh pool preparation
and approved private transport/setup remain unfinished. Object capability stays closed.

## Prepared pool and exclusive requests

[`prepareObjectWorkPool`](../deploy/cloudflare/src/objectWorkSchema.js) is an
explicit operator migration, never a public request operation. The optional
`qualified-object-prepared-pool-v1-20261014` namespace retains prepared batches,
request identities, qualification bindings and cancellation history.

[`importObjectWorkPool`](../deploy/cloudflare/tools/import-object-work-pool.mjs)
accepts a separately pinned, bounded operator input under the current eligibility
policy and confirmed Community resource. Each batch contains an existing original
assignment digest, exact source TSV/digest, complete profile, one to four ordered
location/pose/coverage records and an import window of at most one hour. Identical
imports are idempotent; changed retained identities are refused. This function
provides no public endpoint, upload transport, actual transfer consent, qualification,
official coverage approval or protected-source approval.

The original-source private protection service must independently recognize the
assignment and source hashes before delivery, and again before upload acceptance.
Importing a file or setting a client flag cannot supply that authority. The pool
must be prepared from legitimately owned source assignments; automatic source-side
sealing/replenishment is separate remaining work.

[`requestQualifiedObjectWork`](../deploy/cloudflare/src/objectWork.js) accepts a
saved request key, complete qualified profile, maximum count and pace. It selects
an available prepared batch only when its current Object rows, contributed Scene
membership and fresh trusted exact-panorama official Gen4 coverage match. The
account/profile qualification and policy authority must be current.

One transaction reserves the lease, items and locations, binds the request to
its original qualification, and consumes the prepared batch. Concurrent accounts
cannot reserve the same active locations. One account cannot open a second active
Object lease. A retry keeps the same work identity; changed request parameters
conflict. An expired/cancelled request never silently becomes a new assignment.

Delivery requires a fresh private original-source protection challenge. All
qualification, account, Scene, coverage, pose, policy, lease and prepared-state
checks repeat after the reply and in the final transaction. SQL equality checks
use balanced expressions to stay within D1's expression-depth limit without
dropping any comparison. An outage leaves a recoverable preparing request;
a lost reservation or delivery reply cannot allocate replacement work.

The response contains the exact source TSV, public location items and immutable
upload authority. It includes no operator file paths or credentials and earns
zero credit. Ready-request replay recovers the same assignment without another
private preparation call; it still checks current account/qualification/input state.
Upload and publication independently require fresh protection and current authority.

## Upload, cancellation and recovery

The qualified upload checker and final staging/publication transactions now bind
pool assignments to their ready request and original qualification ID. An unfinished
delivery cannot be bypassed, and requalification after revocation cannot silently
rebind an old assignment. The existing private operator-prepared path remains
separate; no native approval is manufactured or weakened.

Cancellation works without the private service or active runtime policy. It
releases an active lease's locations and retains the cancelled request and consumed
pool identity. Submitted uploads are retained for settlement; accepted credit and
publication are not undone. Account deletion cancels active requests and preserves
accepted work and financial history. The expiry trigger applies only to this
namespace's Object leases.

Version-3 financial snapshots now include the optional pool's exact schema,
prepared records, saved requests and their lease/location/artifact histories.
Missing allocation history, changed cancellation state, weakened fences or an older
cutoff that omits the pool fails comparison. Whole-SQL-dump recovery is checked
with accepted work. This is local cutoff comparison, not provider recovery or
permission to open admission.

Metadata is finite: at most 64 available prepared batches, 4,096 retained batch
identities, and eight combined active allocated requests/pending qualified uploads.
Expired available batches retire automatically; history is never silently deleted.
Sealed rollover/import must be integrated before claiming indefinite operation.

## Evidence and next work

[Windows evidence](evidence/qualified-object-assignments-20261014.json): **80 Node,
53 Python and 22 actual local workerd checks** pass with no skips. Nineteen Node
and six Python cases are new; the remainder verify affected qualification,
publication, financial and queued-search behavior. Four fresh workerd processes
check outage/resume, prepared allocation, upload, publication, saved receipt replay
and deletion using actual local D1/R2 persistence.

All accounts, numerical qualifications, model declarations, original-source replies,
coverage and outputs are synthetic. No real qualification, contribution or credit
is claimed. Original failures are preserved, including the corrected response-read
budget and the D1 expression-depth failure. No cloud account read, model/imagery run,
deployment, Actions run or indexing restart occurred.

Next finish trusted source-side pool sealing/replenishment, approved private setup
and contributor/public routing while retaining closed defaults. Then finish Object
search execution, shared allocation for other paid work, and sealed corpus/import
recovery. The operational hold and actual [launch gates](PRODUCTION_ACCEPTANCE.md)
remain unchanged.
