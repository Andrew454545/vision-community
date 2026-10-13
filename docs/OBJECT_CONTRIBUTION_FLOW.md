# Object contribution handoff

The saved Object auditor is now connected to guarded publication, once-only
credit and the contributor's restart-safe upload queue. This closes the
publication handoff in source. Public Object assignments and qualification
remain closed until authentic reference and release evidence exist.

For the approved cheaper architecture, a [direct owner-local interface](OWNER_OBJECT_VERIFICATION.md)
now reuses the saved auditor without a listener. Authenticated outbound queue
delivery and guarded import integration remain source work; hosted execution
stays paused under the [cost hold](COST_STOP_20261012.md).

For the initial restricted Object trial, qualification is **per batch**: every
batch must pass the independently configured native comparison. It grants no
reusable device approval. Volunteers do not label objects or run a separate
verification command. An operator must select measured runtime profiles and
explicit score tolerances; three saved locations do not establish broad bounds.

## What happens

1. A trusted assignment stages the contributor's exact output in private
   quarantine. The client saves pending delivery across restarts.
2. The saved native job compares it with the pinned reference and preserves its
   original report. An approved status alone cannot publish or award credit.
3. The coordinator writes only sanitized public index metadata and feature
   files, then requests fresh, full native evidence. That evidence requires
   current protected-source files and expires after 30 seconds.
4. One guarded database transaction records acceptance, publishes every
   location and awards the existing Object units. It compares exact current
   ownership, pose, coverage, receipt and write intents. The database's clock
   also checks expiry. Failure rolls back the whole financial/publication step.
5. Lost replies recover from the durable acceptance. Replays award zero extra
   units. Account deletion preserves accepted contributions and forfeits the
   account's remaining credit.

## Operator connection

After preparing dispatch, explicitly call `prepareObjectSettlement(db)` from
`deploy/cloudflare/tools/prepare-object-settlement.mjs`. HTTP requests never
install this optional schema.

The private `OBJECT_SETTLEMENT_POLICY` JSON setting requires version `1`, scope
`object-batch-parity-v1`, `policyId`, admitted `profiles`, and independently
approved `policySha256`, `runtimeProfileSha256`, `qualityImplementationIdentity`,
`protectedAuthoritySha256`, `protectedOriginHandoffSha256` and Community
`resource`. `INDEX_BUCKET_NAME` must match that confirmed resource. There are
no default profiles, tolerances or authority pins.

`advanceObjectContribution` connects saved auditing and settlement. Authenticated
`/api/object-audits` requests and upload replays use it only when operator policy
is configured. Ordinary Object lease/qualification gates remain closed. The
contributor automatically uses the Object endpoint for its saved pending work;
unknown pending protocols preserve the original upload for retry.

## Remaining launch work

Supply the fresh matching authentic protected handoff, qualify the exact real
Mac/Windows profiles, connect the first real trusted assignment and exercise
earned-credit Object search. Measure full native revalidation within the
20-second handoff budget. Hosted [queue continuity](OBJECT_QUEUE_RETENTION.md)
now releases completed slots while preserving candidate/acceptance history;
eight unfinished batches may wait at once. Native registry rotation and
terminal-job retention remain open: its separate spool still has a 64-job limit.
This is a bounded trial coordinator, not an indefinite public Object queue.

Complete the platform, recovery, capacity, seven-day and signing gates in the
[launch checklist](PRODUCTION_ACCEPTANCE.md). Nothing here starts those clocks
or changes the frozen Windows Scene pilot.

Windows verification: **142 JavaScript checks, 50 Python checks and 10 local
Cloudflare cases across three processes pass**. Model inference and coverage
are synthetic. No real Object work or credits were created and nothing was
deployed. Original failed attempts are retained privately; the machine-readable
[receipt](evidence/object-contribution-flow-20261012.json) records the limits.
