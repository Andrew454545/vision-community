# Production acceptance and continuation

Updated 2026-09-29. This checklist defines completion; "perfect" is not a
testable release claim. Check off a requirement only with test or deployment
evidence. Preserve earlier calibration failures and do not turn exploratory
measurements into automatic production approval.

## Reference and boundaries

- Reference application: `Andrew454545/VISION`, inspected at
  `9811448e3e05259e08f5106ab5a7740dce0c6b4a`.
- Community working branch: `codex/windows-production-readiness`.
- Never read or modify the `geonections-images` bucket. The Community config
  names `vision-community`; confirm the account and binding before deployment.
- Do not import the reference application's private corpus as searchable
  Community contributions. Only published contributions belong in the shared
  index. Input queue metadata and searchable contributed indexes are distinct.
- Keep bulk catalogs, account codes, models, results, and live databases out of
  Git. Small, deliberate calibration fixtures may be versioned.

## Completed in this pass

- Added an opt-in unattended Windows scene worker with a single-instance lock,
  saved account reuse, qualification checks, bounded waits, low-disk protection,
  a pause file, and preserved diagnostics. Its installer uses a versioned source
  snapshot, a per-user logon task and Windows recovery scheduling, not Codex.
- Both Python and Worker scene/object downloads now require a published index
  row tied to a contributor. Orphaned storage and uncredited imports are denied.
- Public object manifests replace the local source path with `locations.tsv`.
- Object search uses CPU on Windows/Linux rather than requesting Core ML.
  This is a prerequisite, not a validated Windows object release.
- Catalog tail extraction no longer needs Unix `head`/`tail`; Windows launcher
  hashing no longer depends on the inherited PowerShell module search path.
- Banked credits are tested across application restarts and search debits.
- Added a private staging scene verifier with bounded reads, checksum-pinned
  policies and references, independent vector comparisons, and payload-bound
  audit approval. Production inference auditing remains a separate gate.
- Scene publication now claims the quarantined locations and grants credit in
  the same transaction. SQLite-backed Worker tests demonstrate concurrent
  approval credits once, failed publication rolls credit back, and a changed
  queue cannot be published or credited.

## Blocking live indexing

- [x] Authorize unattended external contributions. The user explicitly approved
  anonymous account creation/reuse, downloads, imagery and verified submissions.
  The earlier approval rejection is resolved; do not ask for this consent again.
- [x] Cloudflare API access is connected. On 2026-09-29, read-only checks
  confirmed the `Geonections Account`, the `vision-community` Worker, its
  `vision-community` D1 database, and its `vision-community` R2 binding. The
  excluded `geonections-images` bucket was not accessed.
- [ ] Deploy and test the trusted scene verifier and approved runtime policy.
  A private verifier is now implemented for staging: it independently compares
  the 112-location output with a checksum-pinned reference in a separate,
  private policy bucket and fails closed for every unreviewed submission. It
  still needs the owner-reviewed calibration policy and a live staging exercise.
  The live `/api/capabilities` returned `not_found` on 2026-09-29.
- [ ] Complete the PC qualification against that policy. Never bypass it.
- [ ] Confirm the source of real work: the shared Community queue or a supplied
  local production location list. The reference source repository does not
  contain its full runtime corpus. Repeating the calibration fixture is not
  ongoing useful indexing.
- [ ] Install the Windows task, observe one actual accepted batch, exercise
  pause/resume, forced exit, network loss, sleep/wake and logon recovery.
  Sleep/power-off suspends computation; after restart the user must sign in.
  On 2026-09-29 registration succeeded but scheduled startup failed (Windows
  results 0x80070002, 0x8007010B, then PowerShell 0xFFFD0000; direct windowless
  Python still returned 0x80070002). The failing task was disabled. Direct Python
  execution wrote `waiting_for_service`; it did not process a contribution.
  File visibility differs between launch contexts as a possible explanation,
  not a confirmed diagnosis. Preserve the startup report and resolve this on
  the host before approving unattended operation. Do not repeat unchanged
  scheduler probes on every development heartbeat.
  The default Windows PowerShell test host also rejected scripts under its
  execution policy. No policy was changed; helper tests pass under the existing
  configured PowerShell host. A signed installer remains a release requirement.

## Remaining release gates

- [ ] Strict official Gen4 object admission, processing, publication and search,
  using trusted historical-capture validation. A client-supplied generation
  label or a well-formed panorama ID alone is insufficient evidence. The local
  service and Worker now fail closed: object leases, publication downloads and
  search indexes require an `object_coverage` receipt naming the pinned
  `official-gen4-historical-v1` validator and a 64-character evidence digest.
  Generic pose catalogs cannot create this receipt. A trusted coverage importer
  and live staging test still need to be deployed before this can be checked off.
- [ ] Publish checksum-pinned Windows/Linux object binaries and runtime assets;
  compare all RF-DETR, YOLOE and OWLv2 lanes with the reference results.
- [ ] Audit object submissions using trusted inference. Current structural
  validation alone does not prove that the volunteer performed inference.
- [ ] Finish 1/2/4-thread measurements on fixed inputs; define quality/ranking
  tolerances and approve only measured configurations. Compare numerical
  outputs and rankings, not merely file bytes from changing live imagery.
- [ ] Durable job queues and measured CPU/memory budgets for parallel scenes
  and objects; avoid two independent processes oversubscribing one device.
- [ ] A signed packaged application with guided downloads, qualification,
  contribution, pause, recovery and search. Test with a nontechnical person
  on a clean Windows PC and a supported Mac. Mobile/low-memory support remains
  unvalidated; do not advertise every device as supported.
- [ ] Anonymous account recovery, user deletion, retention policy, minimization
  of IP/search logging, public artifact metadata and maintainer identity audit.
  Removing names from a UI does not erase Git history or provider records.
- [ ] Ledger concurrency, replay and failure tests; no credit expiry or cap
  unless the owner explicitly chooses one. A finite queue cannot guarantee an
  infinite supply of useful new work; wait for new work without re-crediting it.
- [ ] Storage publication atomicity, backup/restore, deletion, secret rotation,
  service failure recovery, resource/cost measurements and live staging tests.
- [x] Read-only inventory completed on 2026-09-29. The confirmed Community
  bucket is in ENAM and has only Cloudflare's seven-day incomplete-upload
  cleanup rule. The D1 database has 17 anonymous accounts, 101,123 locations,
  29,664 published scene indexes, 1,854 ledger rows, and no searches; sampled
  aggregate checks found no published rows without a contributor or source.
  No object contents or records from the excluded bucket were read. Plan any
  removal of legacy indexes explicitly; do not delete existing data merely to
  enforce the new publication policy.

## Architecture decision still required

Keep a small website for onboarding, recovery, credit balances and search UI;
keep local inference in a packaged app. D1/another transactional database owns
queue leases and credits. R2 holds immutable verified contribution artifacts.
GitHub distributes code/releases, not a mutable location database.

The current client downloads shared indexes and searches locally. Once an index
has been downloaded, the service cannot enforce a debit for every subsequent
offline search. Strong per-search enforcement requires a trusted hosted search
service, with measured compute and operating cost, or a product rule that sells
index access instead. Do not claim both free unlimited index distribution and
unbypassable per-search credits. Decide this before redesigning/deploying search.

## Recurring development

The chat has a seven-hour development heartbeat. Use this file to choose useful
work, run the relevant checks, and commit/push verified changes. Do not poll the
local indexer with Codex. Notify only on meaningful changes or necessary user
action; pause the heartbeat when the agreed acceptance gates are satisfied.
