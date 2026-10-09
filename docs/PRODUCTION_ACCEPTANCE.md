# Production acceptance

Updated **9 October 2026**. Start with the finite
[five-gate launch plan](LAUNCH_PLAN.md). The detailed dated evidence below
preserves historical results and limitations; completed reference trials do not
require repeating merely because an older paragraph described them as pending.

The [allocation integration and endurance checks](ALLOCATION_ENDURANCE_20261009.md)
now cover retired catalog assignments, queued fallback, late holds and competing
claims. Andrew's exact-exclusion/export tools are integrated; the complete
replacement catalog handoff is still pending. A finite 24-round offline Windows
supervisor was started independently of Codex, but its first native round timed
out after 902.781 seconds and the failure receipt is preserved. It created no
accepted work or credit and does not close the seven-day production workload gate.

The [native Object auditing component](NATIVE_OBJECT_AUDIT.md) now reruns the
pinned CPU program, requires two full native verifications and compares every
feature lane against independently pinned assignment/quality authority. Its
synthetic tests and actual Windows runtime contract check are component
evidence, not hosted Object qualification, accepted work or release approval.
Unattended Object CLI batches now default to one location, matching guided
processing; CPU-only checks no longer demand an unused DirectML library.
The direct worker and legacy Windows installer now match the guided defaults:
medium 06:00–00:00, maximum 00:00–06:00. Saved custom times remain supported.

GitHub Actions spending is on hold at the user's request (8 October 2026).
Continue local checks without dispatching jobs or triggering paid workflows;
see the repository's developer instructions. Earlier CI evidence remains valid
only for its recorded revisions. New local checks do not establish Mac execution.

The complete local Cloudflare Worker suite currently runs **313 tests**: 306
pass, with seven explicit skips for Windows directory/file-link cases that this
machine cannot create without the OS link privilege, and zero failures. Those
skips preserve the security checks for link-capable hosts; they do not assert
that a link is safe. The same suite previously stopped with raw `EPERM` setup
errors, so the test harness now records the platform limitation honestly.
The Windows native guidance, packaging, signing-preflight and background-control
checks add **46 passing tests** using the pinned PowerShell runtime. The one
link-specific packaging branch is omitted when Windows denies junction creation;
the ordinary package and revision checks still run.

The [complete Object index comparator](OBJECT_INDEX_COMPARISON.md) adds bounded,
pinned comparison of stored detection, quality and semantic features. This is
an offline diagnostic prerequisite, not a trusted inference verifier, a
reference provenance decision or production qualification.
Its optional pinned-codebook analysis now measures decoded semantic vector
differences, explicitly separating rejected placeholders and undefined norms;
this does not replace original tensor or native query comparisons.

The [offline recovery soak](RECOVERY_SOAK_20261008.md) completed 24 scheduled
rounds of 80 existing checks on Windows: no failures/errors, one existing
permission skip per round. This supports fixture recovery reliability; actual
accepted work, physical restart, Mac and extended workload gates remain open.

The [Object feature validation and anonymous export repair](OBJECT_FEATURE_VALIDATION_20261006.md)
adds native record checks across desktop, gateway and snapshots. The shared
corpus passes actual workerd with eight valid formats and 63 rejected formats;
95 focused Python and 332 JavaScript checks pass. Full native verification
confirms the repaired two-location synthetic export. This is structural and
privacy evidence; trusted model recomputation and Object admission remain open.
Application source `1d9fc98` passes all twelve executed public CI jobs, including
716 Python checks on each of Windows/Linux (two/31 platform skips), 332 service
checks without skips and the shared actual-workerd corpus. Native model inference
is intentionally skipped on ordinary updates. See the linked evidence above.
The [remaining work and planning estimate](https://github.com/Andrew454545/vision-community/issues/15)
summarizes release dependencies; the estimate is not a readiness claim.

The [official Object coverage importer](OFFICIAL_OBJECT_COVERAGE.md) now has
[actual native Windows and live staging evidence](OFFICIAL_OBJECT_COVERAGE_20261006.md).
All eleven native tests and the locked optimized metadata-validator build pass.
Five real panorama IDs/poses pass Google's official Generation 4 metadata,
the unchanged importer and actual staging D1 rollback/replay, followed by
independent primary readback. These are pending metadata, not indexed results,
device qualification or search credits. All twelve executed public CI jobs pass
at application source `7ba40c1` (640 Windows/Linux checks with platform skips and
259 service checks without skips). Retired v1 authority remains refused; old
rows require fresh trusted validation. Object admission stays closed.
Those older private CI attempts were blocked before runner startup. The newer
Mac comparison was subsequently completed through a private local handoff;
see [the 9 October cross-platform evidence](OBJECT_CROSS_PLATFORM_20261009.md).
GitHub Actions spending remains on hold.

The [offline Object reference checker](OBJECT_REFERENCE_CHECK.md) supports
checksum-pinned saved faces and all three detector lanes without account or
service access. It measures differences and keeps failures; it does not supply
Object production qualification or open admission.

The original private Mac artifact omitted portable values, and its historical
replacement workflow could not start. The completed 9 October local handoff
now supplies full indexes, actual search replies, source identities and traces
with independent file pins. These remain exploratory evidence. The service
explicitly reports Object readiness false and recognizes the closed
qualification endpoint.

**The project is not yet ready for production.**
This checklist describes the current state; check off a release gate only with
recorded evidence. Earlier failures and exploratory results remain separate.
The [guided work selection](GUIDED_WORK_SELECTION.md) and
[native installer packaging](NATIVE_INSTALLER_PACKAGING.md) support in
[PR #9](https://github.com/Andrew454545/vision-community/pull/9) and
[PR #10](https://github.com/Andrew454545/vision-community/pull/10) adds the
Scenes / Objects / Both controls and native Windows/Mac launcher candidates.
These do not close trusted lane admission, accepted production work, signed
clean-device installation or endurance gates. Neither signing account is set
up yet; the [account-holder setup](SIGNING-ACCOUNT-SETUP.md) explains what is
needed before signed downloads can be built. Public download links still point
to the older Windows Scenes preview and say so explicitly.
The [project audit](PROJECT_AUDIT_20261004.md) records corrected API admission,
request-size and error-handling defects, download consistency, tested Mac
controls and remaining release/capacity/privacy findings. Source fixes do not
update an older release ZIP or deploy the website.
The later [API protection update](API_PROTECTION_20261004.md) is tested and
deployed to confirmed staging with admission closed; its schema checkpoint
preserves the existing credit, queue and publication aggregates. Production
and the installed contributor remain unchanged.
The previous chronological development log remains in
[Git history](https://github.com/Andrew454545/vision-community/blob/a4b2630b1e8a049bbe79f904aad75376b6432c8d/docs/PRODUCTION_ACCEPTANCE.md).

## Boundaries and architecture

- Required release scope is Windows and macOS, with Scenes, Objects and Both
  available in the guided application on each. A Windows Scenes release alone
  does not complete this project. Track each combination in the
  [platform acceptance matrix](PLATFORM_ACCEPTANCE.md); experimental commands
  or another platform's tests do not establish beginner or unattended support.
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
| Full identical-input Windows Scenes | All nine 1,024-location trials at 1/2/4 threads complete; a separate verifier rechecks 110,592 raw tensor files and every comparison. Packed PC indexes and queries agree across all runs. All 108 top-ten/top-100 reference sets match; close-score orders and one selected view differ. Four threads are about 3.6 times faster than one in this frozen workload. | [Full comparison](FULL_WINDOWS_SCENE_COMPARISON_20261005.md) |
| Fixed starter inputs | Three fixed synthetic Mac repeats and fresh PC 1/2/4-thread checks finish all 112 locations. Preprocessing hashes match Mac; PC packed indexes agree across threads and meet unchanged experimental bounds. Full production qualification remains separate. | [Fixed check](FIXED_PC_CHECK_20261004.md) |
| Windows working-set observations | Three additional fixed 112-location runs record sampled sums around 797 MiB and peak committed memory around 957 MiB. All accounted processes were observed; owned cleanup passed and packed results stayed identical. This is not exact physical RAM, sustained capacity or thermal approval. | [Memory evidence](WINDOWS_SCENE_WORKING_SET_20261004.md) |
| Actual staging contribution | Corrected binary64 pose serialization; fresh 112-location qualification; new eight-location batch independently audited, published and credited once. Two earlier strict-policy submissions remain rejected. | [Admission](STAGING_SCENE_ADMISSION_20261003.md) |
| Actual staging search | Independently sealed snapshot of only those eight contributions passed native search, filters and exact response recovery after restart. Hosted API charged once; exact/account-recovery retry did not charge again; conflicting/unfunded requests were rejected. | [Admission](STAGING_SCENE_ADMISSION_20261003.md) |
| Hosted native operation | Real private Linux FP32 inference and restart, bounded eight-location audits, frozen capture/replay, lifecycle failure recovery and stopped compute with seal retained. Public/preview URLs, SSH and Container logs disabled. | [Startup](HOSTED_SCENE_CHECK_20261003.md), [budgets](HOSTED_SCENE_BUDGET_20261003.md) |
| Objects on Windows | All three pinned models processed six views; full one-location index and both native verifications passed. Eighteen frozen 1/2/4-thread detector commands agree within the sample. App-local compiler libraries were observed and checked. | [Objects](PC_OBJECT_CALIBRATION_20261002.md) |
| Actual identical-input Mac/Windows Objects | Published Mac CPU and CoreML-requested programs each repeat all three detector lanes exactly. The same six image bytes and eleven models match Windows; detection structures agree and measured score/box differences are retained. One location, no full-index/coverage/installed-gold/shared-pool qualification; newer private build blocked before runner by Actions budget. | [Private comparison evidence](MAC_OBJECT_REFERENCE_20261006.md) |
| Objects on Linux | Fresh Ubuntu CPU build passes 49 native tests. All 11 pinned assets, actual RF-DETR/YOLOE/OWLv2 six-view processing, identical within-run repeats, complete one-location index and full native verification pass. | [Linux evidence](LINUX_OBJECT_INFERENCE_20261003.md) |
| Banked accounting | Transactional publication/credit and search/result/debit; concurrency, replay and rollback tests. Actual hosted search used a separate disposable synthetic 100,000-unit balance; the eight real earned units stayed unchanged. Synthetic account deleted. | [Admission](STAGING_SCENE_ADMISSION_20261003.md) |
| Privacy and recovery | Anonymous recovery/deletion, revoked credentials, late scene-write fences, immutable R2 deletion receipts, real staging deletion-aware D1 restore. Offline published-index/catalog integrity checker rejects missing, corrupt or linked files. | [Privacy](ACCOUNT_PRIVACY.md), [restore](PRIVATE_RESTORE.md) |
| Beginner flow | Short README/website guide, guided Windows starter, qualification/service checks, saved-code recovery, pause/resume and private diagnostics. Website assets/privacy headers verified in staging. | [Service readiness](WEBSITE_SERVICE_READINESS.md) |
| Native Windows setup | Native private bootstrap, isolated verified Python, immutable source snapshot, 28 setup guards, 46 background guards, real fresh-download/page/paused worker under Restricted and 32 actual install/update/repair/controls/removal checks pass. All eleven CI jobs pass at application head `c037f24`; the earlier modal-window lookup failure is preserved. No inference, clean physical-device, endurance or release approval. | [Starter evidence](WINDOWS_NATIVE_STARTER_20261006.md), [Native background](WINDOWS_NATIVE_BACKGROUND_20261006.md) |
| Mac private setup | Actual Apple-silicon private interpreter download/tree and HTTPS verification, public-source snapshot, local guided window and 37 guards pass. No native inference, account, imagery or contribution; Mac runtime/background and clean-device acceptance remain open. | [Mac starter](MAC_PRIVATE_STARTER_20261004.md) |
| Mac background controls | Actual Apple-silicon guarded registration, immutable source/interpreter startup verification, safe idle replacement, private schedule/pause/resume window and nine exact runtime-link accounting pass. No native work, real account or imagery; actual restart/sign-in and endurance remain open. | [Mac controls](MAC_BACKGROUND_CONTROLS_20261004.md) |
| Current Mac CPU programs | Locked builds pass after the private Actions budget increase. Scenes completes all 16/112-location 1/2/4-thread indexes and searches with identical within-run results and all 18 reference query orders/views matching. Objects completes all three models, identical six-view repeats, a complete one-location index and full verification. Exact pins and independently verified reduced evidence are retained; neither lane is production qualified. | [Mac native check](MAC_CPU_NATIVE_CHECK_20261004.md) |
| Full current Mac Scenes | All nine 1,024-location 1/2/4-thread trials pass independent source/model/profile, transport and repeat checks. All 108 leading reference sets match; packed/raw/query results agree across all nine Mac trials. Close-score orders and one selected view differ from the reference. Four threads are about 2.31 times faster than one in this workload; production parallel/endurance qualification remains separate. | [Mac full comparison](MAC_CPU_NATIVE_CHECK_20261004.md) |
| Setup download recovery | Interrupted model/runtime files are retained and resume with validated byte ranges and complete checksum verification. All 543 local Windows tests, 24 targeted guards, one actual pinned HTTPS recovery and all seven hosted CI jobs pass. Native setup no longer automatically installs global Python packages. | [Download recovery](RUNTIME_DOWNLOAD_RECOVERY_20261004.md) |
| Slow-download recovery | A 30-minute elapsed body budget is checked between available HTTP fragments; saved prefixes survive expiry and retry. All 28 targeted and 547 local Windows tests plus a second actual pinned HTTPS recovery pass. All seven hosted CI jobs pass at `dc597dc`. | [Download recovery](RUNTIME_DOWNLOAD_RECOVERY_20261004.md) |
| Saved-delivery replies | Malformed acknowledgements preserve exact ready/pending payloads and trigger persisted delayed retries. Valid rejection and corrupt saved local data still stop for review. All 62 focused and 552 local application checks pass, including actual HTTP/SQLite recovery across fresh workers. All seven hosted CI jobs pass at `b25b9aa`. | [Recovery evidence](SAVED_DELIVERY_RECOVERY_20261005.md) |
| Desktop service replies | Credential-bearing API redirects are refused; JSON bodies are bounded even without declared length. Saved work survives these failures and resumes after persisted cooldown. All 66 focused and 564 local checks, all seven CI jobs and a credential-free actual HTTPS staging read pass. | [Reply protection](SERVICE_REPLY_PROTECTION_20261005.md) |
| Client privacy | Unknown service error text cannot become CLI/shared report content; Object payload labels omit private absolute paths without mutating native resume data or changing binary checksums. All seven CI jobs pass at `fbb203f`, including 574 Windows tests and 27 actual Mac privacy/restart guards. The local full-run setup failure and passing unchanged recheck are disclosed. | [Client privacy](CLIENT_PRIVACY_20261005.md) |
| Close-score ranking assessment | All complete assessed rankings preserve reference ordering beyond a proposed 0.00050 score gap; the largest observed inversion gap is 0.000179630. Proposed winning-score bound 0.00025 is fitted to controlled evidence. A separate 49,152-view PC calculation reaches 0.000333680, so that proposal cannot apply to every view. Neither approves other devices, selected views or live inputs. | [Gap assessment](SCENE_RANKING_GAP_ASSESSMENT_20261005.md) |
| Background worker | Native scheduled startup, idle handover and idle forced-exit/pause/resume verified. Installed schedule: medium 06:00–00:00, max 00:00–06:00 local; saved account, 30-minute service retry, sign-in/recovery triggers and one worker. | [Background processing](BACKGROUND_PROCESSING.md) |
| API protection | Supported routes are limited before body/database access, account budgets span read/write routes, previews have a smaller budget, and HTTP/scheduled requests never perform schema upgrades. Actual workerd checks and an explicit confirmed staging checkpoint/readback pass; this is not global load/cost approval. | [API protection](API_PROTECTION_20261004.md) |

Application source `4378f88` passes all seven Community CI jobs:
[tests](https://github.com/Andrew454545/vision-community/actions/runs/37257153471)
and [calibration](https://github.com/Andrew454545/vision-community/actions/runs/37257153520).
Actual Windows passes 543 tests in 339.854 seconds with two Mac-only skips;
the hosted-service suite passes all 232 tests plus the complete workerd checks.
Actual Apple-silicon Mac passes 41 setup/platform, 42 sleep/background and 12
control guards without skips, including guarded per-user registration, private
window ownership, preserved idle replacement and changed-source rejection.
Both calibration jobs pass 80 guards. Earlier dependency-order and lightweight
status source-format CI failures are retained with their corrected passing runs.
These close the recorded source defects, not the production release gates.

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

The [saved Object delivery update](OBJECT_DELIVERY_RECOVERY_20261005.md) gives
the default Object command and guided Scene client a shared restart-safe
journal. Fresh-process loopback/SQLite fixtures verify exact Object resubmission,
a single synthetic award, retained interrupted checkpoints and account/service
isolation. Both starters require the new module. This is source and delivery
evidence; released native Object qualification, hosted admission and
accepted long-running work remain open.
All seven CI jobs for `cbbc555` pass: 588 Windows checks with two
Mac-only skips, 588 Linux checks, 62 private Mac transport/delivery/Object guards
without skips, existing Mac setup/background/control and ownership checks,
232 service tests with complete workerd checks, and 80 guards on each
calibration runner. See the linked delivery report for run URLs and scope.

Andrew's merged guided choice, legacy schema upgrade and native package work
also pass all nine CI jobs for head `37aeca9`: 605 Windows and Linux client
checks, 237 service tests, the actual private Mac checks, both calibration jobs
and unsigned package builds. The Windows link-privilege fixture failure is
preserved; its corrected real-junction check passes without security changes.
CI tests GitHub's proposed merge with main; its package receipts pin checkout
`e3ba354e4341198b8c4285c90314ac386f941104`, not a released runtime. The
subsequent [native guide correction](GUIDED_WORK_SELECTION.md) names the app's
actual controls and preserves the folder-download instructions. These checks
do not establish clean-device startup, Object qualification or live endurance.
All nine CI jobs for the native-guide head `068682e` now pass: 609 Windows
and Linux client tests, 238 service tests, actual private Mac/ownership checks,
both calibration suites and unsigned package builds. The tested proposed
merge is `3b8eaa79bfab1234e069f35c758447f82678ce9c`; the final evidence commit
changes documentation only. Run URLs and preserved failure scope are in the
[delivery report](OBJECT_DELIVERY_RECOVERY_20261005.md).

## Release gates still open

The [installer integration](INSTALLER_INTEGRATION_20261006.md) incorporates
PR12 repair/lifecycle support and PR14 Mac lifecycle/signing automation.
Windows setup/removal contention is serialized and signing failures clean only
owned temporary credentials. The new **Remove VISION** Mac action verifies the
existing private interpreter/registration, stops the worker cooperatively,
unregisters startup and moves this app to Trash, retaining private work.
Actual Mac paused-worker removal, repeated removal and the native Trash API
pass. Complete guided/control close replies are also checked after correcting
an early-exit race. All eleven CI jobs pass for corrected application head
`40f6e2d`: 624 Windows and Linux client tests, 238 service checks, actual private
Mac guards, both calibration suites and unsigned packages/lifecycles. The
checked proposed main merge is `a9ab59e77fdae1ef69c9696c8cea8cd2c3992910`.
The linked report retains failed attempts and exact scope. Active accepted native work, signing/clean devices and
the other release gates below remain open.

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
  The subsequent continuation verified its first one/two/four-thread cohort,
  then stopped after the second two-thread index/search on a Windows resource
  reporting failure. The exact original API failure was not recorded. A repair
  passes 80 calibration guards; 24 fresh native searches pass actual accounting
  and cleanup. Independent offline recovery verifies four retained full indexes
  and preserves the original failed receipt. All packed indexes agree; four-thread
  raw tensors have 712 hash differences from one thread, with identical PC query
  results. The five remaining trials have now completed. A separate offline
  verifier passes all nine raw cases and comparisons, preserving four retained
  executions and five new ones. All 108 top-ten/top-100 reference sets match;
  eleven queries reorder close scores and one selects a different view in each
  repeat. The new [full comparison](FULL_WINDOWS_SCENE_COMPARISON_20261005.md)
  records exact pins, timings, tensor differences and limits. The independently
  running full PC comparison is complete, not production qualified. See the
  preserved [accounting recovery](WINDOWS_MATRIX_ACCOUNTING_RECOVERY_20261004.md).
  All six CI jobs pass at `741c6da`, including both 80-test calibration jobs and
  all 482 Windows application checks. The remaining finite comparison has a
  verified limited Windows task and its own byte-pinned copy of 276 public files;
  actual isolated Windows imports and all 80 guards pass. Its supervisor ran
  independently of Codex, rechecking retained cases before fresh native work.
  No production profile is approved by registration or these checks.
  All six Community CI jobs pass with the matrix at `5d1bb33`. A private
  format-compatibility check verifies a copy of earlier actual 128-location PC
  output, retains its raw tensors and confirms the original files unchanged;
  this runs no new native command. A separate finite Windows scheduled task
  downloaded/verified the exact completed Mac run and executed the matrix with
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

The [private Mac starter](MAC_PRIVATE_STARTER_20261004.md) adds a checksum-pinned
private interpreter, verified public-source snapshot and platform-aware guided
Scenes setup. Mac qualification cannot borrow the Windows released policy.
Actual Mac bootstrap/window CI is separate from native model, inference,
admission and unattended-processing acceptance; none of those gates is closed
by introducing the launcher.
All seven Community CI jobs pass at `f200767`, including 501 Windows application
tests without skips and the actual Mac setup/recovery/window check with 37
guards without skips. The private Actions budget increase now allows both Mac
Scenes/Objects CPU builds to pass in run 37236127846, attempt 2. The preserved
first attempt was refused before startup, rather than failing native code.
Exact current binaries also pass separate actual inference in run 37255958802:
Scenes completes both fixed inputs at 1/2/4 threads with all 18 reference query
orders/views matching; Objects completes all three models and a full native
one-location index. Independently checked reduced evidence records numerical
differences and coverage limitations; this is not contribution approval. See
[current Mac native evidence](MAC_CPU_NATIVE_CHECK_20261004.md).
The current CPU candidate's full 1,024-location comparison has started in
private run `37271532675`: three fresh trials each at one, two and four threads.
It reuses the exact completed supplied-reference archive. All one/two/four-thread
jobs finish all nine trials and pass independent transport/reference/repeat
checking. All 108 top-ten/top-100 reference sets match; close-score order and one
view differ. Packed indexes, raw tensor hashes and queries agree across all nine
Mac repeats. These finite jobs have completed; none grants production approval.
Staging and the existing public download remain unchanged.

- [x] Implement the guided Scenes / Objects / Both choice, saved lane cursor and
  serialized handover in Windows and Mac client/control source. Keep unavailable
  lanes clearly labelled; native apps and extracted downloads name their own controls.
- [ ] Complete separate trusted native qualification, accepted delivery and
  earned-credit evidence for each lane on both platforms. The default Object
  computer-check provider and hosted Object admission remain unavailable.
- [x] Complete actual clean-Linux inference/indexing with pinned assets and
  bounded shared threads; preserve the failed guard job and passing receipt.
- [ ] Complete clean-device runtime dependency checks and publish checksum-pinned
  Windows/macOS object assets; retain the existing Linux backend checks.
- [ ] Compare full RF-DETR, YOLOE and OWLv2 production paths with Andrew's
  reference on broader identical inputs. The small development pilot and
  detector thread study do not approve production inference or parallelism.
- [x] Implement the trusted historical official Generation 4 importer and
  verify five real source IDs/poses through native v7, local and actual staging
  D1 atomic rollback/retry and independent primary readback. The new authority
  is `official-gen4-historical-v2-exact-pano`; fixture/client camera labels are
  not accepted as evidence. [Measured check](OFFICIAL_OBJECT_COVERAGE_20261006.md).
- [ ] Exercise qualified Object assignment, resume, accepted publication and
  credit-charged search in staging with the released native profiles. The
  coverage rows are pending metadata; default qualification/admission is closed.
- [x] Validate bounded Object feature contents and rebuild anonymous export
  pointers while retaining native road flags. Verify shared adversarial cases
  in Python, JavaScript and actual workerd, plus independent native readback.
  [Evidence](OBJECT_FEATURE_VALIDATION_20261006.md).
- [ ] Audit object submissions with trusted native inference and independently
  approved feature bundles. Structural checks and publication digests alone
  do not show that the contributor ran the models.

### Days or weeks of unattended processing

The [native Windows background update](WINDOWS_NATIVE_BACKGROUND_20261006.md)
now implements automatic controls, owned immutable source/interpreter startup,
verified unlimited task duration and actual detached removal without PowerShell
or a policy change. All eleven CI jobs pass at application head `c037f24`,
including 32 actual Windows lifecycle checks under inherited Restricted and a
real paused private-Python Both worker. This closes the native-script dependency;
accepted native work, real sleep/sign-in/reboot and endurance gates remain open.

The [Mac background foundations](MAC_BACKGROUND_FOUNDATIONS_20261004.md) now
provide process-owned idle-sleep requests with actual Mac assertion/abrupt-exit
evidence, a per-user startup contract and a finite scheduled-recovery fixture.
Guided processing uses the platform-selected runtime path. These foundations
now have [guarded Mac controls](MAC_BACKGROUND_CONTROLS_20261004.md), immutable
startup verification and actual idle handover evidence. Trusted native work,
active-work handover, real sign-in/reboot and long-running acceptance below remain open.
All seven Community CI jobs pass at `f0df8b9`, including 515 Windows tests
(two Mac-only skips), 41 actual Mac setup/platform guards and 41 Mac sleep/
background guards without skips, plus the finite scheduled-recovery receipt.
These passing foundations leave the release gates below open.

- [ ] Implement and exercise macOS background startup/sign-in recovery,
  scheduled pacing, pause/resume and preserved account/batch/delivery state.
  Mac source controls and finite actual registration/recovery now pass; real
  sign-in/restart and accepted native work remain open. Exercise both lanes
  and Both on each OS without overlapping native writers or granting duplicate
  credits; verify shared CPU/memory limits and failures separately.

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
  The [offline privacy-storage check](PRIVACY_STORAGE_RECOVERY.md) now derives
  archives and permanent fences from a separately trusted current export and
  verifies actual cached bodies/metadata, preserving retained publications.
  All 52 focused checks and 385 local service checks pass on Apple-silicon Mac;
  the initial sandbox-only loopback refusal is preserved. This does not prove
  live R2 restoration, contribution/native-bundle recovery or secret rotation.
  Integration also passes 386 local Windows service checks, with two explicit
  file-symlink privilege skips; separate directory-junction checks pass.
- [ ] Reconcile credits and searches earned/spent after backup without replay
  awards or duplicate debits. The offline financial comparison detects changed
  balances, earnings/debits, replay keys and saved responses against a separately
  trusted current cutoff. It does not recover missing events or establish live
  credit recovery; see [the restore guide](PRIVATE_RESTORE.md).
- [ ] Validate complete live publication/storage atomicity and failure recovery,
  load/cost budgets and published retention rules before reopening production.
  The audited per-request schema work, unthrottled GET paths and absent
  production limiter binding are corrected in source; the confirmed staging
  rollout and five actual workerd protection fixtures pass. Measure larger
  workloads, global overload and costs before public load; Cloudflare's local
  permissive counters are not a global spending cap. See
  [API evidence](API_PROTECTION_20261004.md) and [the audit](PROJECT_AUDIT_20261004.md).

Credits have no added expiry or cap. A finite queue cannot supply infinite useful
work; an empty queue waits without re-crediting old locations. Preserve legacy
contributions and failures rather than deleting them to make a gate pass.
Confirmed historical catalog/reference provenance limits are recorded in
[the R2 inventory](REFERENCE_R2_INVENTORY.md).

## Continuing work

The [9 October cross-platform comparison](OBJECT_CROSS_PLATFORM_20261009.md)
measures fresh Windows/Mac native outputs on three distinct saved locations,
including nonempty Hot queries. Detection presence, quality masks, hit order
and stored PQ codes agree; small score/aiming differences are retained. Native
LF checkout fixes a content-derived quality identity mismatch. The failed
16-location Windows timeout and copied-index source-path refusal remain
preserved. These diagnostics assign no production tolerance or approval.

The [complete-batch acknowledgement repair](DELIVERY_ACKNOWLEDGEMENTS_20261008.md)
keeps saved Scene/Object payloads after partial or empty fresh success replies,
while preserving explicit already-published replay. All 58 focused local Windows
delivery/recovery checks pass without skips. This is delivery evidence; trusted
Object admission and accepted-work endurance remain open.

The account holder has prepared the protected `signing` GitHub environment;
[its recorded settings](evidence/signing-environment-20261008.json) contain no
secrets or variables. Actual signing enrollment and clean-device resources are
still missing. [PR #16](https://github.com/Andrew454545/vision-community/pull/16)
also corrects the stale installer migration note. No signing workflow was run.

The [offline Object search comparator](OBJECT_SEARCH_COMPARISON.md) adds pinned
query/filter and native-reply validation, with explicit rank/score/aim changes
and empty-result counts. The private frozen replay can exercise blur filtering
and all three search routes with bounded owned processes and native readback
before and after search. This does not establish protected/tunnel authority,
official coverage, gold provenance or trusted admission.

The [8 October replay separation](OBJECT_FROZEN_REPLAY_20261008.md) keeps private
saved-image diagnostics out of submissions and published snapshots. The offline
comparator reports their declared input identity without treating it as proof
of pixels, reference quality or qualification. The private native handoff is
prepared for local Mac execution; GitHub Actions spending remains on hold.

Use the open gates to select concrete work, preserve evidence, run relevant
checks, and commit/push to the authorized branch. Keep local processing
independent of Codex. The seven-hour development heartbeat should not poll a
healthy/waiting indexer or notify on unchanged status. Pause it only when the
agreed release requirements have evidence; never claim “perfect” without tests.
