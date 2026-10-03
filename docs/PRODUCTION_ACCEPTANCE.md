# Production acceptance

Updated 2026-10-03 UTC. **The project is not yet approved for production.**
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
| Actual staging contribution | Corrected binary64 pose serialization; fresh 112-location qualification; new eight-location batch independently audited, published and credited once. Two earlier strict-policy submissions remain rejected. | [Admission](STAGING_SCENE_ADMISSION_20261003.md) |
| Actual staging search | Independently sealed snapshot of only those eight contributions passed native search, filters and exact response recovery after restart. Hosted API charged once; exact/account-recovery retry did not charge again; conflicting/unfunded requests were rejected. | [Admission](STAGING_SCENE_ADMISSION_20261003.md) |
| Hosted native operation | Real private Linux FP32 inference and restart, bounded eight-location audits, frozen capture/replay, lifecycle failure recovery and stopped compute with seal retained. Public/preview URLs, SSH and Container logs disabled. | [Startup](HOSTED_SCENE_CHECK_20261003.md), [budgets](HOSTED_SCENE_BUDGET_20261003.md) |
| Objects on Windows | All three pinned models processed six views; full one-location index and both native verifications passed. Eighteen frozen 1/2/4-thread detector commands agree within the sample. App-local compiler libraries were observed and checked. | [Objects](PC_OBJECT_CALIBRATION_20261002.md) |
| Portable object build | Private Windows/Linux CPU builds pass 49 native tests. All 11 model assets, source, binary and dependency receipts were checked. A new finite clean-Linux actual model/index check is running; no inference result is claimed yet. | [Objects](PC_OBJECT_CALIBRATION_20261002.md) |
| Banked accounting | Transactional publication/credit and search/result/debit; concurrency, replay and rollback tests. Actual hosted search used a separate disposable synthetic 100,000-unit balance; the eight real earned units stayed unchanged. Synthetic account deleted. | [Admission](STAGING_SCENE_ADMISSION_20261003.md) |
| Privacy and recovery | Anonymous recovery/deletion, revoked credentials, late scene-write fences, immutable R2 deletion receipts, real staging deletion-aware D1 restore. Offline published-index/catalog integrity checker rejects missing, corrupt or linked files. | [Privacy](ACCOUNT_PRIVACY.md), [restore](PRIVATE_RESTORE.md) |
| Beginner flow | Short README/website guide, guided Windows starter, qualification/service checks, saved-code recovery, pause/resume and private diagnostics. Website assets/privacy headers verified in staging. | [Service readiness](WEBSITE_SERVICE_READINESS.md) |
| Background worker | Native scheduled startup, idle handover and idle forced-exit/pause/resume verified. Installed schedule: medium 06:00–00:00, max 00:00–06:00 local; saved account, 30-minute service retry, sign-in/recovery triggers and one worker. | [Background processing](BACKGROUND_PROCESSING.md) |

Latest completed Community code checks: 386 Python, 192 JavaScript, 37 actual
workerd private-host cases and 15 private HTTP/preparation checks. Community
CI passes at `a4b2630`; the code change also passed all five jobs at `b356398`.
Actual Windows CI ran all 386 Python tests without skips. New private Linux
inference checks must be evaluated separately from earlier successful builds.

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

### Portable Objects and coverage

- [ ] Complete actual clean-Linux inference/indexing and clean-device runtime
  dependency checks; publish checksum-pinned Windows/Linux assets.
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

- [ ] Exercise real daytime/nighttime boundaries, overnight work, scheduled
  pause/resume and settings changes during a batch, using the PC's local clock.
- [ ] Observe idle-sleep requests/release and actual sleep/wake plus Windows
  sign-in recovery. A sleeping or powered-off computer cannot compute; work
  resumes after it is awake and signed in. Never advertise otherwise.
- [ ] Exercise network loss, active-process exit and persistent delayed retries
  without rapid loops. Permanent trust/account failures must retain evidence
  and stop, not retry indefinitely or silently weaken qualification.
- [ ] Exercise installer handover/removal during active work, preserving account,
  checkpoint, delivery and failure files; do not force-kill inference.
- [ ] Run an extended qualified workload measuring accepted batches, temperature,
  memory, disk growth and recovery. Bounded pending delivery, free-space checks
  and optional storage allowance are not a cleanup policy or hard quota.

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
  awards or duplicate debits. Existing privacy repair and offline artifact checks
  explicitly do not establish credit recovery or full disaster recovery.
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
