# Queued searches: offline implementation

**Implemented in source, disabled and undeployed.** On 12 October the laptop user
approved building the cheaper owner-local design locally, after being asked about
that specific scope: “whatever changes you decide on you are allowed to implement”.
This authorizes offline engineering. Andrew's [operational cost hold](COST_STOP_20261012.md)
continues: no cloud reads, account/resource migration, deployment, paid tests,
Actions or restarting indexing/pilots. No new cloud resource or credential exists.

## Delivered behavior

1. The browser saves an immutable request key before sending a search. The gateway
   reserves its current quoted price in one guarded SQL insert. The account's banked
   balance and ledger remain unchanged; available credits exclude reservations.
2. A trusted owner agent claims a supported lane over outbound HTTPS. The gateway
   supplies the exact normalized query bytes and pinned policy/runtime/snapshot.
   No inbound owner port or public home address is needed. A Scene-only agent never
   claims Object work. Cohort closure prevents new owner execution.
3. The pinned native engine computes locally. The transport saves one private
   completion outbox before delivery; restart/lost-response recovery sends that
   exact completion before claiming anything else. No query is reserialized before
   its fingerprint is checked. Engine failures save a fixed-code report and a
   retryable failure outbox, with no arbitrary stderr or prompt in diagnostics.
4. The gateway checks the existing contributor-only membership, output hash,
   official Gen4 Object evidence, scores, poses, filters, ordering and all request
   pins. One transaction saves the paid result, records one debit and releases the
   reservation. A fresh transaction nonce fences every financial statement.
5. The user can close the page and choose **Recover search** later, or **Cancel
   waiting search**. Failure, cancellation, exhausted claims and expiry spend no
   credit. Account deletion erases queued private data and fences late completion.

Existing paid searches, including older request-key formats, replay before new
admission/configuration/price checks. Old synchronous writers are also prevented
from spending held credit or settling an active queued key during rollback.
New keys include their creation time: after terminal metadata is pruned, an old
unpaid recovery cannot silently become new work. A deliberate new search gets a
new key. This check also protects timestamped requests after rollback to synchronous
delivery. A never-submitted request older than one hour asks the user to start again.
Recovery also has an authenticated read-only endpoint: old large example maps do
not need to be uploaded again under the new small-request policy to retrieve a
paid result. It never executes or charges a search.

## Finite limits and privacy

| Bound | Current source policy |
|---|---|
| Waiting/running jobs | 128 globally; 3 per account |
| Total job metadata | 512 rows; queue refuses excess work without a debit |
| Query / gateway input / paid reply | 64 KiB normalized query; 80 KiB input; 1 MiB paid reply |
| Requested results | At most 1,000 in queued mode; oversized requests fail explicitly |
| Waiting deadline / claim | One hour / five minutes; at most three claims |
| Terminal metadata | Pruned in chunks of 64 after the deadline plus 24 hours |
| Owner spool | One completion/failure; one first fixed report per allowed error code |

Expiry releases holds on the next queue/status/owner interaction; it needs no
cron. A completely stopped service does not perform background database cleanup.
The browser adds no automatic search polling: recovery is an explicit user action.
The transport exposes a finite `run_once()` method, not an installed supervisor.
Future approved supervision must back off at least 30 seconds when idle and longer
on quota/outage/auth failures; it must not spin or add a paid fallback.

The website discloses owner-side processing when queued mode is advertised.
Waiting raw query JSON is cleared at terminal transitions. Saved paid maps and
names remain private account results under the existing deletion policy; a map
name can contain the user's description. Anonymous identifiers do not mean that
the operator/provider cannot correlate requests. Owner memory/native scratch and
in-flight results cannot be instantly erased remotely; deletion prevents server
settlement/recreation, and a stale local completion is erased after a definitive
claim-loss reply. The owner spool belongs in an operator-private folder, outside
sync/GitHub, with normal OS access protection and a deliberate retention policy.

## Source and future activation boundary

- [`search-queue.sql`](../deploy/cloudflare/search-queue.sql) is an **optional
  operator migration**, with its own revision marker, reservation/result guards,
  immutable job identities and deletion trigger. It is never installed by a request.
  The offline [`check-search-queue.mjs`](../deploy/cloudflare/tools/check-search-queue.mjs)
  preflight compares every queue table/index/trigger with this revision's normalized
  source and checks held-credit bounds; a marker alone is not deployment approval.
- [`searchQueue.js`](../deploy/cloudflare/src/searchQueue.js) and the existing Worker
  provide enqueue/status/cancel and separately authenticated owner claim/renew/fail/
  completion routes. `SEARCH_DELIVERY=queued-v1`, a 64-hex-character
  `SEARCH_AGENT_SECRET`, and exact existing search pins are required for new work.
  Dynamic snapshot lookup is refused in this first version; changing the snapshot
  never silently retargets an already waiting job.
- [`owner_search_agent.py`](../community/owner_search_agent.py) accepts separately
  trusted engines implementing `search(request, raw_query=bytes)`. The current
  `NativeSceneEngine` has that interface. No Object native executor, OS startup
  registration, secret provisioning or activation was fabricated here. HTTPS
  transport refuses redirects; a file lock prevents competing local outbox writers.
- The browser's existing journal/recovery flow handles queued responses. The
  optional mode is absent from every checked-in deployment configuration.

For a future approved cutover: rehearse the complete optional SQL migration in a
transaction on a new private copy; verify every guard and the final marker; keep
admission closed and drain writers. Reconcile accounts, paid replies, deletions
**and pending reservations/claims**, then configure the approved isolated resources
and independently pinned owner runtime/catalog. Do not change current resources
or copy private data to a new destination without its specific authorization.
Rollback must retain the queue table/guards and pending work until holds are
released or settled; never drop them to make an older writer run.

## Verification and remaining work

Windows synthetic checks cover competing requests, once-only settlement, injected
partial transaction failure, real SQLite close/reopen, cancellation/deletion races,
legacy paid recovery, pruning/key expiry, HTTP ownership and size limits, strict
Gen4 membership, owner outbox crash/retry, HTTPS bounds/no redirects and writer
locking. The original first-run Windows cleanup failure is retained in the private
`work/queued-search-20261012/first-check.log`; later checks close database handles
before deleting their temporary test folder. This was a fixture cleanup failure,
not a lost financial transaction. Final counts and log hashes are recorded in
`work/queued-search-20261012/receipt.json`.

The final Windows runs passed **101 Node checks and 22 Python checks, with no
skips** (Node 24.19.0, Python 3.12.14). Browser script syntax, unique HTML IDs and
local script links also passed. The native engine and outbound transport were
fixtures; no real inference, provider request or cloud activation occurred.

These are offline protocol/accounting checks. They do **not** prove real Mac/PC
inference, accepted contributions, live owner execution, Free-plan CPU/row budgets,
signing or a continuous soak. In particular, existing gateway membership checks
still use per-location D1 records; result validation and the historical catalog
need measured Free-plan adaptation. Durable paid replies also consume growing
storage and need an authorized retention/storage design. Next: outbound trusted
verification/import jobs and sealed-batch membership, owner supervision/secure
credentials and Object search engine integration; then the approved migration,
real acceptance/capacity evidence and [remaining launch gates](PRODUCTION_ACCEPTANCE.md).
