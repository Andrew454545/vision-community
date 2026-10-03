# Production acceptance and continuation

Updated 2026-10-02 UTC. This checklist defines completion; "perfect" is not a
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

- Built private Windows and Linux CPU object candidates from the reference's
  object-sidecar. Each passes 48 native tests and actual layout startup. Both
  downloaded archives, binaries, observed dependencies and 14 source files were
  independently checked; Linux pins match Git blobs and Windows pins match the
  Git checkout with its explicit CRLF conversion. The Windows executable also
  starts on this laptop with a restricted environment and matching layout.
  All 11 pinned model assets were independently verified. Windows then completed
  actual RF-DETR, YOLOE and OWLv2 processing on one canary view, and a complete
  six-face, one-location object index with zero fetch/inference errors and full
  native verification (47.875 seconds for indexing in this isolated test).
  These are private exploratory candidates: clean-device dependencies, Linux
  inference, reference ranking comparisons, trusted Gen4 admission and measured
  shared thread budgets remain open. Updated private CPU candidates now pass
  49 native tests on both systems and confirm one shared inference pool with
  spinning disabled. Community CPU indexing overrides inherited thread settings
  with that single-thread budget and requires the runtime's confirmation on
  indexing and both verification passes; older runtimes stop with saved evidence.
  Mac reference process settings remain compatible. The complete 339-test local
  Python suite passes with one platform skip. All 18 frozen-image 1/2/4-thread
  object commands completed with identical output values and view rankings in
  the one-location sample. The actual Community command then indexed a location
  at one thread/25% duty in 817.953 seconds and passed both native verifications.
  CPU runs now checkpoint after each location before resuming. The dependency
  inventory exposed four compiler DLLs requiring app-local packaging. The new
  private Windows/Linux builds pass 49 native tests and their archives, source,
  binaries and build helper were independently verified. Actual Windows model
  processing loaded all four compiler DLLs and DirectML.dll from the package
  folder with matching checksums; all six frozen-view output values and rankings
  still match the earlier Windows candidate exactly. No global installation was
  needed. Clean-device and reference admission remain open. See
  [the object report](PC_OBJECT_CALIBRATION_20261002.md).
  These measurements remain exploratory; no production object gate was opened.

- Unified hosted object assignment, resumed leases, publication/download authority
  and paid-search validation around the same Gen4 generation and complete
  lowercase SHA-256 receipt. The local service enforces the same requirements.
  Incomplete, nonhex, uppercase or blob proofs cannot authorize work; losing
  proof after assignment blocks resume/publication before artifacts or credits.
  Actual local workerd/D1/R2 checks pass. This closes an inconsistent receipt
  check; trusted historical coverage import and object inference remain open.

- Added independent private R2 account-deletion receipts, with immutable
  creation, bounded checksum readback before acknowledgement, a durable retry
  outbox and explicit confirmed-resource configuration. Storage or acknowledgement
  failure preserves revocation; replay cannot debit twice or restore access.
  152 JavaScript checks pass, including six archival fault/recovery cases.
  Actual local workerd/D1/R2 verifies the API, lost-response replay and scheduled
  recovery with synthetic accounts. Live staging rollout now passes anonymous
  deletion, revoked recovery/session, exact receipt replay and a single debit.
  Independent private R2 preview verification matches the canonical receipt
  checksum and resource; all 13 website assets and privacy headers still pass.
  The offline restore tool also supports an explicit isolated staging profile
  and rejects mixed resource mappings before changing accounts (17 SQLite/CLI
  checks pass). The isolated live deletion-aware database restore now passes:
  seven independent R2 receipt preview checksums matched the complete frozen
  current source; repaired older data was imported in one 103-statement D1
  query batch while maintenance remained closed. Live privacy fences, revoked
  session/recovery, exact deletion replay, retained balance/search and final
  fixture deletion passed. All 13 assets still match after reopening. Two
  provider bulk-import failures are preserved; production was unchanged.
  A new offline SQL preparation tool preserves table/data/fence ordering,
  private text/blob values and 64-bit automatic-ID high-water marks. Ten tests
  and actual workerd replacement/rollback checks pass. Complete production
  disaster recovery, R2 artifact restoration and retention remain open. See
  [the restore runbook](PRIVATE_RESTORE.md).

- Published and independently verified the private Linux OCI images in the
  confirmed Cloudflare registry. The smaller image stores each model payload
  once (893,888,000-byte image archive); preparation is ready. The tested startup
  correction is deployed privately. Three one-time checks failed before model
  processing; the later two record container exit code 1, and the third exited
  before the authenticated bootstrap diagnostic became available. All reports
  are preserved and triggers removed. This does not yet identify a Python fault.
  A bounded offline launch probe is tested separately and refuses sealed work.
  The later private hosted check passed Python3.12.15/runtime/model identity,
  actual loopback HTTP and separate service/operator authentication, using
  generated disposable credentials and no Internet. Normal startup then exited
  with code 1 before model processing. Its report is preserved, compute stopped
  and triggers removed. The earlier HTTP-only schedule had no start marker or
  receipt and establishes no execution. The controller now uses the immutable
  image's direct server command; a separate hosted retry is still required.
  These checks grant no production admission or hosted model/restart claim.
  A later direct-server check actually executed, passed isolated HTTP/authentication,
  then exited with code 1 at normal startup. Its report is retained and its cron
  removed. A separate bounded private diagnostic now executes the image's exact
  main program with the existing credential bindings, retains only fixed error
  codes, verifies HTTP authentication and stops its process group. Local real
  subprocess tests, 175 JavaScript checks and actual workerd route/scheduling
  checks pass. Its later finite scheduled window produced no start marker or
  result; the trigger was removed and read back empty. This establishes no
  server execution. Its hosted result is still required; scheduling is not execution.
  One-time checks require a short absolute UTC execution window and a create-only
  marker; expired or duplicate deliveries cannot restart compute. A failed final
  shutdown or incomplete model receipt cannot be reported as a passing check.
  Completed stage receipts retain independently inspectable hashes and resource
  measurements; a stage-storage failure or conflict cannot report a pass.
  Added a private
  Container controller with streamed bundle checks, durable activation pointers,
  restart/eviction rehydration, one shared execution slot and bounded idle
  shutdown. The existing staging namespace is preserved; public routes, SSH
  and invocation logs remain disabled. 146 JavaScript tests and 24 actual
  workerd route/binding checks pass. Three additional actual workerd SQLite
  alarm checks prove delivery, renewal and active-operation deferral using
  synthetic compute; they are included in CI. All five GitHub jobs pass at
  `58e7eed`, including 330 Windows Python tests with no skips;
  full local gateway/verifier checks pass. The first one-time private hosted
  check failed during initial startup; its report is preserved and its trigger
  removed. A tested correction makes Python settings explicit, enforces a
  separate startup deadline and preserves redacted lifecycle diagnostics. A
  durable idle alarm is tested independently of the monitor's eviction delay;
  it preserves seals across eviction and defers during an active native operation.
  The fixed bootstrap and offline probe pass ten Python checks and retain only
  allowed startup stages/codes/numeric errno values; it grants no readiness.
  Hosted model inference and restart verification still need a successful retry. Bundle restoration
  is tested locally; live qualified bundle restoration is still required.
- The final packaged one- and two-thread candidates each completed their
  112-location check and three fresh 1,024-location repetitions, with zero errors
  and complete masks. Together with the completed four-thread candidate, this
  finishes the full exploratory 1/2/4-thread trial matrix. Median batch times
  were 1,344, 827 and 1,186 seconds respectively; these were not isolated speed
  tests and do not establish a maximum production profile. The two-thread executable
  and all five packaged DLLs were observed loaded from the pinned package and
  matched to the build receipt. This establishes that process's library identity,
  not quality, representative speed or a production parallel profile.
- The exact final Windows package also completed nine frozen-image replays
  (three each at 1/2/4 threads). All 81 comparisons with the supplied Mac packet
  agree on ordered locations and selected views; settings repeat consistently
  and packed native indexes/search results agree across thread counts. The
  controlled sample has 16 locations, so broader quality coverage, measured
  resource limits and admission remain open. See
  [the calibration report](PC_CALIBRATION_20261002.md).
- Shortened the README, setup guides, PC screen and website instructions.
  The website guide has 160 visible words, with search and troubleshooting
  behind optional sections. Desktop, phone and expanded-help rendering pass.
  All five GitHub jobs pass at app revision `d27aba8`; 24 launcher/bootstrap,
  34 indexer and six readiness tests also pass locally. Staging deployment
  `08752be5fd0848349fbb2e643685ceb1` serves all13 matching public assets with
  the existing backend, bindings and privacy/security headers preserved.
  Account-code and qualification gates remain required.
- Final packaged Windows/Linux native builds pass69 tests and their binary,
  library and source pins have been independently verified. The final Windows
  four-thread candidate completed its112-location check and three fresh full
  1,024-location trials with zero errors. It remains unqualified: the final
  full comparison quality and runtime policy are still required. Private Linux image CI also built and checked actual
  payload/layout/auth startup. Independent retrieval verified all12 OCI blobs,
  the real runtime payload, helper pins and host source. GitHub's recorded
  temporary merge and tested branch have identical complete source trees.
  Hosted model inference remains pending; image identity does not open gates.
- Integrated Andrew's beginner Windows starter, four-step desktop flow and
  simpler website without weakening saved-code or PC qualification gates.
  The isolated [test website](https://vision-community-staging.visioncommunity.workers.dev/)
  now serves the new guide. All13 hosted assets match source hashes, including
  the guide's expected same-site canonical redirect and a same-site stylesheet
  that renders under the existing strict content security policy. Live disposable account
  recovery/deletion/revocation and outage checks pass; no production account,
  credit, contribution or bucket was changed. Staging identifies itself and
  reports its own bound bucket. Fresh environments no longer silently create
  prototype queue rows; deliberate local demonstrations may opt in with
  `SEED_PROTOTYPE_LOCATIONS=1`. Integrated Windows317 Python tests ran with
  one skip; all106JavaScript tests, three Worker builds and complete local
  gateway/verifier checks pass. Native bindings and approval policy are still
  unset, so this does not establish successful hosted contributions/search.
- Independently verified Andrew's new private frozen scene reference and
  full Mac calibration/service packets. Three additional real Windows fp32
  repetitions on his exact frozen RGB match all27 paired native query orders
  and selected views. All64NCHW inputs are identical; normalized worst relative
  L2 is0.0000361704. Packed embedding bytes differ. A separate three-run test
  of the supplied reconstruction's ordinary CPU int8 graph changes all27
  query comparisons and has worst normalized cosine0.877263. Reject that
  reconstruction profile for reference parity rather than relaxing bounds
  enough to admit it. An explicit ordinary fp32 path and CPU thread-pool fix
  passed all68 private native checks and a locked Windows build. The new ordinary
  112-location CPU fp32 check and first two full1,024-location trials completed
  with no errors. The third timed out after30minutes, at640logged locations but
  only16checkpointed. Its original report/index/logs are preserved; recovery
  on a separate copied index completed all1,024locations with zero errors and
  confirmed the original files stayed unchanged. Recovery is reported
  separately from a fresh repetition. Its Mac canary
  comparison has409/448 identical packed views and
  minimum cosine0.999797169; separate live imagery is not a frozen comparison.
  This is not activation or admission. The older
  distributed Windows binary is a different artifact and was not identified
  by this graph experiment. Full ordinary-path/device/parallel qualification
  and a measured policy remain open; raw reference data stays private.
- Client/auditor inputs now explicitly select fp32 and require the native log to
  confirm both the graph and requested ONNX pool. An old runtime that silently
  ignores the input cannot complete qualification or approve an audit. The host
  explicitly bounds all four thread variables. Native audit batch capacity is
  independent of pace, default8; larger limits require measured host capacity
  inside the50-second audit budget and matching Worker/policy configuration.
  The new checks require new runtime/helper/policy pins; no admitted release
  profile or hosted native service is created by changing these helpers.
  Actual pinned CPU recomputation of16locations completed in47.09seconds during
  concurrent calibration, inside the50-second native limit but with little
  spare time. This supports reducing the default rather than assuming128fits.
  All320 Windows Python tests ran with one skip and107JavaScript tests pass;
  the actual local workerd/D1 checks exercise the bounded lease and recovery.
  A Windows rejected-request socket reset exposed during tests was fixed with
  a brief bounded drain of small unambiguous bodies; large or ambiguous bodies
  are never drained. Original failed checks remain in private evidence.
- Long client batches now save every completed chunk, reducing lost progress
  after power loss. Local and private hosted saved-search inputs explicitly
  request the same fp32 image graph as indexing. The hosted adapter checks the
  actual bounded CPU pool and, for image examples, the actual fp32 graph before
  accepting results. A wrong graph or old runtime returns unavailable without
  credit settlement. The corresponding native saved-search graph propagation
  and cache regression are in private PR11. Its Linux CPU build passes native
  tests, locked release, actual startup/layout and shared-library checks;
  final Windows build/profile/distribution qualification remains pending.
  The previous Windows package was rebuilt with all five pinned runtime DLLs
  from the explicit build-runner redistributables; those files are bundled,
  never installed globally.73 targeted Windows recovery/search/audit checks
  pass. A deliberately incorrect synthetic image-mode fixture failure is
  retained and corrected to respect the native query's minimum similarity.
- Nine new actual frozen-RGB scene repetitions completed at bounded1/2/4ONNX
  threads, three per setting. All81 paired Mac query comparisons agree on
  ordered locations and selected views. Each thread setting repeats exactly;
  the packed indexes/native searches also agree across the three settings.
  Five raw views differ slightly at four threads (maximum normalized relative
  L2 about0.000000158), without changing those packed results. These16-location
  instrumented studies ran alongside other processing and establish neither
  representative speed nor a production parallel profile. Full-size parallel
  quality, quiet speed/resource measurements and final installed runtime
  qualification remain separate requirements.
- Added reproducible private scene runtime packaging from independently pinned
  native build/model/country inputs and a private Cloudflare bridge to an
  operator-configured native HTTPS ingress. Packaging preserves executable
  permissions/model timestamps, checks every payload and writes the runtime
  manifest last. The bridge retains exact query bytes, injects its own host
  secret and bounds upstream reads/time without adding credit settlement.
  The real Mac development runtime and retained 16-location records pass the
  complete local workerd/D1 gateway through this bridge: exact native
  IDs/scores/views after existing filters, four queries, three recoveries without
  extra inference/debit, scientific coordinates and no debit for outage or lost
  contributor ownership. The initial bridge framing failure is preserved and
  fixed. Eight new packaging and nine transport tests are included; the Python
  suite ran 304 tests with 15 Windows-only skips and all 97 JavaScript tests
  pass. Both Worker builds and the separate local gateway/verifier checks pass.
  All accounts/publications/credits/storage are disposable local fixtures.
  Live native hosting/HTTPS, verifier policy and Windows qualified workload
  remain open. See [NATIVE_SCENE_SEARCH.md](NATIVE_SCENE_SEARCH.md).
- Delivered the requested Mac development scene reference privately: the same
  unchanged scene source, exact 16-row input and four canonical models, one
  actual capture and three fresh frozen-RGB replay/index/native-search runs.
  The build passed 65 native tests. Every scoped tensor/index/mask/search output
  repeats identically on this Mac, with zero fetch/inference/incomplete errors.
  The complete frozen-input packet, native artifacts and receipts are available
  to the contributor. This resolves the requested reference-data handoff;
  installed-reference correspondence, full calibration/canary, cross-provider
  bounds and parallel acceptance remain the contributor's engineering decisions.
- Implemented the private native scene search adapter from independently sealed
  contribution snapshots to the real saved-index engine, with strong runtime
  pins, unchanged record bytes/ordinals, fresh private query caches, bounded
  execution, first-error reports and no shell/credential inheritance. Fifteen
  helper checks cover trust, filters, HTTP, killed timeouts and recovery. Actual
  16-location native HTTP results match direct search rankings/scores/views;
  the complete local workerd/D1 flow passes real search settlement and replay
  without extra inference/debit, scientific-coordinate fingerprints, outage
  and contributor-removal rejection. All accounts/publications/credits are local
  fixtures. No live resource or installed worker changed. See
  [NATIVE_SCENE_SEARCH.md](NATIVE_SCENE_SEARCH.md); hosting, live export, full
  quality/device/parallel qualification and Objects admission remain open.
- Andrew accepts our findings and engineering decisions and withdrew his separate
  independent verification/sign-off requirement in PR #2. Do not wait for an
  approval or request raw-result uploads for that withdrawn requirement. This
  authorizes progress; it does not create absent quality/endurance evidence.
- Added and exercised a separate private native scene capture/replay path.
  It preserves actual four-view thumbnails, model inputs, raw outputs and
  normalized vectors before native packing; replay never refetches imagery.
  A real Windows saved-search crash exposed a large stack buffer, now moved
  to the heap without changing the hash algorithm. All 65 native checks pass,
  including a small-stack regression. Three fresh 16-location CPU fp32 scene
  repetitions have identical tensor/index hashes and native search rankings,
  scores and selected views. Native search of the original captured index and
  reopening a copied completed checkpoint also pass. Original failures and
  tiny raw checkpoint metadata round-trip differences are preserved privately.
  This is PC development evidence; matching Mac scene repetitions have now
  been supplied above. Installed reference correspondence, full
  calibration/canary and parallel admission
  remain open. No installed worker, account, upload or live resource changed.
- Completed the private frozen-input object pilot: three actual Windows CPU
  repetitions against three Mac repetitions, using 16 locations and nine fixed
  native queries. All 27 paired query results matched ordered locations, hit
  counts and selected views. Both platforms repeated consistently; cross-platform
  bytes and some raw model outputs differ. The independently checked report
  preserves those differences and sets no acceptance tolerance. This small
  development study does not qualify installed VISION equivalence, Scenes,
  the full calibration, a device or a parallel profile. Its private comparison
  helper passes 34 offline checks and all five Windows/Linux/Mac CI cells.
- Received a buildable scene development reconstruction and verified read-only
  access to the two Community pose catalogs against independent manifest/sample
  hashes. The catalogs overlap and contain neither original embeddings nor
  frozen imagery; they are work inputs, not published searchable contributions
  or Gen4 authority. The recovered scene path has matching frozen Mac
  repetitions supplied above; installed-reference/text/ranking correspondence
  remains open. No catalog was imported
  into search and no live resource or installed worker was changed.
- Added a private operator runner for three fresh native object repetitions
  using independently pinned frozen RGB, models, query settings and development
  build receipts. It preserves native index/search outputs, ranked results,
  explicit face/model/provider coverage and incomplete failures, with separate
  uninstrumented timing runs. All 26 offline helper checks pass locally;
  synthetic/mocked orchestration and actual native input/model-contract rejection
  checks are prerequisites, not real model repetitions or qualification. The
  original failures remain private. Full scene reference repetitions,
  semantic text boundary evidence, numerical/ranking bounds and the
  parallel profile remain open. Detailed source, fixtures and receipts stay in
  the private technical channel; no installed worker or live deployment changed.
- The website now checks service status and the required scene qualification
  contract before showing/copying an indexing command. Missing or legacy
  capabilities fail closed, Objects/Both remain unavailable during portable
  validation, and deliberate outage/recovery checks preserve saved credits and
  browser journals. Unreadable/invalid successful search responses preserve
  the original request key for paid-result recovery. All 88 JavaScript checks
  pass locally, including six new availability/recovery checks. The page controls were exercised with a disposable
  read-only synthetic browser fixture; this is not live deployment or model
  qualification. See [WEBSITE_SERVICE_READINESS.md](WEBSITE_SERVICE_READINESS.md).
- Added immutable scene write intents and create-only R2 uploads so account
  deletion can discover uploads before a candidate exists. Cleanup permanently
  fences unpublished keys, blocks delayed payload recreation, preserves published
  indexes and checks lease/account provenance. Offline restore requeues journaled
  uploads; migration and repair failures roll back. All 82 JavaScript tests and
  the complete Worker build/local workerd/D1/R2/verifier checks pass, including
  real conditional quarantine/final writes on both sides of deletion. Live
  rollout must stop/drain old unconditional writers; object uploads, historical
  orphan retention and live storage/restore acceptance remain open. See
  [ACCOUNT_PRIVACY.md](ACCOUNT_PRIVACY.md).
- Incorporated Andrew's [current Mac reference report](MAC_REFERENCE_STATUS_20260930.md)
  from PR #3 at `351548b`. It records executable/model identities and observed
  settings, and explains why the installed production path cannot yet establish
  identical-input repetitions. Source/build provenance and native export/replay
  access have been requested on PR #2. Numerical/ranking bounds and parallel
  production qualification remain unestablished; this is documentation evidence,
  not a completed model-quality comparison.
  Andrew's later PR #2 reply reports a tested native object development build
  with a new identity, an incomplete recovered scene checkout, and a private
  technical handoff. Those source/access details stay in the private channel;
  the handoff has now been located and read. An isolated Windows CPU runner
  passed the native object's locked tests, release build and v4 index-layout
  check, using the original object source/lock hashes verified against the Mac
  build receipt. At that earlier step this established startup/layout, with no
  model inference or production qualification. The laptop still lacks native build tools. After
  an explicitly authorized private download, the checksum-verified
  unchanged-source Windows binary ran its v4 layout check on this laptop and
  matched the hosted build receipt. The small object and scene studies recorded
  above subsequently exercised real inference; full installed-reference
  comparisons and production qualification remain open.
  Detailed source/access information and build artifacts remain private.
  He also reports his local workers resumed at 1% duty with scheduled increases
  disabled. The earlier maximum settings are a dated observation, not current
  worker status or a new comparison result.
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
  All five jobs subsequently passed at `e67c898`, including 269 Windows Python
  tests. Recheck the final PR revision after further changes.
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
  journal rows and evidence can still grow. An optional `-StorageLimitGB`
  allowance pauses new work using logical sizes across the private folder;
  saved deliveries and audits still recover for the original account. Metadata
  scans, restart recovery and growth during downloads/PC checks/batches are
  tested, including a real SQLite journal and disposable HTTP service. The
  setting defaults to disabled and is not a hard quota: an active operation
  and recovery/status writes may exceed it. The 5 GB free-space guard always
  remains. Neither guard deletes files or supplies a cleanup policy. Preserve
  unsent/rejected work and account recovery while resolving storage pressure;
  live disk growth and long-run acceptance remain open.

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
- [x] Complete the final packaged 1/2/4-thread exploratory full trials and
  16-location frozen numerical/native-ranking studies. Evidence and limits are
  recorded in [the calibration report](PC_CALIBRATION_20261002.md).
- [ ] Define quality/ranking tolerances, broaden fixed-input coverage, measure
  representative resource budgets and approve only measured configurations. Compare numerical
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
  Account deletion, database fences and late scene-upload protection are tested locally; live
  production rollout, complete database/storage recovery, wider orphan cleanup
  and provider logging/retention review remain outstanding. Independent private
  deletion-receipt storage now passes live staging verification. The
  deletion-aware staging database restore passes with synthetic accounts and a
  complete independent receipt inventory. It does not satisfy full production
  recovery of storage, credits earned/spent after backup or retention.
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
  The native scene adapter, runtime packager and private bridge are implemented
  and exercised locally on Mac/Windows. A private Container controller and
  named engine/verifier/operator service bindings are deployed in staging;
  actual hosted inference, measured policy activation and a live contribution
  snapshot remain unverified. See the
  [private host instructions](../deploy/cloudflare/native-container-host/README.md).
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
