# Check privacy objects after storage recovery

This is an offline operator check. It reads private copies and cached object
bytes, makes no Cloudflare calls and changes no live database or bucket. It
does not restore contributions, native bundles, secrets or search credits. A
successful report always has `liveReady: false` and `productionQualified: false`.

A database restore alone can resurrect a deleted account's private artifacts.
Use this check with [account deletion recovery](PRIVATE_RESTORE.md) to verify
that the independent deletion archives and permanent privacy fences survive
storage recovery. Published contributions remain retained.

## 1. Preserve a current authority snapshot

Use a separately trusted **current** Community D1 export, independently of the
historical backup being restored. Finish the deletion archive and artifact
cleanup outboxes, stop and drain every writer, record the writer-stop time, and
keep public access closed. Preserve the original snapshot and its independently
established SHA-256. The database must be a closed, self-contained SQLite file
without WAL, SHM or journal sidecars.

The operator must establish which resource produced it and that every writer
was stopped. A checksum or a newly dated report cannot prove those facts. Do
not substitute the old backup or the intermediate copy made by account repair:
that copy can still contain pending cleanup and unarchived receipts. Do not
change rows to make this check pass. Pending, removed or `needs_review` cleanup
and incomplete archives stop the check.

Only the repository's fixed `production` and `staging` Community account,
database and bucket profiles are accepted. No other bucket is supported.

## 2. Make the private object plan

Use an existing private Node.js 22.20 or newer runtime. This installs nothing.
From `deploy/cloudflare`, run:

```text
node tools/privacy-storage-restore.mjs plan --current CURRENT.sqlite --current-sha256 TRUSTED_CURRENT_SHA256 --writers-stopped-at WRITER_STOP_UNIX_SECONDS --environment staging --out .private-storage-plan
```

Use `production` only for the independently confirmed production resource. The
destination must be new and its parent must exist. The tool creates a private
`current.sqlite` copy, `privacy-object-plan.private.json` and aggregate
`privacy-plan-report.json`. Pin the plan's exact SHA-256 from a trusted copy of
that report before the next step.

The plan independently derives every required object from the current export:

- Immutable deletion receipt JSON, using the exact Worker serialization,
  resource identity, receipt values, archive hash and required metadata.
- Permanent fence bytes for unpublished deleted-account artifacts, including
  intent-only uploads and legacy quarantine. Final artifacts require the
  matching intent journal; lease and account ownership must agree.
- No fence for retained published contributions. A publication/fence conflict
  stops the check.

The plan contains private account IDs, receipt keys and artifact paths. Keep it
and its database out of public Git, issues and shared logs. Completing a plan
does not prove that any storage object exists.

## 3. Export observed metadata and cache actual bytes

Obtain actual objects from the independently confirmed recovered Community
resource through the approved operator process. This tool does not fetch them.
Preserve observed HTTP/custom metadata; compute size and SHA-256 from the bytes
actually downloaded. Do not fill observed values by copying the expected plan.

For each planned key, save its body as `SHA256_OF_UTF8_OBJECT_KEY.blob` in a
private cache directory. The exported `privacyObjectCacheName(key)` helper
computes this opaque filename. Keep the mapping in the private inventory:

```json
{
  "version": 1,
  "scope": "vision-community-privacy-object-cache",
  "resource": {"accountId": "CONFIRMED_ACCOUNT", "databaseId": "CONFIRMED_DATABASE", "bucket": "CONFIRMED_BUCKET"},
  "exportedAt": 0,
  "objects": [{
    "key": "ACTUAL_PLANNED_KEY",
    "size": 0,
    "sha256": "ACTUAL_DOWNLOADED_BODY_SHA256",
    "httpMetadata": {"contentType": "ACTUAL_CONTENT_TYPE", "cacheControl": "ACTUAL_CACHE_CONTROL"},
    "customMetadata": {"ACTUAL_METADATA_NAME": "ACTUAL_VALUE"}
  }]
}
```

This is a schema example, not usable evidence. The resource has exactly the
three confirmed fields; `exportedAt` must be between the writer-stop time and
the checking machine's current time. Include each required privacy object
exactly once. Additional observed metadata fields are allowed, but every
required value must match. Pin this inventory independently too.

## 4. Check the observed recovery

```text
node tools/privacy-storage-restore.mjs check --plan .private-storage-plan/privacy-object-plan.private.json --plan-sha256 TRUSTED_PLAN_SHA256 --inventory observed.private.json --inventory-sha256 TRUSTED_OBSERVED_SHA256 --cache .private-storage-cache --environment staging --out .private-storage-check
```

The checker copies the plan's pinned database into its own new private folder,
rederives the complete expected object set, checks observed metadata and cached
bytes, then checks the inputs and every cached object again before finishing.
A newly pinned edited plan cannot omit objects still required by that database.
Links, overlapping outputs, mixed resources, duplicate or missing objects,
changed bytes and stale metadata are refused. Existing outputs are preserved.

On success, preserve `privacy-storage-report.json` and its hash together with
the private `checked-files.private.json` inventory. That inventory uses opaque
cache filenames. CLI output contains aggregate counts and fixed failure codes;
it does not print private object keys or raw SQLite/provider errors.

Inputs are bounded to 512 MiB per database, 64 MiB per JSON file, 10,000 deletion
receipts, 110,000 required privacy objects and 2 KiB per cached privacy body.
These limits describe a finite recovery check, not capacity qualification.

## Evidence and remaining acceptance

The focused local tests cover independent expected bytes, actual Worker
deletion/archive/cleanup output, retained contributions, missing outboxes,
ownership, payload/metadata corruption, repinned reduced plans, late changes,
links and a closed WAL-mode export. This does not validate live R2 credentials,
durability, inventory completeness outside the trusted snapshot, service
reopening or recovery of accepted work and credits. Complete the remaining
[production recovery acceptance](PRODUCTION_ACCEPTANCE.md) before reopening.
