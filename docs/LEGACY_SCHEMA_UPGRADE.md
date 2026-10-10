# Preparing an older Community database for the current service

This is an offline maintainer step. Volunteers use the normal starter and never
run database commands. It prepares a new copy and a guarded SQL plan; it does
not log into Cloudflare, deploy a Worker, enable admission or change live data.

The revision checkpoint in `0004_schema_revision.sql` requires the complete
current schema. An older prototype database also needs the scene pipeline,
privacy tables/fences and additional columns. Applying the checkpoint alone
cannot install those components. Use this rehearsal to establish the required
upgrade from that database's actual schema.

From `deploy/cloudflare`, use the existing private Node.js runtime:

```text
node tools/upgrade-schema.mjs --database CLOSED_PRIVATE_COPY.sqlite --database-sha256 TRUSTED_DATABASE_SHA256 --out .private-schema-upgrade
```

The input must be a closed regular SQLite file with no WAL/journal sidecars,
at most 512 MiB, and the independently established checksum. SQL exports must
first be converted into a new private SQLite file; never supply a live database
path. Input files and output parents must have no symbolic links or directory
redirection in their ancestors. The destination must be new and its parent must exist. All generated
files are private and must remain outside Git/public releases.

For a complete Cloudflare SQL export, first authenticate the export's source,
confirm the exact Community resource pair and obtain permission for its private
destination. Record an independently pinned provenance JSON with `version: 1`,
`scope: "private-cloudflare-d1-export"`, `resource`, `completeSchemaAndData: true`,
the provider's `bookmark`, and the export's exact `bytes` and `sha256`. From the
repository root, use the existing private Python runtime:

```text
python -B -m community.d1_export --sql-export PRIVATE_EXPORT.sql --sql-sha256 TRUSTED_EXPORT_SHA256 --provenance PRIVATE_PROVENANCE.json --provenance-sha256 TRUSTED_PROVENANCE_SHA256 --out NEW_PRIVATE_CONVERSION_FOLDER
```

The converter saves the original SQL, `input.sqlite` and a final pinned report.
It limits export/database size to 512 MiB, individual statements/values to
16 MiB and conversion to 300 seconds. It accepts known application schema/data,
rejects external-file access, extensions and history-rewriting statements, and
checks integrity and foreign keys. Conversion uses one owned transaction.
Its `providerProvenanceVerified: false` is deliberate: validating a pinned JSON
does not authenticate Cloudflare or grant transfer permission. Keep the actual
provider/consent receipts independently. Failed/partial copies are preserved.

The tool runs the actual application migrations on a private copy in one
transaction. Before committing, it checks integrity, the current schema
contract, every historical column/row and autoincrement high-water values.
Fingerprints preserve integer precision, floating-point bits, blobs and text
bytes including embedded NULs. Existing accounts, credentials, credit entries,
saved maps, publications and unfinished leases must survive unchanged. The
privacy migration may intentionally requeue old `removed` cleanup jobs as
`pending`; that count is recorded separately. It does not award credits, repair
financial discrepancies or qualify a runtime.

Successful output contains:

- `upgraded.sqlite`: the completed private copy.
- `rollback.sqlite`: independent complete copy verified unchanged after the
  generated batch reaches an injected failing final statement.
- `replayed.sqlite`: independent complete copy upgraded using the generated batch.
- `upgrade.private.sql`: the data-free migration plan.
- `query-batch.private.json`: exact statement boundaries, including trigger bodies.
- `upgrade-report.private.json`: input/output/plan/schema pins, historical row
  counts/digests and the intentional cleanup count, written last.

Allow space for the original/retained SQL and all four SQLite files, plus failed attempts.
The completion report requires successful independent replay and full-copy
rollback, rather than inferring rollback from a synthetic fixture alone.

The report explicitly says `liveReady: false`. Failure preserves a redacted
failure report and the partial copy, with no completion report. A failed
migration transaction rolls back. Existing output directories cannot be replaced.
Only the known Community table families are supported; unfamiliar tables, views,
hidden columns, integrity defects or changed historical data require investigation.

The plan guards the complete source application schema, including trigger
bodies. A schema mismatch aborts before upgrade work. It contains no account or
contribution rows, but can still include operator schema metadata, so keep it
private. Provider tables and migration bookkeeping are excluded from the guard.
Preserved source SQL must match the live schema: if an SQL exporter rewrites
schema spelling, regenerate/validate against an independently read-back source;
never remove the guard to make an unexpected database pass.

Before any production rollout, stop and drain all writers and obtain a fresh
backup/rollback bookmark for the complete confirmed resource pair. The rehearsal
copy is historical evidence, not a replacement database or a current financial
source. Compare the actual live schema to the guarded source, review the plan,
and repeat the rehearsal from the fresh cutoff. Submit the entire query batch
atomically using the supported D1 batch interface. Do not split SQL on semicolons
or send individual upgrade statements: that can leave a partial migration.

Afterward read back the schema contract, row/credit/publication preservation,
privacy fences and service capabilities before reopening. Native runtime/policy
and release qualification remain separate requirements. Never downgrade to an
old writer that bypasses the new privacy protocol. Full deletion, financial,
R2 artifact and native-bundle recovery still follows [the restore guide](PRIVATE_RESTORE.md).

Validation includes synthetic late-failure and schema-mismatch rollback in
actual local workerd/D1, exact private-value preservation, deletion fences and
an offline older-schema rehearsal. These checks establish the upgrade path;
they do not establish a live migration, hosting capacity or production approval.
The [actual production-data rehearsal](PRODUCTION_DATA_REHEARSAL_20261009.md)
now passes; complete provider recovery and controlled rollout remain open.
