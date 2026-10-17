# One-shot cloud Scene search

**Source only, disabled and undeployed.** The existing private native host now
has a finite Scene queue runner. It creates no resource, schedule or background
job. The [operational hold](COST_STOP_20261012.md) remains in force.

The runner claims through the [shared search allocation](HYBRID_SEARCH_QUEUE.md),
checks fresh account/resource/runtime authority, performs one native operation,
saves the bounded result and stops the container before delivery. A lost claim
reply recovers the same grant using a durable nonce, without another reservation
or attempt. The budget retains only opaque nonce hashes, including after private
account/job deletion, so an old retry cannot claim a different person's request.
Legacy budget documents upgrade without resetting consumed allowance.

Before native work, it saves a durable alarm for **40 seconds before** the
coordinator's nonrenewable execution deadline. An independent in-memory timeout
uses the same cutoff. Both cancel further startup/hydration/search work. The
durable alarm takes priority over a busy controller; it does not defer shutdown
because an operation is still waiting. A late bundle read cannot restart compute.
An execution window of 40 seconds or less cannot start native work.

Successful results, at most 1 MiB, are saved atomically in checked 32 KiB chunks.
The journal keeps the query's checksum rather than the raw request. Results retain
the existing Scene hit and optional `membership` proof format. The gateway still
checks actual contributor membership, scores, poses, filters and current pins.
This transport does not create publication or qualification authority.

Shutdown requires `destroy()`, `running === false` and `inspect() === null`.
The first durable shutdown receipt is immutable. An unconfirmed shutdown retains
the pending journal and schedules another bounded stop attempt; it cannot release
the claim for local execution. Corrupt metadata still triggers owned shutdown;
the damaged evidence remains and cannot manufacture a fallback acknowledgement.
Provider outage or failed alarm delivery can still
delay shutdown: source guards are **not a provider-enforced invoice cap**.

After confirmed stop, the outbox first delivers the saved result, then acknowledges
shutdown. Reversing that order would invalidate an unpaid completion. Lost replies
replay the same saved bytes/receipt without native execution or another debit.
Restarting an uncertain running attempt stops it; it never reruns that inference.
Without a saved result, confirmed shutdown releases the original request for local
fallback. Paid replies survive configuration closure and rollback through the
existing coordinator recovery path. Private chunks retire only after delivery is
acknowledged or the coordinator definitively reports the old claim lost.

## Deliberate activation contract

No checked-in deployment enables these fields or bindings. A future explicitly
approved staging activation needs all of the following:

- The named private `NativeQueuedSceneSearch` entrypoint, accepting only an empty
  `POST /run-once`, with a finite reviewed trigger. Public native routes stay closed.
- Host `NATIVE_QUEUED_SEARCH_MODE=cloud-scene-v1`, the separate cloud-agent secret
  and private `QUEUED_SEARCH_COORDINATOR` service binding. It permits only the
  confirmed staging bucket, database and account.
- Coordinator `SEARCH_CLOUD_EXECUTION_MODE=native-host-one-shot-v1`, the installed
  shared queue budget and exact staging resource/runtime/snapshot pins.
- Positive finite daily host allowances **and** the monthly/rolling host policy.
  The queued whole-job reservation must cover at least the higher sealed
  request/start weights in those two host windows. New admission with missing/zero
  authority cannot call the coordinator or read a bundle.

Pausing new admission still permits stopping an already-owned container. Paused
delivery retains its outbox. Legacy native compute is blocked while that journal
is pending; aggregate operator status exposes only whether delivery is pending.
No secret, raw query or result is added to public diagnostics.

## Evidence and remaining work

[Windows evidence](evidence/queued-native-20261013.json) records 172 passing Node
checks, without skips, and 15 actual local workerd checks across five separate
processes. Those exercise durable SQLite chunks, D1 settlement, lost replies,
restart recovery, same-nonce concurrent claims, local handoff and actual alarm
delivery. The alarm fixture advances its synthetic controller clock to ensure
the durable alarm wins independently of the wall-clock timer. Containers, costs,
accounts, scores and contributions are synthetic. No inference, cloud resource,
provider, model download or GitHub Actions run occurred.

Original failures remain privately in `work/cloud-executor-20261013`: the first
fixture omitted required staging rate-limit bindings; its deletion case attempted
to bypass retained financial foreign keys; restricted workerd could not open a
Windows SQLite handle; and the initial alarm fixture let the wall-clock timer win
before alarm delivery. Corrected fixtures use real local rate-limit bindings in
workerd, proper private-job deletion and a separately observed alarm. Only the
finite local runtime check needed broader process permissions; no security
setting changed. Both production entrypoints bundle locally.

Still required: approved trigger/binding activation, actual provider shutdown and
whole-job cost/capacity evidence, authentic native Scene operation on the selected
corpus, Object cloud execution, qualified Object admission and allocation for
qualification/other paid work. Real Mac/Windows parity, signing/clean-device,
recovery and endurance gates remain in [production acceptance](PRODUCTION_ACCEPTANCE.md).
