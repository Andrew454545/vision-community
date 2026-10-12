# Published Object job cleanup

Published Object batches can now release their local candidate, successful
reference index and image/model cache. The hosted coordinator first verifies
the immutable acceptance record, owned published rows and matching earned-credit
ledger entry. Native approval alone cannot start cleanup.

A private saved outbox retries a lost acknowledgement with the same pinned
request, using backoff from one minute to one hour. Request replay and the
existing scheduled handler both deliver pending work. Each handler handles at
most two jobs within five seconds; delivered intents are not routinely polled.
The native worker owns cleanup after its durable acknowledgement.

The native spool records `retiring` before acknowledging and `retired` only
after removal completes. Interrupted filesystem or database work resumes after
restart without inference. Original failed attempts, successful audit reports,
source copies, logs, retry nonces and tombstones remain. Account erasure takes
priority and can still remove the entire job. Neither cleanup state is approval.

## Operator rollout

These changes are source-only; public Object admission remains closed.
Use a verified runtime/policy migration when replacing pinned service code.
Retain the existing spool and independent recovery/deletion authority.

After the existing dispatch and settlement setup, explicitly run
`prepareObjectAuditRetention(db)` from
`deploy/cloudflare/tools/prepare-object-audit-retention.mjs` against the confirmed
Community database. It atomically checks the exact optional schema. HTTP and
scheduled requests install nothing; missing setup leaves accepted work intact.
Deploy the matching private bridge/native service and hosted coordinator.
Rehearse deletion, retry and restore against that actual deployment before admission.

The private `POST /object-audits/<jobId>/retire` body contains exactly `version`,
`leaseId`, `assignmentSha256`, `submissionSha256`, `candidateManifestSha256`,
`receiptSha256`, `attempts` and `acceptanceSha256`. Only the trusted coordinator
constructs it from saved acceptance; users cannot choose paths or cleanup targets.
Its response remains non-authorizing, with zero contributions and credit.

## Verification and limits

Windows checks exercise saved intent delivery, lost replies, backoff, report and
failure preservation, interrupted cleanup, restart, once-only credit, privacy
priority and optional-outbox SQL recovery. Native inference and coverage in these
checks are synthetic. See [recorded evidence](evidence/object-native-retention-20261012.json).

Cleanup releases the 512 MiB input allowance; it does not erase historical job
IDs or remove the 64-job/version-1 and 4,096-job/version-2 registry bounds.
Failed attempts and retained logs still consume disk. Automatic trusted assignment
delivery, measured long-term storage/capacity, authentic Mac/Windows qualification
and native-host acceptance remain launch work. No installed service, frozen
Windows Scene pilot, live database or Cloudflare resource was changed here.
