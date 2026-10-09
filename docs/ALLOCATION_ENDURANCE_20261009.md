# Allocation safeguards and running endurance checks — 9 October 2026

## Contributor allocation

[PR #18](https://github.com/Andrew454545/vision-community/pull/18) supplies exact
panorama-ID exclusion, bounded export, verified publication and the
[allocation policy](CONTRIBUTOR_POOL.md). Its tools exclude indexed and reserved
locations before making contribution batches. They do not establish current
Generation 4 coverage or approve a runtime.

Both the hosted Worker and local service now refuse new assignments from the
retired full, tail and indexed catalog families, even if a database hold is
cleared. Pending rows cannot bypass retirement through the shared queue; a
missing or held registration also fails closed. Existing valid leases can
resume. The Worker checks eligibility again inside its final D1 transaction,
rolling back the entire lease on a late hold or competing claim. Status and batch
counts exclude unavailable catalogs. This requires no schema migration.

The publisher rechecks its mask, identity report, country authority and exporter
before and after the final manifest readback. Changed inputs cannot leave a
local completion marker. Exporter pipes close on success and failure; an exporter
that ignores cooperative shutdown is stopped within a bounded wait.

The replacement allocation remains unregistered while uploading. No catalog
registration, owner process, reserved queue or production bucket was modified
by this integration. Final complete-manifest, pending-row reconciliation and
cutover receipts remain required from the allocation handoff.

## Running offline endurance test

A private Windows Task Scheduler supervisor started at **08:10 UTC on 9 October**
after a successful complete preliminary cycle. Its first scheduled round stopped
at the native-stage timeout described below; no subsequent round is considered
valid. The planned run was **24 hourly rounds**, rotating **1, 2 and 4 CPU threads**.
Each round runs 127 shuffled recovery,
storage, outbox, process-ownership, Object-auditor and background-control checks,
then indexes two saved locations afresh, verifies the entire native index,
runs four native queries, verifies again and compares with the pinned Mac pair.

The preliminary cycle passed all executed checks, with one existing Windows
file-symlink permission skip. Native indexing/search/verification took
**404.781 seconds** at one thread; query hit counts were **2, 1, 1, 2**.
That timing includes initialization, verification and query work, not just
indexing. The earlier incomplete-snapshot/sandbox failure is retained separately.

The supervisor uses immutable Community `c45b218` and native `954b1b8` snapshots,
durable per-round receipts, an exclusive process lock, a sign-in/retry trigger
and fresh output for interrupted attempts. It permits at most two interruptions,
has a **26-hour deadline**, **4 GiB disk floor** and **512 MiB output ceiling**,
and its scheduler registration expires automatically. Native index/verification/
query commands retain their existing **900/120/180-second** budgets. System
available RAM and physical memory load are sampled every five seconds during
native work; this does not measure native-process peak RAM, temperature or power.

Source-inventory SHA-256:
`874bc678032be6210c199aa87d4e060b9fb80cbaae781c8be3c9bc5669f6b58e`.

The run **stopped after round 1, attempt 1**. Native processing indexed one of
the two locations and then timed out after **902.781 seconds** at one thread;
the private failure receipt is retained under the endurance run directory. It
uploads nothing and creates no accounts, contributions or credits. It repeats two distinct locations and
cannot establish broad model quality, official coverage, Mac endurance, physical
OS restart, uninterrupted thermal behavior or seven days of qualified accepted
work. The supervisor's terminal failure receipt makes later triggers no-op;
disabling the Windows task itself could not be verified in this session because
the local approval service had reached its usage limit. Sleeping or powered-off computers cannot compute. The
[five release gates](LAUNCH_PLAN.md) remain open.
