# Object cancellation SQL recovery — 11 October 2026

The repaired Object database can now be converted into a bounded, verified D1
query batch without losing cancellation fences, saved retry/failure history,
accepted records or banked fixture units. Actual local D1 imports, transaction
rollback, repeated import and three fresh processes pass. This closes the offline
SQL preparation step after [older-D1 cancellation repair](OBJECT_CANCELLATION_D1_RECOVERY_20261011.md);
live provider cutover and the other launch gates remain open.

## What changed

`deploy/cloudflare/tools/object-cancellation-restore-sql.mjs` requires the pinned
repair report, exact repaired database, its private plan and the independently
current complete cancellation ledger. It checks the original drained-writer
cutoff and freshness again at completion. Preparation time consumes the same
ten-minute authority window; it never creates a newer authority timestamp.

The source schema must match the actual canonical base and optional Object
dispatch, cancellation and restore schemas, including exact guard literals and
revision rows. Complete saved retry schema/history is supported when present;
unknown or partial schema is refused. Independently reapplying the pinned current
ledger to another private copy must preserve every row and reproduce the exact
plan before SQL is emitted. Missing current cancellations, revived claims,
changed plans, changed guards and unknown schema cannot produce a success receipt.

All tables are created before historical rows are copied, and fences are installed
after copying. Foreign-key dependents are dropped first. Exact high-water values
are retained without changing unrelated provider-owned sequences. The generated
batch must run as **one D1 transaction**, never as separate statements. Its
successful offline round trip includes all application rows and cancellation
tombstones, even when the backup predates the account and lease.

The shared SQLite literal exporter also fixes an existing account-recovery bug:
SQLite `quote(REAL)` could round saved coordinates, while the old comparison used
the same rounded representation on both sides. Export now uses SQLite's precise
floating-point formatting, with explicit assertions against the original numeric
values. Text containing NULs, blobs and integers larger than JavaScript's exact
number range remain exact. Nonfinite values, oversized rows/SQL, linked inputs,
open backup sidecars, incorrect pins and stale authority are refused. Outputs are
create-only and failures leave a redacted report without a success marker.

## Private operator preparation

Use the existing private Node runtime, a new private output folder and the exact
same independently current ledger used for the completed cancellation repair:

```text
node deploy/cloudflare/tools/object-cancellation-restore-sql.mjs --repaired-dir PRIVATE_REPAIR_FOLDER --report-sha256 TRUSTED_REPAIR_REPORT_SHA256 --cancellations PRIVATE_CURRENT_CANCELLATION_LEDGER --cancellations-sha256 TRUSTED_LEDGER_SHA256 --writers-stopped-at ORIGINAL_CUTOFF_SECONDS --environment staging --out NEW_PRIVATE_SQL_FOLDER
```

This command contacts no provider and executes no live import. Private SQL,
batches and database copies contain sensitive data and stay out of GitHub. The
aggregate `sql-report.json` is written last and pins SQL, batch, schema and state.
It explicitly retains pending native/R2 cleanup, destination-authority requirements,
current account-deletion requirements, `financialReconciled:false`,
`accountDeletionReconciled:false`, `liveReady:false` and `productionQualified:false`.

**Do not apply this artifact to a live database.** Complete independent current
deletion/financial reconciliation, drained destination authority, native/provider
fences and secret recovery are still required. The account-only preparer continues
to refuse Object tables; its guard was not weakened. No automatic importer, public
route, qualification or contribution flag was added.

## Verification and preserved limits

[Pinned Windows evidence](evidence/object-cancellation-sql-recovery-20261011.json):

- **265/269 affected JavaScript checks pass**, zero failures and four Windows
  file-symlink privilege skips. Twenty-five new Object SQL cases include guard
  tampering, current-authority omission, exact values, preserved retry history,
  freshness expiry during preparation and redacted command output.
- **37 actual local workerd/D1/R2 checks across three fresh processes** use SQL
  from the new production-source preparer. Imports into empty and populated local
  destinations pass. Injected final-statement failures restore the entire prior
  state; repeated imports add no fixture units or ledger rows. Provider-owned data,
  exact coordinates, NUL/blob values and 64-bit high-water values survive restart.
  Cancelled native approvals remain revoked, late SQL/R2 writes remain blocked,
  and unrelated published bundles remain intact.

The first expanded restart walkthrough incorrectly expected zero accounts after
the existing late-upload fixture deliberately registered a new account. That
original failure is preserved. The corrected assertion checks the real distinction:
repair creates no account; subsequent registration earns zero units and cannot
revive the revoked lease. The final new run passes; the failure was not overwritten.

Identities, inference and units are explicitly synthetic. No genuine Object
acceptance, earned-credit search, Mac execution, provider disaster recovery or
production readiness is claimed. There was no live deployment, private upload,
Actions run, global installation or frozen Scene pilot/refresher change. Andrew's
fresh-origin handoff remains pending without a new source-side request.

References: [D1 batch transaction behavior](https://developers.cloudflare.com/d1/worker-api/d1-database/#batch)
and [SQLite precise floating-point formatting](https://sqlite.org/printf.html).
