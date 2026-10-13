# Low-cost contribution and search plan

**Recommendation:** a free website and small credit coordinator, R2 for bulk
files, and one existing trusted owner computer for verification and search.
Target **$0 recurring cloud hosting outside R2**. Keep the user's additional
$10/month allowance as contingency, not an automatic paid fallback.

On 13 October the user confirmed **one or two searches per day across the entire
application**, not per account. They expect millions of contributed locations,
roughly $10/month for R2, and at most $10/month outside R2. These are product and
budget requirements, not measured capacity or permission to activate services.
Andrew's [operational hold](COST_STOP_20261012.md) remains intact. This plan
refines the [12 October recommendation](COST_OPTIONS_20261012.md); no cloud
account was inspected, moved, deployed or restarted to prepare it.

## What a user does

1. Install the Windows or Mac application, save their private recovery code, and
   choose Scenes, Objects or Both. No GitHub account or cloud credentials.
2. Choose a processing schedule, such as Medium by day and Maximum from midnight
   to 6 a.m. The installed background helper checkpoints progress and resumes
   after login/restart. A sleeping or powered-off computer cannot process; work
   resumes when it is running. Maximum uses only qualified parallel profiles.
3. The application obtains assigned work, processes it locally and saves completed
   results until an upload is acknowledged. Temporary outages do not discard work.
4. Independently accepted, unique contributions add banked search credit. Pending
   uploads and duplicates do not earn credit; replay cannot earn it twice.
5. On the website, the user sees a quoted search price and submits a request.
   The owner computer searches the contributed pool. Waiting, failed or cancelled
   searches spend nothing; a completed search is charged once. Closing the page
   does not lose a paid result or cause another charge on recovery.

Use the existing anonymous account and credit design. Do not introduce a cash
payment system, paid search API or public download of the complete index. Once
someone has the full index, one-credit-per-search cannot reliably be enforced.
Andrew's private indexes are comparison references, not Community search data.

## Where the work lives

| Component | Location | Purpose |
|---|---|---|
| Website, instructions and downloads page | Free static hosting | Simple installation, local work status and recoverable search. Only API paths invoke dynamic code. |
| Accounts, balances, reservations and active jobs | Small Workers Free/D1 coordinator | Authentication and once-only financial settlement; no models or full location catalog. |
| Pending uploads, accepted indexes and recovery archives | Confirmed Community R2 resources | Bulk immutable files, bounded quarantine and retained recovery evidence. |
| Numerical verification, eligibility, deduplication and import | Trusted owner computer | Use pinned VISION models/runtime and current Scene/protected-source authority; publish only qualified contributions. |
| Contributor-only search catalog and query execution | Same owner computer, separate Community folder | Keep an incremental local SSD mirror; run the reference-compatible search engine. |

The owner agent makes outbound authenticated connections only. No public home
address, inbound port or cloud model container is needed. Queries wait visibly
when that computer is offline. A replacement owner computer can take over from
approved snapshots and current financial/deletion authority; an old backup alone
must never restore erased account access or spend credit twice.

The owner machine is a finite resource, not free unlimited compute. Electricity,
local disk, internet and operator availability still matter. Trusted publisher
enrollment/signing and an optional domain are separate costs; this is a recurring
cloud-hosting target, not a promise that every project expense is free.

## Make millions of locations affordable

Store data in sealed batches instead of one cloud database row and many cloud
objects per location. Keep the exact reference feature bytes and their provenance;
do not introduce a different model or lossy representation to save storage.
Small native checkpoints and larger storage batches are different things: retain
the current finite Object inference units, then aggregate their accepted outputs.

The coordinator retains compact batch identities/roots, active queue state and
financial authority. Detailed memberships, deduplication indexes and feature
bytes live in R2 and the owner's local catalog. Historical receipts and exact
paid replies can move to private archives only with authenticated retrieval,
independent integrity pins and a durable once-only settlement reference. Account
and ledger growth still need finite bounds; sealed batches do not make D1 infinite.

Search the local mirror, loading new accepted batches incrementally. Do not
download or rebuild the entire pool for every query. Extend sealed membership
and native-compatible search segments with exact global ordering/deduplication
before claiming million-location capacity. The current optional Scene seal caps
one snapshot at 100,000 locations, and Object search visits bounded batches;
today's source is not evidence of million-location query performance.

Record sizes from source, using decimal GB:

| Locations | Scene feature records only |
|---|---:|
| 1 million | 3.08 GB |
| 10 million | 30.8 GB |
| 100 million | 308 GB |

[`four_view.py`](../community/four_view.py) fixes one Scene record at 3,080 bytes.
Object size varies with sparse detections and metadata; its semantic lane alone
is 16 x 144 = 2,304 bytes/location, not its complete size. Measure real sealed
Object bundles rather than inventing a fixed all-in bytes/location figure.
[`object_index.py`](../community/object_index.py) defines those record sizes.

R2 Standard storage is $0.015/GB-month, with request charges and an included
allowance. Ten million Scene records alone therefore cost roughly $0.47/month
before the allowance, after storage rounding. Metadata, Objects, quarantine,
models, operations and extra retained copies add to that. A $10 storage budget
buys roughly 650 GB of billable storage before those additions; it cannot fund
unbounded growth. Retain derived indexes rather than a permanent image archive,
subject to the imagery provider's permitted use. [R2 pricing](https://developers.cloudflare.com/r2/pricing/).

## Budget and capacity controls

- Use genuinely **Workers Free** coordination. If the current shared account must
  stay Paid, an approved isolated Free account is the migration target; do not
  downgrade unrelated services or assume R2 bindings work across accounts.
  Free includes 100,000 dynamic requests/day and 10 ms CPU/request. Static asset
  delivery is free/unlimited. [Workers pricing](https://developers.cloudflare.com/workers/platform/pricing/).
- D1 Free includes 100,000 row writes/day, five million reads/day and 5 GB total.
  Scanned rows and index updates count. A reached quota stops service rather than
  adding paid capacity. Batch metadata, indexed queries and substantial headroom
  are necessary even with two searches/day. [D1 pricing](https://developers.cloudflare.com/d1/platform/pricing/).
- Budget contribution traffic separately from searches. Grant finite assignment
  and upload permits only while the verifier, quarantine and disk can keep up.
  Local progress needs no cloud polling per location. Use aggregate status and
  slower idle retries. Pause new work before storage or API headroom runs out;
  completed work stays recoverable, with no invented acceptance or credit.
- Use short-lived exact-key R2 transfer URLs with scoped credentials retained
  by the trusted operator. A signed URL is reusable until expiry and is not a
  one-use or spending guarantee. Bound permits, pending storage and retention;
  stop issuing new permits near the R2 target. R2 remains metered, so a $10 target
  is not a provider-enforced invoice cap. [Presigned URLs](https://developers.cloudflare.com/r2/api/s3/presigned-urls/).
- Treat two searches/day as the initial demand envelope. If a service limit is
  needed, advertise it before reserving credit, with fair admission and a visible
  retry time. Do not accept days of waiting work behind the existing one-hour
  deadline or silently spend/recreate expired requests. Do not change the user's
  expected use into an undisclosed permanent two-search global restriction.
- Do not add Containers, managed vector databases, paid model APIs or always-on
  rented search hardware. Workers Paid starts at $5/month but meters overages;
  its base fee is not a $10 bill ceiling. Consider it only after an explicit
  revised budget decision, if measured Free limits block the thin coordinator.

**Verification may be the bottleneck.** Qualification establishes Mac/PC
numerical parity on identical inputs; it does not prove every future upload.
Keep independent trusted submission checks for the initial bounded release.
They can repeat inference and limit how many contributors we can accept. No human
object labelling is needed. Objects still require current official Google Gen4,
real Scene membership and protected-source authority. Later sampled verification
would be a deliberate change in fraud/quality guarantees, not a free substitute
for verifying every accepted record. No such relaxation is made by this plan.

## Execution order and completion evidence

1. **Finish the thin offline data path.** Reuse the implemented queued search,
   owner Object delivery/retirement and Scene membership components. Complete
   owner cancellation/deletion, trusted assignments, verification/import and
   sealed batch credit/membership. Show one batch can be accepted once, imported
   and searched without an unbounded per-location D1 catalog. Replayed delivery
   and deletion must preserve the authoritative ledger. No new cloud service.
2. **Finish bounded recovery and scale plumbing.** Retain private paid replies,
   reservations, acceptance receipts and deletion authority through archival,
   compaction and rollback. Extend catalog segmentation beyond today's small
   limits without changing scores. Use finite local fixtures for these changes,
   not repeated unrelated audits or unapproved model/provider runs.
3. **Obtain the one-time activation decision.** The operator confirms the existing
   trusted computer, scoped Community R2 access and actual Free-account path.
   Approve only the specific required resource/data transfers and restart scope;
   existing consent for a private database rehearsal is not cloud migration
   consent. Keep paid compute and Actions off. No new source export is needed.
4. **Prove one complete real cycle on each supported platform.** Same-input
   numerical qualification, accepted Scenes/Objects/Both, unique earned credit,
   online search and paid-result recovery. Measure API CPU/rows, R2 operations,
   bytes per accepted location, owner verification locations/hour, query time
   and backlog. Set initial contributor/storage caps from those measurements.
5. **Finish release acceptance and a bounded rollout.** Use the recruited clean
   Windows/Mac testers and legitimate signing identities. Run the required
   accepted-work endurance and recover a stopped owner/coordinator without
   losing contributions or credits. Open a small invite cohort only when the
   [five launch gates](PRODUCTION_ACCEPTANCE.md) have evidence, then expand
   within measured capacity. Millions of stored locations are not a prerequisite
   for opening the first cohort.

This is a focused architecture and delivery plan, not another audit program.
Some queue/transport components already exist; bounded metadata/import and
actual activation remain the main engineering transition. A seven-day accepted-
work check still takes seven elapsed days after its real prerequisites pass.
No completion date or production readiness is claimed from arithmetic or source
fixtures, and the intentionally stopped Scene pilot does not count as that pass.

Preparation checks on Windows verified the record constants, all three Scene
storage calculations, the rounded gross R2 example and 28 local document links.
Git whitespace checks passed. This was documentation-only work: no inference,
benchmark, cloud read, deployment, task change or Actions run was performed.
