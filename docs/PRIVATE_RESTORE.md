# Reapplying account deletions after a restore

This is an **operator-only, offline rehearsal tool**, not a volunteer command or
an automatic Cloudflare restore. It prepares a new private SQLite copy, leaves
the original backup unchanged and never contacts Cloudflare, R2 or a user.
Its completion report deliberately says `liveReady: false`.

Restoring an old database can restore revoked credentials and saved searches.
Before any restored database becomes accessible, reapply every deletion recorded
after the backup. The deletion record must come from a separate, current trusted
source; copying receipts from the same old backup cannot establish completeness.

Cloudflare's [D1 Time Travel documentation](https://developers.cloudflare.com/d1/reference/time-travel/)
describes an in-place restore that overwrites the database and cancels in-flight
queries. Its retention window depends on the plan. An offline rehearsal does not
perform that operation or verify the account's actual backup retention settings.

## Required inputs

1. Stop all Community writers and keep public access closed during a restore.
   Record the stop time. Preserve the current database/export and rollback
   evidence before replacing anything.
2. Obtain the complete latest deletion ledger, independently of the old backup.
   Establish its SHA-256 through trusted operator configuration. Confirm its
   account/database identity against the Community configuration. Keep it private:
   it contains pseudonymous account IDs and secret deletion receipt keys.
3. Supply a closed, self-contained SQLite backup with an independently established
   SHA-256. The tool rejects journal/WAL sidecars and incompatible schemas. It
   supports the existing scene-pipeline/work-queue schema, including catalog
   assignment columns; it is not a general migration tool for arbitrary old
   application versions. A checksum pin establishes integrity, not provenance:
   the operator must verify which resource produced the backup.
4. Set `--deletions-not-before` to the writer-stop time in Unix seconds. A ledger
   exported earlier, or claiming a future time, is rejected. This check cannot
   detect an operator's incorrect cutoff or an incomplete but newly dated file.
   Stop new deletions too and verify complete source counts; do not just refresh
   the timestamp of an old export.

The deletion envelope is:

```json
{
  "version": 1,
  "scope": "vision-community-account-deletions",
  "resource": {
    "accountId": "272760294910ef0b246980278aeb36e2",
    "databaseId": "ed4705fa-1190-41fa-86a0-02d755db1b2a",
    "bucket": "vision-community"
  },
  "exportedAt": 0,
  "receipts": [{
    "accountId": "32_LOWERCASE_HEX_DIGITS",
    "requestKey": "64_LOWERCASE_HEX_DIGITS",
    "deletedAt": 0,
    "unitsForfeited": 0
  }]
}
```

This is a schema illustration, not usable restore evidence. The
`DELETION_EXPORT_SQL` constant in `tools/account-restore.mjs` joins current
account tombstones to their receipts. Every deleted account must have a matching
receipt date, and every receipt must belong to a deleted account. The exported
rows' `receiptDeletedAt` is checked against `deletedAt`, then omitted from the
envelope. `exportDeletionLedger` performs this validation in one read transaction
for a current, closed local rehearsal/copy. A live export must enforce the same
complete-source checks under the writer pause. Missing records are a reason to
stop, not to infer or create deletion approvals.

## Rehearsal command

Use an existing private Node.js 24 runtime; this installs nothing. From the
repository's `deploy/cloudflare` directory:

```text
node tools/account-restore.mjs --backup community-backup.sqlite --backup-sha256 TRUSTED_BACKUP_SHA256 --deletions account-deletions.private.json --deletions-sha256 TRUSTED_DELETION_SHA256 --deletions-not-before WRITER_STOP_UNIX_SECONDS --out .private-restore
```

The destination must be new and its parent must exist. The tool:

- Checks both input pins, the current deletion ledger's resource/freshness,
  duplicate IDs/receipt keys, database integrity and schema.
- Repairs a new copy in one transaction, installs the current privacy fences,
  revokes credentials, closes restored balances, removes private search results,
  expires qualifications and releases unfinished work.
- Preserves the actual latest deletion receipt's date and forfeiture amount.
  A separate ledger entry closes the balance present in the old backup; that
  amount can differ from the balance forfeited at the original deletion.
- Retains verified contributions and their opaque contributor identifiers.
  Accounts created and deleted after the backup receive an inactive tombstone.
  Existing deletion history cannot be omitted or silently changed.
- Requeues unpublished candidate blobs and journaled scene uploads, including
  writes without a candidate, for the bounded privacy-fence cleanup routine.
  Previously `fenced` jobs are requeued because restoring storage is a separate
  operation. Published final indexes are excluded. Conflicting cleanup ownership
  rolls the repair back. This tool does not contact or change any R2 object;
  path, lease ownership and publication still require the live cleanup checks.
- Uses secure deletion and compacts the new SQLite copy to remove old
  credential/search values from unused pages. The original backup, provider
  copies, receipt files and external downloads remain private retained data.
- Flushes the repaired database and writes `restore-report.json` last, containing
  input/output hashes and aggregate counts. Failure preserves partial files and
  a redacted `failure-report.json`, without a completion report. Never expose a
  failed or unreviewed copy. Completed destinations cannot be overwritten.

Production is the default resource profile. For the isolated Community test
database, add `--environment staging`; its ledger and report must name D1
`17043cb7-5dab-4a6f-84ca-19ae1c14cc05` and `vision-community-staging`.
The two confirmed mappings are fixed. Mixed resources, arbitrary environment
names and production receipts supplied to a staging repair are rejected.
The profile does not establish backup provenance: still verify its source.

Limits: 512 MiB per backup, 4 MiB per deletion ledger and 10,000 receipts. Larger
corpora require a separately reviewed restore approach. Store all outputs in a
private operator folder; do not commit, publish or send them as calibration
results. SQLite backups, `.private-restore/` and the illustrated private receipt
filename are ignored by Git. Operators must still verify every chosen path.

## Before reopening a live service

Cloudflare [imports and exports D1 using SQL](https://developers.cloudflare.com/d1/best-practices/import-export-data/);
this tool's raw SQLite copy is not a direct D1 import. Test a compatible export,
import and privacy migration against an isolated staging database first. Check
all tombstones, revoked sessions/recovery, private-search removal, accounting,
retained publications, foreign keys, cleanup jobs and late-write rejection
before exposing the restored service. Keep the rollback bookmark/export.

Preserve permanent R2 privacy markers and scene write intents across restore.
Stop/drain old unconditional writers and retain only compatible create-only
writers before reopening. Removing a marker, restoring private bytes over it,
or rolling back to an incompatible writer can permit resurrection. Verify all
requeued jobs against staging R2 before claiming private payload cleanup.

The tool does not reconcile credits/searches earned or spent by other accounts
after the backup, prevent replay against a restored ledger, restore R2 indexes,
rotate other credentials, inventory orphan storage or establish provider
retention. Those remain disaster-recovery requirements. A fresh complete deletion
ledger needs durable, restricted storage outside the database being rolled back.
The [private deletion archive](ACCOUNT_PRIVACY.md) is deployed and tested in
staging; obtain a fresh complete inventory plus any pending database receipts
while writers are stopped. This utility does not retrieve that inventory or
establish completeness, and does not implement the live export/import process.

Seventeen synthetic SQLite tests cover revocation, repeated repair, preserved
contributions, changed/missing history, new-account tombstones, incorrect pins,
freshness, rollback, candidate/journal cleanup ownership, journaled uploads
without candidates, private-byte removal, explicit staging admission, rejection
of mixed resource profiles and both CLI profiles. They
are offline privacy-repair evidence, not a live backup/restore acceptance test.
