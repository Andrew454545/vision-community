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
   Set `RESTORE_MAINTENANCE=1` in operator deployment configuration: all API
   requests return a retryable `service_maintenance` response before database
   access, and the scheduled handler stops. The guide stays available. Invalid
   configured values also stay closed; absent or `0` resumes normal operation.
   This does not cancel earlier requests, other services, external API writers
   or an older deployed version: stop and drain those separately before backup
   or restore. Verify the closed API and recorded writer-stop time first.
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

## Checking banked credits and paid-search history

Before preparing an import, compare the repaired copy with a **separately
trusted current financial snapshot**, captured after every writer has stopped
and drained. A privacy repair alone cannot recover earnings or paid searches
that happened after its old backup. Do not use that backup as the current source.
Establish the current source's complete resource identity and SHA-256 independently.

From the repository folder, using its existing private Python runtime:

```text
python -m community.financial_restore export --database CLOSED_CURRENT_SQLITE --database-sha256 TRUSTED_CURRENT_SHA256 --out .private-financial-source
python -m community.financial_restore check --repaired-dir .private-restore --report-sha256 TRUSTED_RESTORE_REPORT_SHA256 --snapshot .private-financial-source/financial-snapshot.private.json --snapshot-sha256 TRUSTED_SNAPSHOT_SHA256 --writers-stopped-at WRITER_STOP_UNIX_SECONDS --out .private-financial-check
```

Add `--environment staging` to **both** commands for the confirmed test resource.
These offline commands do not fetch a database, import SQL, change balances or
grant credit. Each destination must be new. Inputs must be closed, regular files;
database and snapshot pins, resource identity, row limits and writer-stop cutoff
are checked. A checksum and a fresh timestamp cannot prove source completeness.

The comparison requires every account and its banked balance to match. Active
accounts must also have identical earnings/debit history and identical saved
search IDs, request keys, query fingerprints and exact responses. Search receipts
must pair with a debit; balances must equal their ledger totals. A same-balance
history change, missing account or missing paid result stops the check. Deleted
accounts must retain the same deletion date, zero balance and no saved searches;
their historical ledger hashes are excluded because privacy repair can add a
different balancing closure. Separate deletion-ledger checks remain required.

Mismatch or interruption preserves a redacted failure report and no completion
marker. A passing `financial-report.json` states
`financialStateMatchesTrustedCutoff: true`, **`liveReady: false`** and
**`creditRecoveryVerified: false`**. It proves equality of the offline copies at
the trusted cutoff; it does not replay lost events, verify live retry behavior,
approve credited publications or complete disaster recovery. Do not reopen on a
mismatch or reconstruct credits from guesses. Preserve or recover a complete
financial source first, then rehearse the actual service import and replay.

The private snapshot contains opaque account IDs and history hashes, without
credentials, raw prompts, request keys or ranked responses. Its input SQLite
copy remains sensitive. Keep both private and out of Git. Limits: 512 MiB per
database, 32 MiB per snapshot, 100,000 accounts and 1,000,000 ledger/search rows.

A persisted synthetic command-line rehearsal added 16 earned units and a
100,000-unit paid search after an old backup. The old copy retained 100,016
units; the complete current copy had 32 units and the saved paid result. The
checker rejected the old copy and preserved its failure, then accepted only
the matching current copy, with live approval still false. Seventeen regression
cases also exercise equal-balance history changes, missing debit/result pairs,
changed replay keys/responses, new accounts, deletion closures, cutoff/resource
and input changes, and interruption. No real credits or provider data changed.

## Before reopening a live service

Cloudflare [imports and exports D1 using SQL](https://developers.cloudflare.com/d1/best-practices/import-export-data/);
this tool's raw SQLite copy is not a direct D1 import. Test a compatible export,
import and privacy migration against an isolated staging database first. Check
all tombstones, revoked sessions/recovery, private-search removal, accounting,
retained publications, foreign keys, cleanup jobs and late-write rejection
before exposing the restored service. Keep the rollback bookmark/export.

Prepare private SQL from a completed, pinned repair with the same Node runtime:

```text
node tools/account-restore-sql.mjs --repaired-dir .private-restore --report-sha256 TRUSTED_RESTORE_REPORT_SHA256 --out .private-d1-import
```

Add `--environment staging` for the isolated test resource. The report pin is
the SHA-256 of `restore-report.json`; its database pin is checked too. This tool
does not connect to Cloudflare. It creates replacement SQL and an ordered query
batch in a new private directory, verifies a local round trip and writes
`sql-report.json` last. It rejects open databases, changed pins/resource mappings,
unknown application tables, changed privacy fences and unrepaired private searches.
Keep partial files and the redacted failure report if preparation fails.

**The generated SQL replaces all Community application tables.** It must never
be submitted to an accessible database. Confirm the intended resource, complete
current deletion source, stopped/drained writers and rollback export before any
operator import. Keep the service closed until every post-import check passes.
All tables are created before rows; historical ledger rows are inserted before
the current privacy fences. Automatic-ID high-water marks are retained. Do not
split SQL on semicolons: triggers and saved text can contain them. The private
`query-batch.private.json` preserves exact statements for the D1 query batch API.
Submit its entire batch together; an actual local workerd test verifies that a
failed replacement rolls back its table drops and inserted rows.

Preparation limits are 16 MiB of SQL, 10,000 statements and 100,000 bytes per
statement. Larger datasets need a separately tested import process. These limits
do not establish hosted size, latency or cost budgets. The original database is
read-only; private SQL, query batches and round-trip copies remain sensitive.
`liveReady: false` still requires independent live validation and operator review.

## Isolated live rehearsal: 2026-10-02

Only staging D1 `17043cb7-5dab-4a6f-84ca-19ae1c14cc05` and R2
`vision-community-staging` were used. An older backup contained two synthetic
accounts. After deleting one, all seven independent private R2 receipt preview
checksums matched the frozen current database and archive metadata. The repaired
older backup kept the deleted account revoked, removed its private saved search
and closed its restored 20-unit balance. The other account kept its 40 units and
saved search. Production was unchanged.

Cloudflare's bulk importer twice returned `D1_RESET_DO`; both failure reports,
original exports and rollback bookmarks were preserved privately. The supported
query batch API then successfully imported all 103 prepared statements while
maintenance remained enabled. Live foreign-key checks and both account
reactivation/late-search fences passed. After reopening, old session and recovery
credentials failed, exact deletion replay returned the original forfeiture and
the retained account still worked. Both fixtures were subsequently deleted:
eight revoked accounts, eight receipts/archives and zero saved searches remained.
All 13 website assets and privacy headers matched after reopening.

This is a small account-deletion restore rehearsal. It does not restore R2
contribution objects, reconcile unrelated activity after a backup, verify provider
retention or satisfy complete production disaster recovery. Raw backups, receipt
keys, SQL and credentials remain private and are not included in Git.

## Checking downloaded storage before reopening

An offline storage checker verifies a completed, checksum-pinned privacy repair
against a downloaded private cache. It changes no database, bucket or credits.
From the repository folder, using its private Python runtime:

```text
python -m community.storage_restore --repaired-dir .private-restore --report-sha256 TRUSTED_RESTORE_REPORT_SHA256 --artifact-cache .private-storage-cache --out .private-storage-check
```

Add `--environment staging` for the confirmed staging database and bucket.
The report and database pins must match that complete resource pair. Store
downloads in a private cache: scene files use `SHA256(R2_KEY).i8`, catalog files
use `SHA256(R2_KEY).tsv`, and object bundles use a `SHA256(R2_PREFIX)` directory
with their original manifest, TSV and binary filenames. These hashes are of the
UTF-8 key labels, not the file contents. The tool does not download files.

Every published database row must name a retained contributor and matching
location/publication digests. Scene files must contain exactly the published
records, including duplicate-record counts. Object bundles retain structural,
pose and trusted official Gen4 receipt checks. Every queue catalog is checked
against its recorded size and checksum. Missing, corrupt, changed or linked
inputs stop the check; failed attempts preserve a redacted report. The inputs
and each downloaded file are checked again before the completion report is
written. Existing output directories cannot be overwritten.

The successful report says `liveReady: false`, `inferenceApproved: false` and
`creditRecoveryVerified: false`. It verifies the local downloaded copy, not a
completed R2 upload or inference approval. It does not cover privacy markers,
deletion archives, hosted sealed bundles, retired legacy segments, orphan
objects or account/credit activity after the backup. Unsupported legacy
publication records are a failure to investigate; never omit them to obtain a
passing result. The original repair and SQL checks remain required. Keep the
private input database and checksum receipts out of Git. Limits are 512 MiB per
database, 128 MiB per catalog, 100,000 publications, 200,000 checked files and
16 GiB total checked bytes. Larger restores need a reviewed approach.

## Remaining recovery requirements

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
