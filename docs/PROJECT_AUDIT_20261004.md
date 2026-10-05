# Project audit — 4 October 2026

**Release decision: keep production contribution admission and new paid search
closed. The required Windows and Mac Scenes / Objects / Both release is not
complete.** This is a development audit and recorded test evidence, not an
independent penetration test or a claim that months of operation have passed.

The source fixes are in `1572434`; the test dependency-order repair is in
`a698313`. Mac controls are in `e9c3130`. These changes are committed to
`codex/windows-production-readiness`. No website deployment or release ZIP was
updated during this audit. Existing staging evidence remains historical.

Follow-up: [API protection and explicit database maintenance](API_PROTECTION_20261004.md)
correct the schema/GET/production-binding findings below. All seven CI jobs pass
at `1a8e2d1`, and the tested code and all 13 assets are read back in confirmed
staging with admission closed. Production, the installed contributor and older
release ZIPs are unchanged. The remaining release and capacity gates stay open.

## Confirmed problems corrected in source

| Priority | Finding and consequence | Correction and evidence |
| --- | --- | --- |
| P1 | Hosted Objects endpoints could assign/publish structurally valid work without a trusted native object audit, even though the UI labelled Objects unavailable. This was an admission gap; the audit does not establish that it was exploited. | New hosted object leases, publications and searches return `object_verification_unavailable` before artifacts, credit or inference. An already paid, owned result remains recoverable without another debit. Strict official Gen4 checks remain in the explicitly scoped offline prototype. Actual workerd exercises hosted URLs with the test flag present and confirms refusal; the flag alone cannot enable a hosted origin. |
| P1 | The public API read an entire request with `arrayBuffer()` before applying its 8 MiB limit. An absent or dishonest length header could consume memory before rejection. | Bound streaming reads by actual bytes, read count and a 60-second deadline; reject malformed UTF-8, non-object JSON and inconsistent lengths. Cancellation cannot hold the error response indefinitely. Six boundary guards and an oversized request without a length header in actual workerd pass. |
| P2 | Async account-creation/recovery writes returned outside the API's error handler. A rejected database write could escape the fixed JSON failure contract. | Await both operations inside the handler. Real SQLite-backed regression fixtures inject failures and confirm redacted `internal_error`, no partial account and unchanged recovery token/balance. |
| P2 | The website's main download button still selected the 2 October Windows preview while the short guide and README selected the recovery preview. | Align the button with `windows-starter-preview-20261004-recovery`. This is a source correction; the deployed button has not been read back in this phase. |
| P1 | A malformed service acknowledgement could retire saved local delivery data using negative counts or contradictory pending/rejected flags. This is a source defect, not evidence of actual lost work. | Validate counts, state and delivery identity before updating the journal. Invalid replies keep the exact payload and retry after persisted cooldown; explicit rejection and corrupt local data still require review. All 62 focused checks, including actual HTTP/SQLite recovery across fresh workers, pass. See [saved-delivery recovery](SAVED_DELIVERY_RECOVERY_20261005.md). |

The first CI run at `1572434` failed because the new full-Worker regression
imported `jpeg-js` before the workflow installed its local dependencies. The
failure is retained. `a698313` moves the existing local install before tests;
it adds no global installation and does not change application behavior.

## Areas reviewed

| Area | Evidence and limits |
| --- | --- |
| Processing and qualification | Runtime/model/helper pins, source/interpreter checks, platform-selected assets, fixed canary inputs, native ownership, reference transport and comparison reports reviewed. Existing finite Scenes/Objects pilots do not approve a production profile. |
| Unattended operation | Windows task ownership, Mac registration/readback, cooperative handover, pause/retry/attention markers, storage accounting and caller-owned cleanup reviewed. New Mac controls have an actual OS fixture; native accepted work, sign-in/reboot and endurance remain open. |
| Contributions and storage | Lease/publication fences, scene verifier boundaries, D1 write intents, create-only R2 writes and late scene-write deletion fences reviewed. Objects requires native admission; it is now closed at the API. No bucket was read or modified. |
| Search and credits | Authoritative published-hit validation, transactional saved response/debit, replay, concurrent settlement, rollback, deletion and recovery reviewed. The small staging experiment establishes integration, not full-corpus cost, capacity or reference parity. |
| Privacy and recovery | Fixed public errors, local-window authentication, secret handling, account deletion archives, deletion-aware restore, browser journals and delivery outbox reviewed. Source-name checks are not proof of anonymity in Git history or provider records. |
| Hosting | Checked-in production/staging bindings, immutable private native bundle/image identities, retained activation pointer, alarms and restart handling reviewed against current official types/docs and the pinned Wrangler schema. Actual workerd checks are offline; no fresh live-resource or billing audit was performed. |
| Beginner experience and packaging | Download/guide consistency, Scenes-only preview labels, private setup, background controls and failure wording reviewed. Guided Objects/Both, signed distributed Mac/Windows packages and clean-device beginner acceptance are incomplete. |
| Delivery and development | Public/private branch boundaries, build workflows, source versus released ZIP versions and preserved failure reports reviewed. After the budget increase both current Mac CPU builds and separate actual model/index checks pass; Scenes completes fixed 16/112-location inputs at 1/2/4 threads, with all 18 reference query orders/views matching. Objects completes all three models and full one-location verification. See [Mac native evidence](MAC_CPU_NATIVE_CHECK_20261004.md). |

The loopback prototype remains an explicitly local developer tool. Its cheaper
demo search and legacy diagnostic routes must not be hosted or presented as
the public contribution/accounting system. No code in that prototype grants
approval to the hosted service.

## Remaining findings and release gates

P1 here means a release blocker; P2 means work required before general public
operation. These priorities are engineering judgments, not CVSS ratings.

1. **P1 — Runtime/reference approval:** the full identical-input PC matrix now
   completes all nine trials, independently verified from retained raw files.
   All top-ten/top-100 reference sets match, while close-score ordering and one
   selected view differ. See [the full comparison](FULL_WINDOWS_SCENE_COMPARISON_20261005.md).
   The [gap assessment](SCENE_RANKING_GAP_ASSESSMENT_20261005.md) measures all
   ranking inversions and proposes an explicit score bound; selected-view
   margins and independent release validation remain required.
   Explain these and held-out differences, derive production bounds and pin
   exact distributed runtime/helpers. All nine current Mac full CPU trials now
   pass independent transport/reference/repeat checks;
   earlier failures remain preserved. Live audits
   also need independently trusted imagery identity. Different fetched photos
   must not excuse forged embeddings or count as runtime error.
2. **P1 — Both platforms and lanes:** distribute the tested current Mac candidates;
   finish guided Objects and Both on Windows/Mac, separate qualification and
   earned-credit recovery, and broader detector comparison. A trusted official
   Generation 4 importer and native object submission audit are required before
   reopening the object API. Windows x64 and Apple silicon evidence does not
   establish Intel Mac or Windows ARM support.
3. **P1 — Maximum and endurance:** qualify shared parallel CPU/memory budgets,
   then exercise active batch handover, real schedule boundaries, sleep/wake,
   restart/sign-in, network loss and a sustained accepted workload on both OSes.
   Maximum currently removes deliberate pacing rests; it is not an approved
   all-core mode. Computers cannot process while asleep or powered off.
4. **P1 — Distribution and deployment:** publish verified signed packages with
   clear platform/lane support, repeat setup on clean devices with a beginner,
   and deploy/read back the tested source in confirmed staging before any
   production rollout. Source tests do not update an immutable older ZIP.
5. **P2 — API cost and abuse protection:** the follow-up removes HTTP/scheduled
   schema upgrades, adds shared read/write and separate preview limits before
   body/database work, and requires all three bindings in both hosted configs.
   Explicit schema checkpoint, outage/refusal and actual workerd quota checks
   pass; the staging rollout preserves credit/queue/publication aggregates.
   Before public load, measure representative traffic and hosting cost. Local
   permissive Cloudflare counters do not establish an exact global quota or
   spending cap; see [the follow-up evidence](API_PROTECTION_20261004.md).
6. **P2 — Hosting scale and recovery:** measure larger contributor-only search
   snapshots, updates during searches, eviction, overload, latency and cost.
   Rehearse complete R2/native-bundle/secret restore plus credit events after
   the backup cutoff. Existing deletion-aware D1 restore and financial mismatch
   detection do not recover missing events. Plan historical orphan cleanup and
   retention without deleting unverified or legacy evidence to obtain a pass.
7. **P2 — Long-term operation:** establish bounded retention for successful
   local work, private failure reports and cloud artifacts; verify disk growth
   over time. Add privacy-safe aggregate failure/cost alerts and a supported
   update/credential-rotation procedure. Optional storage checks are neither
   cleanup nor a hard disk quota. Audit provider logs, names and retention
   separately from the anonymous UI.

The private repository Actions budget block is resolved: both current Mac CPU
builds and finite actual model/index checks pass after the increase. The remaining
release gates require further observed engineering evidence. No API token or separate
owner declaration of production approval is needed for the finite checks.

## Validation

- Local Windows: all 527 application tests pass in 359.037 seconds; eight
  skips are two Mac-only cases and six local filesystem-link restrictions.
- Actual Windows CI at `1572434`: all 527 application tests pass in
  376.495 seconds with only the two Mac-only skips.
  Final CI at `a698313` passes the same 527 tests in 291.030 seconds with
  the same two skips.
- Final local hosted-service suite: all 220 JavaScript tests pass in
  4.259 seconds. Corrected Linux CI passes all 220 in 2.954 seconds, all six
  Wrangler dry-run builds, the complete local D1/R2 gateway, verifier boundaries,
  deletion archives, maintenance, restore SQL and private native-host checks.
- Actual Apple-silicon CI at `a698313`: 41 setup/platform guards in 3.124 seconds,
  41 sleep/background guards in 0.748 seconds and 12 control guards in
  2.206 seconds pass without skips. Bootstrap/window, finite scheduled recovery
  and guarded control receipts pass. These create no real account, retrieve no
  imagery, run no native inference and upload no contribution.
- Both 80-test calibration CI jobs pass at `a698313`. Calibration guards do
  not replace completion of the independent full reference matrix.

All seven final application-source CI jobs pass at `a698313`: [application,
Mac and Cloudflare checks](https://github.com/Andrew454545/vision-community/actions/runs/37249752134)
and [Windows/Linux calibration guards](https://github.com/Andrew454545/vision-community/actions/runs/37249752141).
Logs, including the
initial CI failure, are preserved privately outside Git. Native reference
images, vectors, credentials, balances and local account files are not attached
to this public report.

Official references used for the hosting review: [Workers best practices](https://developers.cloudflare.com/workers/best-practices/workers-best-practices/),
[D1 database API](https://developers.cloudflare.com/d1/worker-api/d1-database/),
[R2 consistency](https://developers.cloudflare.com/r2/reference/consistency/),
[Durable Object state](https://developers.cloudflare.com/durable-objects/reference/in-memory-state/)
and [Wrangler configuration](https://developers.cloudflare.com/workers/wrangler/configuration/).
The controller persists its active bundle before using the cached identity;
after eviction it rehydrates from the stored pointer. That matches the
documented requirement to retain important state outside memory, while scale
and disaster-recovery acceptance remain separate.
