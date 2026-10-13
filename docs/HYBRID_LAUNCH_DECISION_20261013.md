# Approved hybrid launch direction

On 13 October the laptop user approved this product change and confirmed that
the **$10/month processing budget is additional to R2**. This supersedes the
Free-only/owner-mirror recommendation in the earlier cost plan. Keep online
banked-credit searches. No full-index download entitlement is adopted.

## Contribution trust and assignment

- Qualify Windows and Mac devices against a small fixed reference sample using
  identical inputs and pinned models/runtime/settings. Use measured numerical
  tolerances; neither exact bytes nor human object labels are required by default.
  Runtime/model/profile changes require renewed qualification.
- After qualification, routine uploads may be accepted without recomputing every
  location on a trusted host. This is an explicitly approved trust tradeoff:
  qualification demonstrates compatibility, not authenticity of every later
  score. Retain the existing fully audited mode as a separate option.
- Implement a distinctly named qualification-based admission policy and retain
  it with publications/credit receipts. Never label those uploads independently
  recomputed or rewrite earlier audit evidence. Revoke admission for a failed
  qualification or detected incompatible/corrupt uploads.
- Continue bounded format, checksum, finite score, model/policy identity,
  assignment and duplicate checks. These do not prove genuine inference. Objects
  still require trusted current official Google Gen4 eligibility, Scene membership
  and protected-source authority. No uploader may self-assert those authorities.
- Use exclusive lane-aware leases and resumable work IDs. Accept/credit each
  unique location/lane once. Recovery after a lost lease can repeat computation;
  do not promise that distributed crash recovery never duplicates any effort.
  Scene and Object work for the same location are intentionally distinct.

This mode is a source implementation requirement, not an already-enabled shortcut
through the current trusted-audit publication path. Do not manufacture an auditor
receipt or weaken existing SQL guards to get a first contribution through.

**Scene implementation:** the [qualified Scene path](QUALIFIED_SCENE_UPLOADS.md)
now connects explicit admission, upload integrity, once-only credit, search and
offline snapshot/financial recovery in source. It is disabled and undeployed;
equivalent qualified Object admission remains work.
The [Object upload inspector](QUALIFIED_OBJECT_UPLOADS.md) now separates routine
integrity from native per-batch comparison in source; device qualification,
fresh protected/Scene authority and qualified Object settlement remain open.
The [shared search queue](HYBRID_SEARCH_QUEUE.md) now connects cloud cost
reservations, exclusive cloud/local claims and shutdown-fenced fallback in source.
The [finite native Scene executor](NATIVE_QUEUED_SEARCH.md) now has durable
claim/result/shutdown recovery in source. Approved trigger/bindings, actual
provider/cost evidence, Object execution and other paid work's allocation still
need integration before activation.

## Cloud first, local overflow

Keep permanent Community indexes in confirmed R2 resources. Cloud search and
qualification run on demand and sleep afterward. Local trusted processors on
the laptop or Andrew's computer may consume queued overflow when available.
Avoid requiring a permanent full local corpus; use separately approved bounded
working storage. Owner availability and local disk must be checked before a
claim. Do not install/start work on Andrew's computer from general laptop consent.

Reserve a conservative maximum job cost before cloud work, including startup,
hydration, execution and idle tail. Use a hard execution deadline and stop
uncertain running compute. Failed/uncertain reservations are not refunded.
Do not switch an ambiguously started job to another executor until its original
claim is fenced; otherwise both machines may execute or settle it.

Start with a maximum $3 native-compute allocation, reserve $5 for the Workers
base plan and $2 for other non-R2 usage/headroom. This is an application spending
envelope, **not a guaranteed $10 Cloudflare invoice cap**. Other account usage,
provider metering, storage and subscription charges cannot be limited by a job
counter. No automatic upgrade or extra paid executor is authorized. The first
configuration needs a consistent prior-usage cutoff and conservative measured
operation prices. Do not spend this allowance on Actions or repeated audits.

When cloud admission refuses work, retain its immutable request and credit
reservation and make it available to an appropriate trusted local executor, or
leave it waiting within its deadline. Never charge an offline/error path or
silently submit an expired request as new work. Previously paid replies remain
recoverable without another debit under either executor.

## Implemented first component

The existing native host's [compute guard](../deploy/cloudflare/native-container-host/compute-budget.js)
now supports optional `NATIVE_MONTHLY_COMPUTE_POLICY`, a JSON object with exactly
`limitCents`, `openingCents`, `requestCents` and `startCents`. The limit is at most
300 cents. Opening reservations conservatively account for earlier usage;
request/start reservations use operator-reviewed maximum cost weights, not actual
provider billing. Zero allowance refuses compute. No deployment sets this policy.

The [monthly record](../deploy/cloudflare/native-container-host/monthly-budget.js)
shares the existing transaction with daily admission. Restarts and midnight cannot
reset it; raises in allowance or decreases in cost weights cannot reopen the
current month. Removing the policy after use fails closed. Failed durability
does not grant work. Exhaustion uses the existing controller's stop-before-retry
path and exposes an aggregate monthly status without private prompts/accounts.

This is **one host allocation**, not a shared project-wide authority. Multiple
cloud hosts require a common reservation service or disjoint sealed allocations
whose total fits the envelope. No automatic local fallback, upload trust change,
cloud reactivation or complete project dollar cap is claimed from this component.

Windows offline checks: all **79** existing/extended compute-budget and controller
cases passed, with no skips. They cover concurrent reservations, month rollover,
configuration tightening/removal, prior usage, zero allowance, corrupt records,
durability failure and existing stop/deadline behavior. No provider call, model
execution, cloud read or deployment occurred. Private logs are preserved under
`work/hybrid-budget-20261013` outside the checkout.

### Month-boundary protection

A calendar counter alone can grant two allocations close together at month-end,
including within one provider billing period. The additional
[rolling guard](../deploy/cloudflare/native-container-host/rolling-budget.js)
limits reservations over the preceding **31 days**, in the same durable
transaction as the monthly and daily records. All three limits must allow work.
The history is bounded at 300 entries because each reservation is at least one
cent and the host allocation is at most 300 cents. Only timestamps and reserved
cents are stored; no account, query or job content is included.

Calendar resets, controller replacement and configuration increases cannot
clear recent reservations. Lower limits and higher cost weights remain sealed
while history is active, which can pause work longer than a calendar month.
Unknown earlier monthly usage is conservatively carried at upgrade time for a
full 31 days. The opening floor is applied without repeatedly adding the same
floor to active history. An operator must reconcile prior usage and clear an
obsolete configured opening floor before activation; counters are not a billing
reconciliation. Corrupt state or failed durability refuses work. Exhaustion
stops the active container, preserves its sealed bundle and returns a backoff
until enough reservations expire. Status and explicit stop remain available.

[Offline evidence](evidence/rolling-host-budget-20261013.json): **86 checks
passed**, no skips, including the controller's month-end refusal and shutdown,
concurrent reservations, February spanning three calendar months, legacy usage,
read-only status, removal/corruption and existing deadline behavior. Private
logs and a source-digest receipt are preserved in `work/rolling-budget-20261013`.
This still bounds one host's reservations, not provider charges, shared-host
spending or a complete project invoice. No allowance or service was activated.

## Next engineering and activation boundary

1. Integrate the explicitly marked qualified-upload publication path, preserving
   eligibility, once-only credit and deletion. Validate a common Mac/PC reference
   policy from actual evidence; no new full matrix by default.
2. Connect the [shared queued-search authority](HYBRID_SEARCH_QUEUE.md) to an
   actual bounded cloud executor with durable completion/shutdown recovery.
   Integrate initial qualification and other paid work into the common allocation
   or sealed disjoint envelopes. Measure prices before enabling any allowance.
3. Complete sealed-batch import/storage and bounded metadata so millions of
   locations do not require millions of coordinator rows or a full owner mirror.
4. Resolve the existing operational stop with a concrete owner handoff before
   changing shared-account resources, deploying or restarting jobs. Preserve zero
   allowances, disabled endpoints/crons/tasks and original interrupted pilot data
   during offline implementation. The latest user decision authorizes engineering
   of this hybrid mode; it does not establish actual service activation.
5. Run the remaining real platform, download, financial/recovery and accepted-work
   launch gates on this architecture. Their numerical qualification requirement
   remains, while full trusted recomputation of every routine upload is no longer
   the required contribution trust model. Do not claim production readiness yet.
