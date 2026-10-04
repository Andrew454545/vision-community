# Production acceptance

Updated 2026-10-04 UTC. **The project is not yet approved for production.**
This checklist describes the current state; check off a release gate only with
recorded evidence. Earlier failures and exploratory results remain separate.
The previous chronological development log remains in
[Git history](https://github.com/Andrew454545/vision-community/blob/a4b2630b1e8a049bbe79f904aad75376b6432c8d/docs/PRODUCTION_ACCEPTANCE.md).

## Boundaries and architecture

- Andrew454545/VISION is the reference. Preserve its model, geometry, query,
  ranking and map-export behavior where verified. Development reconstructions
  do not alone establish equivalence with his installed application.
- Never access the `geonections-images` bucket. Use only the confirmed Community
  account and complete database/bucket/environment pair.
- The shared searchable index contains independently verified, published user
  contributions. Andrew's catalog is queue metadata, not permission to import
  his vectors as contributions. Finite reference comparisons are authorized.
- GitHub distributes source and releases. R2 stores immutable verified artifacts;
  D1 owns accounts, queue leases, publications and credits. Keep models, private
  imagery, credentials, live databases and raw results out of Git.
- Keep the small website for onboarding, recovery, balances and **online search
  using banked credits**, as chosen by the user. Shared-index downloads and paid
  local-search requests are retired. Previously downloaded files cannot be revoked.
- Never bypass qualification or infer approval from an exploratory trial. Andrew
  delegated engineering decisions; his separate sign-off is not a prerequisite.

## Evidence already completed

| Area | What the evidence establishes | Details |
| --- | --- | --- |
| Scenes on Windows | Final pinned package completed three fresh 1,024-location trials at each of 1/2/4 threads, zero errors and complete masks. Nine frozen 16-location replays agree with Mac on all 81 query orders/selected views. Bytes differ across platforms. | [Calibration](PC_CALIBRATION_20261002.md) |
| Larger controlled Scenes | Andrew's unchanged supplied Mac binary captures/replays 128 new locations; nine identical-input PC repeats match all top-ten/top-100 sets. Two near-score rank pairs and one selected view differ in every repeat. All PC packed indexes/search results agree across threads; cumulative CPU and committed-memory receipts verify descendant cleanup. | [Held-out evidence](HELD_OUT_SCENE_REFERENCE_20261004.md) |
| Fixed starter inputs | Three fixed synthetic Mac repeats and fresh PC 1/2/4-thread checks finish all 112 locations. Preprocessing hashes match Mac; PC packed indexes agree across threads and meet unchanged experimental bounds. Full production qualification remains separate. | [Fixed check](FIXED_PC_CHECK_20261004.md) |
| Windows working-set observations | Three additional fixed 112-location runs record sampled sums around 797 MiB and peak committed memory around 957 MiB. All accounted processes were observed; owned cleanup passed and packed results stayed identical. This is not exact physical RAM, sustained capacity or thermal approval. | [Memory evidence](WINDOWS_SCENE_WORKING_SET_20261004.md) |
| Actual staging contribution | Corrected binary64 pose serialization; fresh 112-location qualification; new eight-location batch independently audited, published and credited once. Two earlier strict-policy submissions remain rejected. | [Admission](STAGING_SCENE_ADMISSION_20261003.md) |
| Actual staging search | Independently sealed snapshot of only those eight contributions passed native search, filters and exact response recovery after restart. Hosted API charged once; exact/account-recovery retry did not charge again; conflicting/unfunded requests were rejected. | [Admission](STAGING_SCENE_ADMISSION_20261003.md) |
| Hosted native operation | Real private Linux FP32 inference and restart, bounded eight-location audits, frozen capture/replay, lifecycle failure recovery and stopped compute with seal retained. Public/preview URLs, SSH and Container logs disabled. | [Startup](HOSTED_SCENE_CHECK_20261003.md), [budgets](HOSTED_SCENE_BUDGET_20261003.md) |
| Objects on Windows | All three pinned models processed six views; full one-location index and both native verifications passed. Eighteen frozen 1/2/4-thread detector commands agree within the sample. App-local compiler libraries were observed and checked. | [Objects](PC_OBJECT_CALIBRATION_20261002.md) |
| Objects on Linux | Fresh Ubuntu CPU build passes 49 native tests. All 11 pinned assets, actual RF-DETR/YOLOE/OWLv2 six-view processing, identical within-run repeats, complete one-location index and full native verification pass. | [Linux evidence](LINUX_OBJECT_INFERENCE_20261003.md) |
| Banked accounting | Transactional publication/credit and search/result/debit; concurrency, replay and rollback tests. Actual hosted search used a separate disposable synthetic 100,000-unit balance; the eight real earned units stayed unchanged. Synthetic account deleted. | [Admission](STAGING_SCENE_ADMISSION_20261003.md) |
| Privacy and recovery | Anonymous recovery/deletion, revoked credentials, late scene-write fences, immutable R2 deletion receipts, real staging deletion-aware D1 restore. Offline published-index/catalog integrity checker rejects missing, corrupt or linked files. | [Privacy](ACCOUNT_PRIVACY.md), [restore](PRIVATE_RESTORE.md) |
| Beginner flow | Short README/website guide, guided Windows starter, qualification/service checks, saved-code recovery, pause/resume and private diagnostics. Website assets/privacy headers verified in staging. | [Service readiness](WEBSITE_SERVICE_READINESS.md) |
| Background worker | Native scheduled startup, idle handover and idle forced-exit/pause/resume verified. Installed schedule: medium 06:00–00:00, max 00:00–06:00 local; saved account, 30-minute service retry, sign-in/recovery triggers and one worker. | [Background processing](BACKGROUND_PROCESSING.md) |

Community CI passes all six jobs at `656f3f3`, including the repaired Mac
ownership job. The cleanup repair passes 465 local Windows
tests in 225.461 seconds (two existing filesystem-link permission skips), 28
ownership/resource guards and all 51 calibration guards. Two fresh actual
supplied-Mac timeouts also pass with own-user private-group cleanup verified;
protected OS service lifetime remains outside the check. See
[the cleanup report](MAC_TIMEOUT_CLEANUP_20261004.md).
The verifier reply-boundary change passes all 206 JavaScript tests and 13 new
actual local workerd gateway cases. Broken approvals are retryable service
errors and cannot create qualification, publication or credit; valid audit
retry still awards once. Gateway accounting/privacy, deletion archive,
maintenance, restore SQL and independent verifier regressions also pass.
See [reply-boundary evidence](VERIFIER_REPLY_BOUNDARIES_20261004.md). The existing
private-host coverage remains 37 workerd and 15 private HTTP/preparation checks.
The checked-in staging config now uses the independently read-back, confirmed
account/database/bucket pair; the retired release-staging mapping was removed.
An offline resource/admission preflight and matching staging dry-run build pass.
Three resource-mix/override guards bring local JavaScript coverage to 209 tests.
The source-only Windows
preview retains its tested `4e53420` revision, with actual progress, pending-work
and reconnect notices. New fixed-check code is recorded separately from that
immutable preview.
The fixed starter implementation passes all 441 local Windows Python tests
in 205.074 seconds, with two existing filesystem-link permission skips. Its
ten new fixed-input guards and installed-copy generator check are included.
The initial installed-copy path guard failed in CI on a shortened Windows path;
resolving both paths repaired the guard. The complete Windows CI rerun passes
all 441 tests without skips in 227.215 seconds; the original failure is retained.
Private native hosting, both portable object jobs, both held-out reference jobs
and both new fixed-input Mac jobs pass at `977c20a`. The unchanged supplied Mac
executable completed three fixed 112-location repeats; the reduced private
artifact and regenerated input inventory were independently verified.

The [3 October Windows preview](https://github.com/Andrew454545/vision-community/releases/tag/windows-starter-preview-20261003)
is source-only, with 237 files independently checked after public download.
ZIP SHA-256: `26e55b7d1b85b36a29742dff084741802e1d480f18f8966839be9db9f5307f1e`.
Staging's 13 assets and short guide match that source revision; privacy headers
remain enabled. Contribution and paid-search availability remain closed.
The gateway update from `656f3f3` is deployed to confirmed staging version
`06ef6c1d-d261-4aca-bde8-77d908d52fb4` (4 October, 09:21 UTC). All 13 assets
and privacy headers pass fresh readback; all expected bindings match, preview
URLs remain disabled and contribution readiness remains false. These read-only
checks create no accounts, credits or native work. Production is unchanged.

The admission/search experiment ended with eight published staging locations,
eight spendable earned units, the disposable account deleted and compute stopped.
Temporary public contribution/search bindings are closed. Production was unchanged.
The deployed immutable runtime uses its independently pinned older helpers;
shipping newer offline helpers requires new runtime and policy pins.

## Release gates still open

### Production scene contributions and search

- [ ] Broaden controlled reference coverage and derive numerical/ranking bounds
  from held-out data. The historical full trial used separately fetched images;
  it cannot isolate runtime error. The staging `.9999` cosine / `.02` relative-L2
  policy is a finite measured experiment, not a production tolerance.
  The new 128-location controlled study is complete and discloses its ranking
  differences. A separately refreshed 112-location live-source diagnostic
  finished but exceeded the cosine limit. Its sixteen-image fixed replay passes;
  retrieving again changes 41 views and fails both limits.
  [Release-pinned dataset support](RELEASE_CANARY_DATASET.md) preserves the
  historical fixture and adds a fixed synthetic starter path. Its successful
  diagnostic cannot approve a PC by itself. Live contribution audits still need
  independently trusted imagery identity so photograph changes cannot be
  confused with runtime error or used to excuse forged vectors.
  The [full identical-input Mac trial](FULL_MAC_REFERENCE_20261004.md) is
  complete: capture plus all three full repeats have identical packed indexes,
  tensor hashes and twelve-query results. The pinned private artifact passes
  [offline verification](FULL_SCENE_REFERENCE_VERIFICATION.md): 4,096 full RGB
  and 32,896 normalized/pooler transports, masks/checkpoints/source/model/query
  pins and repeat identities. Preprocessing bytes remain omitted, hashes only.
  This completes controlled Mac reference transport, not PC qualification.
  The [finite full PC matrix](FULL_SCENE_REFERENCE_VERIFICATION.md) has started,
  with 66 local calibration guards passing. It uses completed pinned Mac
  gold, rotates three fresh trials each at 1/2/4 threads, retains all PC tensor
  bytes, records resource/cleanup receipts and reports full query differences.
  Its first index reached the original 90-minute bound at 688 locations, with
  no saved fetch/inference/incomplete-location errors. Owned cleanup passed;
  no case completed and it grants no qualification. The failed attempt is
  preserved. A separate fresh attempt uses longer, explicitly finite allowances
  without changing reference inputs, model/runtime or comparison requirements;
  see [the matrix evidence](FULL_SCENE_REFERENCE_VERIFICATION.md).
  That attempt completed its first full native index and twelve searches,
  then stopped on a verifier inventory defect: the application's retained
  startup receipt was omitted from the expected file list. The corrected
  verifier validates the receipt's identity and retains all byte/inventory
  requirements. All 75 calibration guards pass; original failure and output
  remain unchanged. See [the recovery evidence](FULL_PC_MATRIX_RECOVERY_20261004.md).
  All six Community CI jobs pass with the matrix at `5d1bb33`. A private
  format-compatibility check verifies a copy of earlier actual 128-location PC
  output, retains its raw tensors and confirms the original files unchanged;
  this runs no new native command. A separate finite Windows scheduled task
  downloaded/verified the exact completed Mac run and started the matrix with
  pinned source/runtime files. It is independent of Codex and the installed contributor
  worker. Its registration does not establish actual restart or endurance.
  The first full attempt failed near its original two-hour bound during repeat
  two; its original receipt reports `PermissionError`. Its pinned archive and
  logs are preserved, and the offline verifier rejects it as incomplete.
  The corrected four-hour run completed. Finite Mac Python fixtures pass timeout
  and parent-exit checks. A separate actual supplied-executable timeout exposed
  a redundant final group stop; its failure is preserved and the repaired
  helper passes two fresh native timeouts. The original full-run receipt has no causal
  stack, so this does not retrospectively establish its exact failure cause.
- [ ] Approve and distribute an exact production runtime/model/helper profile,
  deploy its independent verifier/policy and complete fresh PC qualification.
- [ ] Run useful accepted production batches through the background worker;
  verify saved delivery/audit recovery and earned credit. Its last observed state
  was `waiting_for_service`, zero accepted production locations. The successful
  finite staging DesktopClient run does not establish scheduled production work.
- [ ] Deploy the production contributor-only sealed search snapshot/engine.
  Validate every hit against current publication authority, preserve resource
  identity and deny unowned records without spending credits.
- [ ] Measure hosted cost, memory, latency and concurrency at realistic scale,
  including an index update during search, outage, eviction and credit recovery.
  Eight records prove integration, not full-corpus capacity or ranking parity.
- [ ] Establish parallel scene/object CPU and memory budgets with durable queues.
  Enable only measured configurations. `max` currently removes deliberate rests;
  it does not promise all-core processing or an approved parallel profile.
  Nine additional frozen scene trials measure actual Windows cumulative CPU and
  peak committed memory, with verified descendant shutdown. Two threads provide
  most of the short-sample gain. Three fixed 112-location runs additionally
  observe sampled working sets, with every accounted process observed and
  verified shutdown. Exact simultaneous/unique physical RAM, thermal pressure
  and sustained shared scene/object capacity remain open. See
  [CPU/commit evidence](WINDOWS_SCENE_RESOURCES_20261004.md) and
  [working-set evidence](WINDOWS_SCENE_WORKING_SET_20261004.md).

### Portable Objects and coverage

- [x] Complete actual clean-Linux inference/indexing with pinned assets and
  bounded shared threads; preserve the failed guard job and passing receipt.
- [ ] Complete clean-device runtime dependency checks and publish checksum-pinned
  Windows/Linux object assets.
- [ ] Compare full RF-DETR, YOLOE and OWLv2 production paths with Andrew's
  reference on broader identical inputs. The small development pilot and
  detector thread study do not approve production inference or parallelism.
- [ ] Deploy a trusted historical official Generation 4 coverage importer and
  exercise assignment, resume, publication and search in staging. An arbitrary
  client `gen4` label or valid panorama ID is not proof. Current gates require
  `official-gen4-historical-v1` plus a complete lowercase evidence digest.
- [ ] Audit object submissions with trusted native inference and independently
  approved feature bundles. Structural checks and publication digests alone
  do not show that the contributor ran the models.

### Days or weeks of unattended processing

The [4 October background controls](BACKGROUND_CONTROLS_20261004.md) add a
beginner schedule/pause/resume/status window and verify Windows' saved recovery
settings before starting. Installation keeps a stop marker throughout; the
delivery journal indexes actionable rows instead of scanning accepted history.
Local regression, isolation and real temporary task-readback checks pass.
All six Community CI jobs pass at `b4e79a3`; the final Windows job passes
478 tests in 296.718 seconds. The independently downloaded
[4 October source preview](https://github.com/Andrew454545/vision-community/releases/tag/windows-starter-preview-20261004)
matches all 272 tracked public files and its published checksum. The short guide
is deployed to confirmed staging version `bed0cf46-7bfa-437d-83a1-f1e3bdba1bff`
(4 October, 10:54 UTC); all 13 assets, privacy headers and expected bindings
pass readback. Admission remains closed and production is unchanged.
The installed contributor is unchanged. These improve the recovery design;
they do not satisfy the actual restart, accepted-work or endurance gates below.

- [x] Bound native descendants to their caller and preserve unfinished receipts.
  Real Windows child/grandchild fixtures and an actual half-finished native
  index recover without overlapping writers. The installed windowless Python
  path also passes. The laptop's helper was updated by idle handover; the exact
  tested bytes, schedule and unchanged recovery/failure files were verified.
  Production admission still waits; see [recovery evidence](NATIVE_PROCESS_RECOVERY_20261003.md).
- [ ] Exercise real daytime/nighttime boundaries, overnight work, scheduled
  pause/resume and settings changes during a batch, using the PC's local clock.
- [ ] Observe idle-sleep requests/release and actual sleep/wake plus Windows
  sign-in recovery. A sleeping or powered-off computer cannot compute; work
  resumes after it is awake and signed in. Never advertise otherwise.
  A finite check on this laptop verifies Windows accepted the system-only sleep
  request and restored the previous thread flags. The updated worker checks
  both calls and stops with a preserved report on failure, including during
  pacing rests. Thirty-one sleep/background guards pass. This is not an actual
  sleep/wake, restart or overnight processing exercise.
- [ ] Exercise network loss, active-process exit and persistent delayed retries
  without rapid loops. Permanent trust/account failures must retain evidence
  and stop, not retry indefinitely or silently weaken qualification.
  Real loopback HTTP/SQLite checks across fresh Python processes now cover
  interrupted submission/audit replies, verifier outages, persisted cooldown,
  same-account recovery and a single disposable award. Partial replies use
  bounded transport retries; terminal HTTP statuses remain terminal even with
  an unreadable error body. This is synthetic delivery evidence, not an actual
  qualified batch or OS restart; see [interrupted replies](INTERRUPTED_REPLY_RECOVERY_20261004.md).
  The complete local suite and final Windows CI both pass 482 tests. All six
  Community CI jobs pass at `1e85807`. Its separate source-only recovery preview
  is published and all 274 files independently verified after public download;
  24 checks against that downloaded copy pass. Confirmed staging version
  `d37b0842-3421-482c-b6bf-15e3f29cd1c3` (4 October, 11:39 UTC) serves the updated
  short guide with all 13 assets, privacy headers and bindings verified.
  Admission remains closed and the installed contributor is unchanged.
- [ ] Exercise installer handover/removal during active work, preserving account,
  checkpoint, delivery and failure files; do not force-kill inference.
- [ ] Run an extended qualified workload measuring accepted batches, temperature,
  memory, disk growth and recovery. Bounded pending delivery, free-space checks
  and optional storage allowance are not a cleanup policy or hard quota.
  The updated starter removes only verified large temporary files from a freshly
  service-approved fixed PC check; reports and failed attempts remain. Synthetic
  filesystem and guided-flow guards pass, but live release cleanup and general
  contribution retention still need validation. See [PC check storage](RELEASE_CANARY_DATASET.md).
  The cleanup change passes forty targeted tests and the complete 453-test local
  Windows suite (225.055 seconds, two existing link-permission skips).

### Packaging, privacy and disaster recovery

- [ ] Publish a signed guided application/download flow and test with a
  nontechnical person on clean Windows and supported Mac. Phone, low-memory
  and “any device” support remain unvalidated.
- [ ] Review public/release metadata, maintainer names, IP/search logs, provider
  retention and orphan cleanup. UI anonymity cannot erase Git/provider history.
- [ ] Complete production backup/restore including R2 contribution files,
  permanent privacy markers, deletion archives, sealed native bundles, retired
  legacy segments and secrets. Rehearse credential rotation/service recovery.
- [ ] Reconcile credits and searches earned/spent after backup without replay
  awards or duplicate debits. The offline financial comparison detects changed
  balances, earnings/debits, replay keys and saved responses against a separately
  trusted current cutoff. It does not recover missing events or establish live
  credit recovery; see [the restore guide](PRIVATE_RESTORE.md).
- [ ] Validate complete live publication/storage atomicity and failure recovery,
  load/cost budgets and published retention rules before reopening production.

Credits have no added expiry or cap. A finite queue cannot supply infinite useful
work; an empty queue waits without re-crediting old locations. Preserve legacy
contributions and failures rather than deleting them to make a gate pass.
Confirmed historical catalog/reference provenance limits are recorded in
[the R2 inventory](REFERENCE_R2_INVENTORY.md).

## Continuing work

Use the open gates to select concrete work, preserve evidence, run relevant
checks, and commit/push to the authorized branch. Keep local processing
independent of Codex. The seven-hour development heartbeat should not poll a
healthy/waiting indexer or notify on unchanged status. Pause it only when the
agreed release requirements have evidence; never claim “perfect” without tests.
