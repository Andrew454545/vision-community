# Older-database Object cancellation recovery — 11 October 2026

A pinned current cancellation ledger now revokes work in an older **private
Community database copy**, including copies made before the candidate, lease or
account existed. This closes the older-D1 replay component of the
[native cancellation recovery follow-up](OBJECT_CANCELLATION_NATIVE_RECOVERY_20261011.md).
Actual provider cutover, complete independent deletion/financial reconciliation,
secrets and public Object acceptance remain open.

The offline repair validates the confirmed resource, independent ledger hash,
complete retained cancellation history, exact optional schema definitions and
candidate/lease/upload identity. It installs immutable cancellation tombstones,
expires existing cancelled leases and removes saved approval/claim authority in
one transaction. It releases only that lease's unpublished locations. Unknown
work remains a tombstone: the repair does not invent accounts, jobs or credit.
Newer empty or changed ledgers cannot remove earlier cancellations.

Accepted publications from another lease remain intact. Same-lease, unknown or
older publication conflicts require review. Exact protected-row digests inside
the transaction preserve accounts, ledger entries, paid replies, published
locations, index records and shards. Unexpected trigger side effects roll back
the repair. NUL/blob values, 64-bit integers and adjacent floating-point values
have explicit checks. Preservation does not validate the original financial
history.

Persistent SQL fences block later lease activation, candidates, location claims,
upload intents and publication under a revoked lease. The shared Scene/Object
writer also rechecks the live lease before using an existing upload intent and
after R2 acknowledgement. An expired lease cannot reuse an old intent while
cleanup is pending.

The private recovery plan includes native revocation and canonical R2 fence
targets, including owned partial bundles. The internal R2 helper writes and
reads back the permanent fence with a bounded deadline. The exact cancelled
quarantine can be fenced even when its lease is absent from the backup; other
members require an original owned intent. Arbitrary/foreign keys are refused.
R2 completion alone never certifies native cleanup.

Current-authority export merges original cancellation journals and immutable
restored tombstones, refusing conflicting events or changed recovery schema.
The v2 native exporter can revoke an independently cancelled assignment absent
from the old D1 copy. It still requires the independently pinned current deletion
and cancellation ledgers. Legacy exports without cancellation authority and the
R2-only account-deletion checker refuse these restored cancellations.

## Private operator procedure

Keep admission closed and drain writers before independently capturing/pinning
current deletion and cancellation authority. Never capture those current
ledgers from the old backup. Keep databases, ledgers, plans and logs private.

Run the existing private Node runtime with
`deploy/cloudflare/tools/object-cancellation-restore.mjs` and all these options:

```text
--backup <absolute-closed-old.sqlite> --backup-sha256 <trusted-pin>
--cancellations <absolute-fresh-independent-ledger.json> --cancellations-sha256 <trusted-pin>
--writers-stopped-at <UTC-unix-seconds> --environment <staging-or-production>
--out <new-private-directory>
```

The command creates a separate `restored.sqlite`, a pinned private cancellation
plan and `restore-report.json` last. Existing outputs and linked paths refuse;
input hashes/sidecars are checked before and after copying and repair. Failure
writes a separate report and no successful completion marker. The original
backup is unchanged.

The component supports closed backups up to 512 MiB, current ledgers up to
4 MiB/4,096 events, at most 128 intents per cancelled lease and 16,384 fence
targets. Capture freshness is under ten minutes and after the supplied writer
cutoff; replay never refreshes it. Compaction beyond these bounds is not
implemented.

Finish separately pinned current account-deletion repair and independent
financial reconciliation, native-spool revocation/erasure and actual provider
fence inventory before any cutover. This cancellation report deliberately sets
`accountDeletionReconciled`, `financialReconciled`, `liveReady` and
`productionQualified` to false. Pending native/provider cleanup stays explicit.
The existing account-only SQL import preparer still refuses the additional
Object tables; it must not be used to publish this copy. The new source helper
has no public HTTP route, automatic migration or deployment driver.

## Evidence and limits

[Pinned Windows evidence](evidence/object-cancellation-d1-recovery-20261011.json):

- **231/234 affected JavaScript checks pass**, zero failures and three existing
  Windows file-symlink privilege skips. Twenty new recovery/writer cases are
  included, with transaction rollback and exact protected-value preservation.
- **24 additional Scene pipeline checks pass**, zero skips/failures, including
  upload retries, publication, deletion races and immutable intents. This verifies
  the shared writer change on the Scene lane.
- **Five Python cancellation recovery checks pass.** Actual Node repair of an
  old hosted copy produces the same v2 authority as the independently current
  copy. The real Python restored-spool constructor revokes an old approved job
  before serving; erasure completes without another inference attempt. Original
  hosted and native backups remain unchanged.
- **24 actual local workerd/D1/R2 checks across three fresh processes** load two
  separately repaired database fixtures, including one predating the account and
  lease. Failed D1 batches roll back, late SQL and correct-payload R2 retries are
  rejected, fences survive restarts, and the unrelated published bundle remains.

Inference, identities and units are explicitly synthetic. Actual SQLite files,
Node/Python recovery, Cloudflare local storage, persisted triggers and process
restarts execute. There are no new authentic contributions or earned credits.
This is not Mac, provider disaster-recovery or full Object acceptance evidence.

Original failures are preserved. The first focused selection had three fixture
adapter errors (missing synthetic verifier binding and two R2 text-reader
assumptions); those fixtures were corrected. A subsequent new preservation guard
initially refused existing numbered `sha256` columns before any repair committed.
Its original JavaScript and walkthrough failures remain pinned; the name check
was corrected, and all final selections pass. The separate retired offline
diagnostic failure receipt remains unchanged.

No live deployment, schema mutation, private upload, Actions spending, global
installation or frozen Scene pilot/refresher change occurred. Remaining launch
work includes authentic portable Object authority and qualification/publication/
once-only credit/search, real provider/secret/deletion/financial reconciliation,
signed Windows/Mac acceptance and full accepted-work soaks. Andrew's fresh-origin
handoff request is unchanged.
