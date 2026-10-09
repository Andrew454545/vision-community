# Verify credits and paid results after restoring a backup

This is an **operator-only offline check**, not a volunteer setup step. It reads
three closed SQLite snapshots, makes no provider calls, and changes no balance,
credential, publication or database. It supplies the accounting comparison that
must pass before a restored service can reopen.

The snapshots have distinct roles:

- **Backup:** the historical database being restored.
- **Current:** independently trusted, complete financial state after stopping
  and draining every writer. Preserve it outside the database being rolled back.
- **Recovered:** the proposed restored database after reconciling post-backup
  activity and applying current deletion history.

The recovered database cannot generate its own current authority. If the
independent financial state has been lost, this check cannot reconstruct it
from the backup. Keep the service closed and investigate; an empty ledger or
a new timestamp is not evidence that nobody earned or spent credit.

## Prepare the private authority

Record the actual confirmed Community resource, writer-stop time, source export
provenance and independent hashes in restricted operator storage. The small
authority JSON has this shape; replace placeholders with independently obtained
values:

```json
{
  "version": 1,
  "scope": "vision-community-credit-recovery",
  "resource": {
    "accountId": "CONFIRMED_ACCOUNT_ID",
    "databaseId": "CONFIRMED_DATABASE_ID",
    "bucket": "CONFIRMED_BUCKET"
  },
  "capturedAt": 0,
  "writersStopped": true,
  "backupSha256": "TRUSTED_BACKUP_SHA256",
  "currentSha256": "TRUSTED_CURRENT_SHA256"
}
```

`capturedAt` and the command's `--authority-not-before` are Unix seconds. Record
the authority's own SHA-256 separately. A checksum and `writersStopped: true`
do not independently prove provider identity or that writers were stopped;
the operator must establish those facts. Only the exact resource profiles in
`deploy/cloudflare/tools/account-restore.mjs` are accepted. Do not substitute
production identifiers for a staging export or vice versa.

Use self-contained SQLite files with no WAL, SHM or journal sidecars. Final
input files cannot be symlinks. Keep raw exports, authority, report and saved
searches private. Do not commit credentials, account IDs or search replies.

## Run the check

From the repository root with the existing private Node 22 runtime:

```text
node deploy/cloudflare/tools/credit-recovery.mjs --environment staging --backup PRIVATE_BACKUP.sqlite --current PRIVATE_CURRENT.sqlite --recovered PRIVATE_RECOVERED.sqlite --authority PRIVATE_AUTHORITY.json --authority-sha256 TRUSTED_AUTHORITY_SHA256 --recovered-sha256 TRUSTED_RECOVERED_SHA256 --authority-not-before WRITER_STOP_UNIX_SECONDS --out NEW_PRIVATE_REPORT_DIRECTORY
```

Use `production` only for independently confirmed production snapshots. The
destination must be new and its parent must exist. The tool opens databases
read-only and writes only a private aggregate completion or failure report.
All inputs are checked again before the completion marker is written.

It verifies:

- Every historical ledger entry, credited publication and deletion receipt
  survives unchanged. New ledger IDs are above the backup's high-water mark.
- Every account balance equals its full ledger; duplicate references, invalid
  amounts, negative running balances and unsupported credit reasons fail.
- Every work award names a submitted lease, the correct account/lane and the
  exact published assignment count. One location cannot earn credit twice.
- Every live saved paid result has its debit, original idempotency key, request
  identity and exact response bytes. Paid-result replay can survive reopening
  without another charge. Deleted accounts retain debit history and no private
  search results.
- The recovered account/credential state, financial rows, credited assignments,
  publication metadata and saved results match the independent current state.
  This detects post-backup work or spending omitted from a restored ledger and
  rollback of a rotated session/recovery hash.

The completion report has `accountingCopyVerified: true` but deliberately keeps
`creditRecoveryVerified`, `providerRecoveryVerified`, `liveReady` and
`productionQualified` **false**. A local comparison cannot certify the live
restore, independently recover missing financial authority or reopen service.
It does not verify native inference, pricing policy, actual R2 bytes, provider
retention, signing or credential rotation after a compromise. Run the separate
[storage](PRIVATE_RESTORE.md) and [privacy-object](PRIVACY_STORAGE_RECOVERY.md)
checks and complete a provider readback/replay exercise before reopening.

Unknown legacy credit reasons, credits without matching lease/publication
history, unjournaled balances and missing modern deletion columns fail closed.
Investigate and migrate those histories without discarding records. The tool
does not silently normalize a legacy production export into a passing result.
Limits: 512 MiB per database, 64 KiB authority, one million rows per financial
table, and 100,000 publications. Larger restores require another bounded plan.

## Recorded validation

The focused suite exercises the actual search settlement/replay and account
deletion functions on explicitly synthetic SQLite publications. It includes
post-backup work/debits, repeated requests after reopening, deletion of an
existing/new account, lost or duplicate awards, changed saved replies,
credential rollback, consistently rewritten history, stale/mixed authority,
bad pins, sidecars, symlinks, late input changes and the command-line entrypoint.
This is local component evidence, not accepted native work or a live restore.

On 9 October 2026, Apple-silicon macOS 27.0.1 / Node 22.20.0 completed all
**26 focused checks** and **414 complete service checks**, with zero skips.
The first restricted full-suite attempt passed 413 checks and failed the
existing localhost HTTP fixture with `listen EPERM`; that log is preserved.
The unchanged suite passed with local networking allowed. No Actions job,
Cloudflare operation, native indexing or live credit was created. Aggregate
evidence is in [the validation receipt](evidence/credit-recovery-20261009.json).

The integrated Windows x64 / Node 24.19.0 service suite subsequently completed
**440 checks: 437 passed, three file-symlink privilege skips, zero failures**.
It includes all 26 new accounting checks; the new file-symlink case is one of
those skips. This is a separate platform integration result, with its retained
log checksum in [the Windows receipt](evidence/credit-recovery-windows-integration-20261009.json).
No production export, provider write or GitHub Actions run was performed.
