# Production acceptance and continuation

Updated 2026-09-30. This checklist defines completion; "perfect" is not a
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

- Fixed completed-delivery recovery after definitive lease expiry/loss. The
  journal retains output and a fixed reason, stops retrying that terminal
  delivery, frees its pending slot and continues other deliveries. It never
  reassigns the output or treats network/authentication failures or pending
  audits as expired work. Guided/background status exposes retained
  undelivered-batch counts. Nine new checks include an actual disposable HTTP
  expiry/replay exercise and reconnect recovery. All 269 Python tests pass on
  this Windows host; this is not a live accepted contribution or a days/weeks
  endurance test.
- Opened draft PR #2 with the reference evidence request for Andrew. Initial
  PR CI passed Linux Python, Cloudflare JavaScript/workerd and both calibration
  jobs (including Windows embedded-Python and native executable layout). Windows
  Python CI exposed a missing Pillow test dependency and short/long-path
  assertion mismatches. The workflow now installs declared dependencies and
  tests compare resolved paths; the original failing log is preserved privately.
  Recheck the final PR revision before treating the complete CI gate as passed.
- Bounded the object launcher's native process/retry lifecycle. Native logs and
  exit outcomes are preserved, failed launches/timeouts stop, repeated exits
  and stalled/regressed checkpoints cannot retry forever, and both native
  verification passes remain mandatory. Separate failure reports preserve prior
  evidence. Ten new tests cover recovery and an actual killed helper timeout;
  this does not qualify object models or implement an unattended object worker.
  All 260 Python tests pass after fixing a Windows timestamp collision that
  could overwrite a failure report. The initial failing log is preserved
  outside the repository. See [OBJECT_RECOVERY.md](OBJECT_RECOVERY.md).
- Added an offline deletion-aware restore safeguard. Independently pinned current
  receipts repair a new copy of an old SQLite backup, revoke restored access,
  remove private searches, close restored balances, preserve contributed indexes
  and install current late-write fences. Original backups remain unchanged;
  failures preserve redacted reports without a completion marker. Twelve new
  synthetic tests and all 67 server/browser/verifier tests pass. This does not
  perform a Cloudflare restore, reconcile other post-backup credits, or complete
  live disaster recovery. See [PRIVATE_RESTORE.md](PRIVATE_RESTORE.md).
- Added hosted account deletion with typed confirmation, atomic session and
  recovery revocation, credit closure, removal of private search results,
  unfinished-work release and database fences against delayed writes. Browser
  receipts recover lost responses and preserve other accounts' journals;
  confirmed deletion prevents delayed tabs from recreating private results.
  Local workerd/D1/R2 tests also exercise hourly bounded quarantine cleanup at
  the configured compatibility date, 2026-09-19. These are synthetic local
  tests, not a live deployment or completed retention/privacy audit. See
  [ACCOUNT_PRIVACY.md](ACCOUNT_PRIVACY.md) for records retained and release gaps.
  Verification at that step: 55 JavaScript and 233 Python tests passed; the complete
  Worker builds and passes the native privacy/search/scheduled-cleanup check.
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
- Guided and background clients persist completed submissions before network
  delivery. A restart resumes pending delivery/audit under the same anonymous
  account and service. Unresolved batches are bounded, and rejection preserves
  the evidence and stops processing. Local tests verify this recovery path.
- Online search settlement saves the result, debit and ledger entry in one D1
  transaction. Tests cover duplicate requests, concurrent spending of the last
  credit, changed requests, and rollback on failed result storage. The browser
  saves the request before delivery and recovers a lost response after restart.
  These are local tests; the hosted inference engine is not deployed.
- The complete Worker builds with Wrangler 4.144.0. The same search scenarios
  also pass in Cloudflare's local workerd/D1 runtime at compatibility date
  2026-09-29, using synthetic results and a disposable local account. This is
  transaction/gateway evidence, not VISION model parity or live deployment.
  CI now runs that check on the authorized development branch too.
- The private verifier also passes a synthetic exercise using Cloudflare's
  local R2 runtime at compatibility date 2026-09-29. Damaged or missing operator
  reference data is a retryable service failure, rather than a PC rejection.
  All 31 JavaScript tests pass. No synthetic policy has been deployed or used
  to approve a real runtime.
- Hosted map exports now follow the inspected VISION reference for query modes,
  query thresholds/text, model names, registry ordinals, object evidence and
  seven-decimal rounding. Engine contract version 2 requires that evidence.
  All 37 JavaScript tests pass, including semantic object's zenith/nadir faces,
  tied scores with registry order differing from D1 IDs, and rejected metadata
  that spends no credit. The full gateway again passes local workerd/D1 checks.
  Export conformance is separate from the pending inference/ranking comparison.
- Added an operator-only offline scene snapshot sealer: separate inventory and
  independent approval pins, per-record artifact verification, stable ordinals
  across appended updates, account-identifier minimization, durable files and
  manifest-last publication. Seven tests cover admission, tampering, corruption,
  path boundaries, privacy, update history and preserved failures. Live export
  and hosted inference remain unimplemented.
- Added the corresponding offline object snapshot sealer. It requires published
  contributions, trusted Gen4 coverage receipts and a separate audit pin for
  each complete feature bundle. Object publication digests alone identify
  global-ID records and cannot prove model inference. The sealer checks native
  files, preserves approved feature history and source ordinals, minimizes
  private metadata, retains declared view-quality evidence hashes, bounds
  resources and preserves failures without a completed marker. Seventeen
  synthetic tests cover those boundaries; they do not certify object models.
  See [OBJECT_SEARCH_SNAPSHOTS.md](OBJECT_SEARCH_SNAPSHOTS.md). Trusted live
  object auditing, portable binaries, live export and hosted inference remain
  release requirements. All 250 Python tests pass on this Windows host after
  the final changes. The initial temporary-directory permission failure is
  preserved outside the repository; no security policy was changed.
- Windows snapshots now require and include the completed-submission delivery
  journal. An isolated Python import test checks the actual packaged guided and
  background applications so missing modules cannot be hidden by the checkout.
  Windows CI uses its configured PowerShell host for helper tests, without
  changing execution policy. The signed installer/scheduler host gates remain.
  After these fixes, all 207 Python tests pass on this Windows host; the initial
  default-host/stale-assertion failure log is preserved outside the repository.

## Blocking live indexing

On 2026-09-30, all 233 Python checks and 37 server/browser checks passed for
the day/night and recovery changes. The updated private Windows task passed
fresh paused startup, automatic resume to its unavailable-service wait, and
an actual graceful installer handover without force-stopping the new worker.
Exactly one native worker remained enabled and Running. This is startup and
handover evidence only: zero production locations were accepted, and no
qualification check was bypassed. The earlier intermediate scheduler-interval
test failure was preserved and resolved before the final checks.

The user requested that `max` eventually use parallel processing like the
reference application. It currently runs continuous single-thread batches.
Do not advertise all-core processing or enable an unqualified thread count.
The controlled 1/2/4-thread quality/ranking and throughput gate below remains
open; unchanged input pixels and a fresh reference comparison are needed.

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
  still needs an independently validated calibration policy and a live staging exercise.
  The live `/api/capabilities` returned `not_found` on 2026-09-29.
- [ ] Complete the PC qualification against that policy. Never bypass it.
- [x] Confirm the source of real work: the shared Community queue. Read-only
  R2 manifests and D1 catalog aggregates on 2026-09-30 confirm 933 metadata
  shards registered for each lane, including 20,955,444 already-indexed
  location rows exported from the reference application. These are location
  inputs, not copied reference vectors or frozen images. See
  [REFERENCE_R2_INVENTORY.md](REFERENCE_R2_INVENTORY.md) for the existing
  four-view contributions, provenance limits and remaining calibration gate.
  This does not approve the PC runtime or prove Generation 4 object coverage.
  Repeating the calibration fixture is not ongoing useful indexing.
- [ ] Install the Windows task, observe one actual accepted batch, exercise
  pause/resume, forced exit, network loss, sleep/wake and logon recovery.
  Sleep/power-off suspends computation; after restart the user must sign in.
  On 2026-09-29 registration succeeded but scheduled startup failed (Windows
  results 0x80070002, 0x8007010B, then PowerShell 0xFFFD0000; direct windowless
  Python still returned 0x80070002). The failing task was disabled. Direct Python
  execution wrote `waiting_for_service`; it did not process a contribution.
  A native scheduled diagnostic on 2026-09-30 UTC confirmed that Task Scheduler
  could see neither the old runtime nor its launcher, although both were visible
  to the development shell. A fresh checksum-verified private installation in
  the shared local workspace (`work/background-host-20260929`) now starts on
  the native scheduled host. The task is enabled and Running with one actual
  worker, state `waiting_for_service`, zero accepted locations and no startup
  failure. An idle forced-exit/pause/resume exercise also passed and restored
  that waiting state. The original files/failure reports remain preserved.
  Native startup is verified; accepted-batch, network, sleep/wake and logon
  recovery still require evidence. Keep this folder in place. Do not spend
  development heartbeats polling the waiting worker; its own 30-minute retry
  and Windows recovery trigger operate without Codex.
  The default Windows PowerShell test host also rejected scripts under its
  execution policy. No policy was changed; helper tests pass under the existing
  configured PowerShell host. A signed installer remains a release requirement.

## Remaining release gates

### Long-running Windows processing

The background worker is intended to remain available over days or weeks,
without Codex polling. Its operating contract is described in the
[background guide](BACKGROUND_PROCESSING.md):

- The default daily schedule is medium from 08:00 to 22:00 and max overnight,
  using the PC's local clock. Each period can instead use slow, medium, max or
  pause. There is no separate weekday/weekend schedule.
- Pacing changes at safe batch boundaries. Medium rests for the preceding
  batch's processing duration; slow rests three times as long; max adds no
  deliberate pacing pause. These are approximate active-time targets, not CPU
  percentage caps. They preserve the single inference thread and qualified
  model/runtime configuration.
- Service and empty-queue waits use the chosen retry interval, defaulting to
  30 minutes. Recognized indexing interruptions have increasing delays capped
  at six hours, with retry state preserved across restart. Rejected trust,
  invalid account data and failures requiring review stop with retained
  evidence; recovery does not mean bypassing approval or retrying everything.
- The Windows idle-sleep request covers processing and deliberate pacing
  rests. Manual/scheduled pauses and unavailable-service waits allow normal
  idle sleep. `-AllowSleep`/`--no-keep-awake` disables the request. No power-plan
  change or scheduled wake is implied; sleep, shutdown and lack of sign-in
  still prevent computation.
- Updating an installed snapshot uses a safe `STOP-AFTER-BATCH` handover. A
  busy worker may require the installer to be rerun after its batch finishes;
  applying settings must not force-kill active inference or discard a lease.
- Pending delivery is bounded at 64 batches, but historical indexes, logs,
  journal rows and evidence can still grow. The 5 GB free-space guard is not a
  total disk quota or a cleanup policy. Preserve unsent/rejected work and
  account recovery while resolving storage pressure.

The old scheduled worker's idle recovery evidence does not validate these new
schedule controls. Do not convert the following into completed claims without
recorded evidence:

- [ ] Confirm the installed task's actual options and fresh status match the
  selected day/night schedule, retry interval and sleep preference.
- [ ] Exercise daytime/nighttime boundaries, an overnight interval, scheduled
  pause/resume and changes while a batch is active, using the local clock.
- [ ] Observe idle-sleep requests across paced rests and their release during
  pauses/service waits; separately exercise real sleep/wake and Windows sign-in.
- [ ] Verify delayed indexing retries survive process exit/restart without a
  rapid retry loop, while permanent failures still preserve evidence and stop.
- [ ] Exercise safe installer handover and removal during idle and active work,
  preserving account, checkpoint, delivery and failure files.
- [ ] Run an extended qualified workload with measured disk growth,
  temperature, memory, network interruptions and actual accepted batches before
  claiming dependable days/weeks operation.

### Other release requirements

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
  Account deletion and delayed-write protection are now tested locally; live
  rollout, independent durable deletion-receipt storage, a complete staging
  restore/import, wider orphan cleanup and provider logging/retention review
  remain outstanding. The offline privacy-repair rehearsal is implemented and
  tested; it does not satisfy the complete restore gate.
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

## Architecture decision accepted

Keep a small website for onboarding, recovery, credit balances and search UI;
keep local inference in a packaged app. D1/another transactional database owns
queue leases and credits. R2 holds immutable verified contribution artifacts.
GitHub distributes code/releases, not a mutable location database.

On 2026-09-29 the user chose **online search using banked credits**. The website
now submits searches directly and the Community Worker retires shared-index
downloads and paid-local-search requests with `online_search_required` (410).
Previously downloaded copies cannot be revoked. The local development service
and offline diagnostic commands retain their test behavior; they are not the
production credit product.

- [ ] Deploy a private hosted engine using the reference models and only an
  independently sealed, contributed index snapshot. The gateway requires a
  policy ID, runtime digest and snapshot digest, validates every hit against D1,
  enforces Gen4 receipts for objects, and spends nothing if the engine is
  missing or returns invalid results. The prototype 96-dimensional extractor
  is not an acceptable substitute for VISION's four-view scene vectors.
- [ ] Measure hosted compute, memory, latency and cost, including simultaneous
  requests and an index update during search. Compare held-out rankings with
  Andrew's application before advertising parity.

Repository inspection found no approved Windows tolerance policy. The supplied
historical packet explicitly says `SOURCE_PIXELS_NOT_FROZEN` and
`non_exact_acceptance_thresholds: NOT_ESTABLISHED`. The reference's installed
Mac runtime uses a different binary and observed provider/settings. An exact
controlled input comparison and fresh reference repetitions are required to
derive numerical and ranking bounds; the earlier live trials cannot provide
them. The user asked us to determine this from evidence, not invent approval.

The 2026-09-30 [R2 inspection](REFERENCE_R2_INVENTORY.md) confirms that Andrew's
already-indexed pose catalog and newer Community four-view artifacts do exist.
The catalog explicitly excludes copied embeddings and imagery; the newer
artifacts have Community publication records but no attested reference runtime
or three-run frozen-input packet. Preserve them without treating their presence
as a completed quality gate.

## Recurring development

The chat has a seven-hour development heartbeat. Use this file to choose useful
work, run the relevant checks, and commit/push verified changes. Do not poll the
local indexer with Codex. Notify only on meaningful changes or necessary user
action; pause the heartbeat when the agreed acceptance gates are satisfied.
