# Cost recommendation for owner discussion

**Recommend free-tier coordination + R2 + Andrew's existing computer for trusted
verification and search.** Contributors still index locally. This removes hosted
model execution, retains online banked-credit searches, and gives a small pilot
an affordable path. The tradeoff is queued service when the owner's computer is
offline and finite owner capacity. This is a proposal, not a migration decision
or a claim that the current application already runs on the Free plan.

Prepared from Community source `65d73a5`, the private VISION reference checkout
`5e57a26`, saved evidence and public provider documentation checked 12 October.
No customer Cloudflare reads, inference, provider tests, deployments, Actions or
new private-data transfers were used. [The cost hold](COST_STOP_20261012.md)
remains in force. The September [architecture notes](../ARCHITECTURE.md) are
historical; the user subsequently chose online banked-credit searches.

## Why cloud compute exists despite local indexing

| Current operation | Why it exists | Proposed location |
|---|---|---|
| Scene canary comparison and submission audit; Object reference inference/comparison | An uploader's checksum proves byte identity, not correct inference. Scene qualification compares saved reference bytes; submission audits recompute references. Object audits also check trusted assignment/source/protection and model output. | Trusted owner computer; contributor-side checks remain advisory. |
| Query embedding and searching the accepted index | Online credit enforcement cannot survive distributing the entire searchable index. New search queries still need model/search execution. | Owner computer, using a separate contributor-only Community catalog. |
| Container startup, bundle hydration, snapshot refresh and restart diagnostics | Keep the hosted native process and its accepted index ready/recoverable. | Remove hosted dependency; owner agent imports accepted batches locally. |
| Authentication, leases, quarantine, publication, deletion, ledger and paid-reply replay | Protect anonymous account keys, prevent duplicate work/credit and enforce deletion and search payment. | Small Free Worker/D1 coordination, with bulk artifacts in R2. |
| Website and onboarding | Explain installation and show status/search results. | Static assets; no model execution or server rendering needed. |

Source: [Scene admission/audit](../deploy/cloudflare/src/scenePipeline.js),
[native Scene verification](../community/native_scene_verifier.py),
[native Object verification](../community/native_object_verifier.py),
[online search](../deploy/cloudflare/src/onlineSearch.js),
[native host](../deploy/cloudflare/native-container-host/controller.js).
The real restricted Scene path used the hosted native service. Object publication
and native job machinery are implemented in source; full real Object admission
and its production deployment remain unfinished. Historical prototype paths do
not establish that shape/hash checks alone are sufficient.

Containers require Workers Paid and meter running CPU, provisioned memory/disk
and potentially egress, alongside Worker and Durable Object usage. Sleeping stops
container execution billing, not existing subscriptions or retained storage.
Native request/start allowances bound operations, **not the entire invoice**.
[Containers pricing](https://developers.cloudflare.com/containers/platform/pricing/)
explains these separate meters. Workers Paid has a **$5/account/month minimum**
and usage overages; the current shared paid account is not a project-level Free
cap. [Workers pricing](https://developers.cloudflare.com/workers/platform/pricing/).

## Practical choices

| Option | Non-R2 hosting cost | Trust and user experience | Assessment |
|---|---|---|---|
| Free coordination + owner-local verifier/search + R2 | No new paid compute subscription if coordination is genuinely Workers Free; quotas stop service. Owner hardware/electricity still cost money. | Trusted audit/ledger; online search can queue while the owner is offline. | **Preferred for a bounded launch.** Reuses existing contracts and native tools. |
| Owner-local verifier/search/ledger + R2 mailboxes; static website only | No metered Worker/D1 backend; requests/polling/storage become R2 costs. | Requires secure mailbox permissions, serialized credit authority and more client protocol changes; owner remains availability bottleneck. | Viable if absolutely no dynamic cloud service is wanted; more custom engineering. |
| Free coordination + download the full index for local searches | No hosted search inference; storage/transfer requests are R2 operations. | Numerical parity remains possible, but one-credit-per-search cannot be enforced after download. | Requires changing the user's chosen online-credit product. Not recommended. |
| Existing hosted containers, even with lower daily limits | Paid minimum plus possible non-R2 overages. | Better independent availability, with the existing audit/search design. | Fails the requested strict spending constraint. |

Moving trusted verification to arbitrary contributors cannot preserve the same
trust: an attacker can forge results and mint credit. Qualification alone does
not prove every later submission. Spot-checking can reduce owner work but changes
the fraud guarantee; keep current independent checks initially. Do not silently
replace them with self-reported hashes, a relaxed tolerance or an old protection
capture. Mac/PC parity is automated comparison on identical inputs/settings;
human confirmation of object presence is unnecessary. Current official Google
Gen4, Scene membership and protected-source authority remain required for Objects.

## Free limits and what happens when reached

- **Workers Free:** 100,000 dynamic requests/day per account, 10 ms CPU/request,
  128 MB memory. At the daily quota requests fail rather than buy more capacity;
  use fail-closed API routes. Authentication/signature parsing must fit this CPU
  budget. [Workers limits](https://developers.cloudflare.com/workers/platform/limits/).
- **D1 Free:** five million rows read and 100,000 rows written/day, 5 GB total.
  Index updates count too. Daily exhaustion stops queries until reset; a full
  database needs storage relief. Paid D1 instead bills overages.
  [D1 pricing](https://developers.cloudflare.com/d1/platform/pricing/).
  Each Free database is limited to 500 MB, 50 queries per Worker invocation and
  seven-day Time Travel. Keep bulk indexes out of D1 and maintain separate private
  backups. [D1 limits](https://developers.cloudflare.com/d1/platform/limits/).
- Static asset delivery is free/unlimited, but the current `run_worker_first:true`
  invokes the Worker even for the website. A future migration should send only
  API paths through it so instructions remain accessible at API exhaustion.
  [Static asset billing](https://developers.cloudflare.com/workers/static-assets/billing-and-limitations/).
- Standard **R2**, which Andrew accepts, charges $0.015/GB-month, $4.50/million
  Class A operations and $0.36/million Class B operations, beyond included usage
  (10 GB-month, one million A, ten million B). Internet egress is free; R2
  requests/storage are not unlimited free usage. Polling and retained quarantine
  must be bounded. [R2 pricing](https://developers.cloudflare.com/r2/pricing/).

These are account quotas, not a promise of unlimited contribution volume. For
illustration, ten D1 row writes per accepted location would consume the entire
100,000-write allowance at 10,000 locations/day **before** leases, searches,
deletions and other traffic. Actual row counts and owner throughput must be
measured; this is not a capacity result. Use batched jobs, indexed lookups and
headroom. At limits stop issuing new work, retain completed uploads locally,
back off with jitter, and resume with the same job IDs. Never invent acceptance,
lose credit or automatically upgrade a plan. Slow/busy/offline status must be
plainly visible to users.

## Preferred design and enforceable spending boundary

Use a **dedicated Workers Free account** for the small public coordinator if the
existing account must remain Paid for unrelated services. Do not downgrade the
shared account. Free quotas can prevent non-R2 usage overages for that isolated
coordinator; application counters or alerts in the existing Paid account cannot
provide the same guarantee. Confirm the new account's actual entitlements before
activation and never automatically upgrade it. No account was created here.

Keep existing Community R2 data in its approved account. An owner-local agent
can issue short-lived URLs for exact upload/download keys using bucket-scoped S3
credentials; credentials never go to contributors. This avoids assuming a native
R2 binding spans accounts. Presigning needs no R2 request, but using the URL does.
URLs are bearer capabilities, reusable until expiry, not proof of correct data
or a dollar cap; enforce finite permits, upload size/digest checks and quarantine.
[R2 presigned URLs](https://developers.cloudflare.com/r2/api/s3/presigned-urls/).
No existing bucket/database is moved by this proposal.

The owner agent polls bounded queues outbound, with no exposed home address or
inbound operator port. It verifies pinned assignments and numerical output,
checks the real current Scene/protection authority locally, and returns an
authenticated receipt bound to source, candidate, policy and job ID. D1 publishes
and grants credit once. Use a separate Community search catalog containing only
accepted contributor work; Andrew's personal indexes remain reference evidence,
not public search data. Keep private database access on the owner machine.

Search becomes a resumable queued job. Atomically reserve available credit,
compute on the owner machine, then commit the result and debit once; retries
recover the same paid reply. Failed/cancelled jobs release reservations, with
bounded deadlines and crash-safe settlement. Existing synchronous search needs
adapting; polling alone is insufficient. Do not charge for an offline owner or
quota error. Disclose owner-side query processing and minimize prompt retention.

Required cloud pieces are static hosting, a small trusted coordinator/ledger and
R2. Containers, cloud model APIs, Vectorize, Durable Objects and paid queue/logging
products are unnecessary in this proposed design. Owner CPU, electricity, disk,
internet reliability and backups remain real finite costs. Strict **zero cost
outside R2 everywhere**, including electricity and signing, cannot be promised.
Trusted publisher enrollment, signing and any custom domain have separate costs;
existing paid subscriptions/retained non-R2 storage need the owner's billing
review. Disabled endpoints do not cancel them. No account-wide cancellation is
proposed or authorized.

Moving vector bytes alone is insufficient: today's per-location catalog and
publication rows also grow. Free coordination needs bounded active metadata,
sealed batch manifests and trusted owner-side membership checks instead of an
unbounded duplicate corpus in D1. The exact schema and recovery transition need
implementation and measurement; the historical database's row count does not
prove it fits the Free plan. Local pending work also needs a finite disk limit
and automatic pause when the owner or coordinator cannot keep up.

## Migration sequence after discussion and approval

1. Agree on Free-only coordination, queued search and owner capacity/availability;
   keep the present cost hold intact until there is an explicit activation decision.
2. Build an outbound owner agent around existing verifier/import/search contracts,
   separate its Community catalog, and add durable job/receipt replay. Leave the
   current comparison, Gen4/protection and once-only credit guarantees intact.
3. Adapt the coordinator for Free CPU/D1 limits, small metadata batches, direct
   permitted R2 transfer, quota backpressure and queued credit reservations.
   Reuse account/privacy/paid-reply recovery evidence; rehearse migration and
   rollback on already authorized private offline copies first.
4. After account/data-transfer approval, establish only the isolated Free resources
   and scoped connections. Preserve the old data/ledger/deletion authority and
   reconcile a consistent cutoff before switching. Do not restore paid containers.
5. Run bounded real Mac/Windows Scenes/Objects/Both admission and earned-credit
   search on the chosen design; measure owner throughput, API CPU, D1 rows and R2
   operations. Quota/owner-outage tests must preserve work, credits and deletion.
6. Finish signed beginner-device acceptance and accepted-work endurance, then open
   a small invite cohort under measured caps. The intentionally stopped pilot
   does not count as an uninterrupted week. Expand only within demonstrated
   capacity; no automatic paid fallback.

**Decision requested on PR17:** choose the preferred combined option, the
R2-mailbox-only alternative, or an explicit different budget/product model. No
additional source export, model matrix, Actions run or paid test is requested
from Andrew while this decision is pending.
