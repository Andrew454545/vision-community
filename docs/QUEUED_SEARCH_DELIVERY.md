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
The optional [owner supervisor library](../community/owner_search_supervisor.py)
now supplies durable pacing, but has not been activated or registered with either
OS. Its idle delay is 30–38 seconds, successful work waits at least five seconds,
and quota/outage/native-failure retries double from 60 seconds to a one-hour cap,
with additive jitter. Crashes also preserve and increase the retry timer across
restart. Success resets transient failure counts. No paid fallback exists.

The supervisor saves a conservative retry deadline **before** network/native work,
uses a separate writer lock and never holds it while sleeping. Fully written
pending timer state recovers an interrupted rename; corrupt/partial state remains
preserved and stops execution. PAUSE/STOP win over timers, an intentional pause
is not reported as a crash, and the explicit loop uses interruptible waits.
Authentication and malformed configuration/replies latch for operator repair
instead of repeatedly probing a bad connection. An explicit connection reset
preserves the completion outbox, first fixed-code failure report and pause/stop
markers. Diagnostics contain no arbitrary exception text, query or credential.
This library has no command-line entry point, listener, startup installer or import
side effects. No real owner loop or background task was started.
The separate inert [owner runner](OWNER_SEARCH_SERVICE.md) now assembles the
libraries behind a pinned configuration and explicit local activation guard.
It defers vault/model loading, replays saved completions first and supports verified
Scene mount reuse after restart. No OS startup registration or activation occurred.

The optional [OS credential reader](../community/owner_search_credentials.py)
and `HTTPSCoordinator.from_os_credentials(origin)` read only a deliberately
provisioned owner-search entry for that exact HTTPS origin. The service/target is
`VISIONCommunity.OwnerSearch.` followed by SHA-256 of the canonical origin; the
entry account is `owner-search-agent`. Windows uses one generic `CredReadW`
lookup and frees the native buffer. Mac uses Apple's fixed `/usr/bin/security`
binary for one service/account in the current user's login keychain, bounded
private stdout and a ten-second owned-child timeout. It never enumerates, writes,
unlocks or changes vault permissions, and has no plaintext/file/environment
fallback. Missing, denied or malformed entries fail with a fixed error. The secret
is used in process memory for HTTPS; this is not protection against an attacker
already controlling that OS user or process. No real OS vault was accessed or
credential provisioned during implementation. Future provisioning must use the
normal OS interface, without passing secrets in command arguments or this chat.
References: [Microsoft CredReadW](https://learn.microsoft.com/en-us/windows/win32/api/wincred/nf-wincred-credreadw),
[CREDENTIALW](https://learn.microsoft.com/en-us/windows/win32/api/wincred/ns-wincred-credentialw),
[Apple security manual](https://github.com/apple-oss-distributions/Security/blob/main/SecurityTool/macOS/security.1).

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
  Optional [independent lane bindings](OWNER_SEARCH_BINDINGS.md) let one coordinator
  serve separately pinned Scene and Object engines. Owner capabilities must match
  each lane before its query is disclosed; saved work is never retargeted.
  Dynamic snapshot lookup is refused in this first version; changing the snapshot
  never silently retargets an already waiting job.
- [`owner_search_agent.py`](../community/owner_search_agent.py) accepts separately
  trusted engines implementing `search(request, raw_query=bytes)`. The current
  `NativeSceneEngine` and the new inert [Object engine](OWNER_OBJECT_SEARCH.md)
  have that interface. The Object engine runs separately pinned accepted batches
  and maps their local IDs to stable snapshot ordinals before global selection.
  Its synthetic verification does not approve an authentic runtime. Explicit
  [OS vault provisioning](OWNER_CREDENTIAL_SETUP.md) is now source-only;
  startup registration, real vault acceptance and activation remain unfinished. HTTPS
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
The [offline financial recovery checks](CREDIT_RECOVERY.md#recovery-with-queued-delivery)
now compare reservations, claims, terminal keys and exact private request bytes
with independent current authority. Balances alone cannot approve a restored
queue; an older version 1 financial snapshot cannot authorize its recovery.

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

The subsequent supervision change passed **31 Windows Python checks, no skips**:
17 new pacing/restart/locking/pause/storage/authentication checks plus the existing
14 transport checks. Its clocks, native engine, coordinator and stop event were
fixtures; tests neither waited in real time nor contacted an external service.
Logs and hashes are private in `work/owner-supervision-20261012/receipt.json`.
This evidence does not establish Mac OS locking, credential storage, startup after
reboot or a running month-long service. OS startup integration and secure credential
provisioning still require implementation and approved activation.

The combined follow-up passed **40 Windows Python checks, no skips** (nine
credential-reader checks, 17 supervisor checks and 14 transport checks). Both OS
vault APIs, the Mac child process and all network/model interfaces were mocked;
no live credential access or Mac execution is claimed. The same private evidence
folder retains the earlier 30/31-check runs and the final combined receipt.

These are offline protocol/accounting checks. They do **not** prove real Mac/PC
inference, accepted contributions, live owner execution, Free-plan CPU/row budgets,
signing or a continuous soak. In particular, existing gateway membership checks
still use per-location D1 records; result validation and the historical catalog
need measured Free-plan adaptation. Durable paid replies also consume growing
storage and need an authorized retention/storage design. Next: outbound trusted
verification/import jobs and sealed-batch membership, owner startup/credential
provisioning; then the approved migration,
real acceptance/capacity evidence and [remaining launch gates](PRODUCTION_ACCEPTANCE.md).
