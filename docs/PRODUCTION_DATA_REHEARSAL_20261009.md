# Full production-data upgrade rehearsal

The account holder explicitly approved copying the complete private production
database to this laptop for recovery testing. The confirmed Community D1 export
downloaded successfully, stayed outside Git, and converted to a new closed
SQLite copy using pinned export/provenance files.

The actual copy contains **364,056 historical rows in nine tables**. Its guarded
45-statement upgrade passed, as did successful replay on an independent complete
copy and rollback after an injected failure at the final statement. Every
historical column/row, credential, balance, publication, unfinished lease and
autoincrement high-water mark survived. An independent provider readback matches
all 11 source application schema objects exactly.

All 18 stored account balances equal their ledger sums. The existing offline
financial snapshot exporter also passes on the upgraded copy. The backup has
**zero paid-search rows**: real paid-reply recovery is not established by this
copy. Synthetic paid-reply tests remain separate evidence.

The later [actual staging recovery exercise](REAL_PAID_RECOVERY_20261010.md)
restores three real paid replies, contributed R2 files and deletion archives into
local workerd, without changing this historical backup. Its corrected converter
also reproduces every historical row and schema object in this production copy.

## Verification and retained failures

- The converter selection passes 16 Windows tests without skips or failures.
- The schema upgrade/plan/revision selection passes 12 of 14 tests, with two
  explicit Windows directory-link privilege skips and no failures.
- Actual local workerd/D1 passes exact deployed-schema synthetic upgrade,
  schema-mismatch refusal, injected-failure rollback and privacy fences. This
  complements the full-data SQLite check; it is not a full-data provider restore.
- The first export expired before download; its failure remains. The first
  conversion exceeded the unchanged 300-second limit. Conversion now uses one
  owned transaction and completed in 12.375 seconds; the full-copy upgrade and
  independent replay/rollback completed in 30.484 seconds.
- Initial Windows financial path-access failures are preserved separately from
  the authorized passing export. A prior automatic review could not run because
  of usage availability; that action did not execute. The later normal approval
  succeeded.
- Simulator setup first selected an incompatible helper, then failed internally
  with the matching alpha runtime. The stable runtime refused the unchanged
  compatibility date. The matching alpha runtime passed with a shorter private
  temporary path; all earlier logs remain. No date or security check was weakened.

No live migration, database write, R2 data change, public admission or release
approval occurred. Full D1/R2/native-bundle/secret recovery, current deletion and
financial authority, real paid work, capacity and a fresh drained-writer cutoff
remain required. The historical copy cannot replace current live state.
See [operator instructions](LEGACY_SCHEMA_UPGRADE.md) and
[redacted evidence](evidence/production-data-rehearsal-20261009.json).
