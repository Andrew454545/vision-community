# Remaining launch work

Saved Object decisions now revalidate their supporting files, with cancellation
and erasure still available; [105 distinct Python, 101 JavaScript and 17 local
Cloudflare checks pass](OBJECT_SAVED_RESULT_INTEGRITY_20261011.md). Launch gates remain open.

The [Object SQL recovery follow-up](OBJECT_CANCELLATION_SQL_RECOVERY_20261011.md)
now preserves cancellation fences, retry/failure history and exact saved values
through offline D1 batch preparation and local import/restart. Windows passes
265/269 affected checks (four file-link privilege skips) and 37 actual local
Cloudflare checks across three processes. Live destination/deletion/financial/
provider recovery and authentic Object acceptance remain open; the frozen Scene
pilot is unchanged.

The [older-D1 cancellation recovery component](OBJECT_CANCELLATION_D1_RECOVERY_20261011.md)
now reapplies current cancellations even when a backup predates the lease, and
blocks late uploads/publication while preserving accepted records and units.
Windows passes 231/234 JavaScript checks (three existing file-link skips), five
Python recovery cases and 24 actual local Cloudflare cases across three processes.
Actual repaired-D1-to-native-spool recovery passes with synthetic inference.
Real provider/secret/deletion/financial reconciliation, authentic Object admission
and other launch gates remain open. The frozen Scene pilot is unchanged.

The [current Object cancellation recovery follow-up](OBJECT_CANCELLATION_NATIVE_RECOVERY_20261011.md)
now binds native backup startup to an independently pinned current cancellation
ledger, including active accounts. Windows passes 211/214 JavaScript checks
(three existing file-link skips), 60 Python regressions and eleven actual local
Cloudflare restart/reassignment cases. An approved old native backup is revoked
before serving, with no extra inference; source backups and banked fixture units
are preserved. Older-D1/provider replay, authentic Object acceptance and other
launch gates remain open. The frozen Scene pilot is unchanged.

The [Object cancellation follow-up](OBJECT_AUDIT_CANCELLATION_20261011.md) adds
durable submission revocation and independent native/R2 cleanup without account
deletion or credit changes. Windows passes 248/251 affected JavaScript checks
(three existing file-link skips), ten actual local Cloudflare restart cases and
one actual Node/Python lost-start-reply test with synthetic inference. Existing
recovery tools refuse incomplete cancellation authority; full current-authority
restore and public integration remain open. The frozen Scene pilot is unchanged.

The [Object recovery follow-up](OBJECT_AUDIT_RECOVERY_20261011.md) adds
explicit, journalled connection resumption and once-only native retry intents.
Lost replies/restarts cannot create an extra attempt; original failures and
deletion authority remain intact. Windows passes 210/213 affected JavaScript
checks (three existing file-link skips), twelve actual local Cloudflare cases,
42 Python regressions and a separate overlapping five-case final selection.
Inference is synthetic; authentic qualification/publication/credit integration
and other launch gates remain open. The frozen Scene pilot is unchanged.

The [saved Object handoff](OBJECT_AUDIT_DISPATCH_20261011.md) now connects
owned quarantine to durable native-job dispatch/status with bounded retries,
exact reply pins and deletion/revocation guards. Windows passes 194/197 affected
JavaScript checks (three file-link permission skips), ten actual local Cloudflare
scenarios across four processes and one actual Node/Python protocol test with
explicit synthetic inference. Pending upload retries no longer report accepted
work. Public qualification/router/publication/credit integration and authentic
authority remain open; the frozen Scene pilot/refresher is unchanged.


The [Object storage follow-up](OBJECT_OWNED_STORAGE_20261011.md) adds owned,
immutable quarantine/bundle writes and deletion/recovery fences. Windows passes
271/274 affected checks (three file-link permission skips) and 18 actual local
Cloudflare storage cases across three processes. This closes the new writer
component; authentic qualification and hosted saved-job/publication/credit
integration remain open. The frozen Scene pilot is unchanged.


The [Object origin auditor follow-up](OBJECT_ORIGIN_AUDIT_20261011.md) now
binds Python auditing and saved approvals to the native source receipt, including
all selected Arrow/delta members and one-hour freshness. Actual Node-to-Python
Windows component checks pass; the native no-tunnel policy mismatch is fixed.
Real portable authority and hosted Object admission remain open. The separate
expired offline diagnostic failed during round 4 Windows resource measurement;
its original failure and three completed rounds are preserved, and its exact
owned task is now disabled. See its [terminal result](WINDOWS_WINDOWLESS_ENDURANCE_20261009.md#terminal-result--11-october-2026).
The Scene pilot/refresher remain unchanged. The user is arranging testers;
[organization signing setup](SIGNING-PUBLISHER-PLAN.md) awaits publisher jurisdiction.


Updated 2026-10-10 after real Windows Scene publication and earned-search recovery.

## Current state

- The [protected origin handoff](PROTECTED_ORIGIN_HANDOFF_20261010.md) is pushed in private VISION PR #17 at `e118a442e0123477c4c64c4b0488ccd509548eff`. It captures complete selected Main/WAL/Arrow/delta authority through two bounded native exports, preserves private failures, and provides independently pinned opt-in sealer/scheduler guards with a fixed one-hour origin window. Windows passes 112/113 checks with one existing POSIX skip and explicit synthetic inference/exporter fixtures. The attempted offline native build failed because the existing cache lacks `arrow`; no dependencies were downloaded. The original authentic eight-row candidate still refuses missing Main/WAL and all 76 owner handoff pins remain verified. Obtain a fresh source-side run on the owner's existing profile/exporter, then finish a legitimate portable/live protection design and runtime authority. This receipt cannot substitute for unavailable origin files or authorize a private MMA database transfer.

- The [native Community Scene bridge](NATIVE_COMMUNITY_SCENE_BRIDGE_20261010.md) is pushed in private VISION PR #17 at `cf64635a88dcf44ee069e67910a162b9eb478e4b`, based on PR #16. The independently pinned consumer, road-label conversion and exact official-input preparation pass 76/77 Windows component cases with one existing POSIX-only skip. The authentic repository command passes native v7 validation on eight genuine completions using still-fresh cached metadata; the actual builder admits all eight. The original mismatched-ID empty candidate remains preserved. Final sealing refuses missing matching protected Main/WAL authority and writes no seal. Finish fresh portable protected/runtime authority and authentic hosted Object qualification/quarantine/publication/credit/search next. Keep all guards and underlying metadata freshness; a new validator completion does not establish a new Google fetch.

- The [audited Community Scene source producer](COMMUNITY_SCENE_SOURCE_20261010.md) works on all eight real credited completions and their authentic original 100-row source. It preserves original IDs, exact pose/row bytes and the `has-road`/`no-road` dialect, and emits a separate independently pinnable private catalog. The first dialect rejection is preserved. Its native consumer and separately pinned road-label transformation now pass above; no Object import is approved by the producer. Use current membership, fresh official Gen4 and protected authority at actual admission.

- The [authentic native Object handoff](NATIVE_OBJECT_SOURCE_HANDOFF_20261010.md) is received with all 76 pins verified. Exact scans find zero supplied cohort IDs in owner Scene sources; do not repeat the owner MMA membership request. The distinct audited Community Scene route is implemented above; finish fresh matching protected/runtime/quality import authority. Native v7 compatibility and Windows flush fixes are pushed as private VISION PR #16 (`47c99c8`); its earlier 39/40 Windows result has one POSIX-only fixture skip. The authentic historical candidate still fails and creates no seal. Do not edit its original proof or stale Main/WAL authority.

- The [Object spool restore component](OBJECT_SPOOL_RECOVERY_20261010.md) applies current independently pinned deletion authority before receipt recovery/HTTP startup. Offline Node export and restored Python/SQLite spool pass together; deleted work cannot replay, active balances remain unchanged and an injected final-statement failure rolls back all revocations. Final selections pass 11 Python and 18 JavaScript cases, with existing job/privacy regression recorded separately. No live Object binding or gate changed; actual native-host, provider/bundle/secret recovery and complete current accounting remain open.

- The [Object account-cleanup integration](NATIVE_OBJECT_ACCOUNT_CLEANUP_20261010.md) closes the saved-job deletion race in source: deletion journals owned assignments, including starts with lost acknowledgements, and the private host saves pre-start revocations. Actual local workerd/D1 passes across three separate processes. This is not deployed Object acceptance. Continue authentic qualification, owned quarantine, publication/once-only credit and independent native spool/tombstone recovery; the R2-only checker correctly refuses to certify that native authority.

- The [automatic Scene refresh follow-up](SCENE_AUTOMATIC_REFRESH_20261010.md) passes 222 targeted checks, deployed private dynamic-head search, a real ten-location two-unit search and exact fresh-process paid recovery. The corrected finite hourly task completed `CURRENT_NO_CHANGE` for the existing ten locations; its first future real append remains to be observed. Six units now remain banked. The pilot client, image, original start pins and daily native limits are unchanged. Preserve the original failed deployment/task receipts and their separate corrections. The refresher reserves four starts for contributions and stops one hour before the pilot ends; do not spend Codex runs merely polling it.

- The restricted [Windows Scene-only seven-day pilot](WINDOWS_SCENE_WEEK_PILOT_20261010.md) started **10 October 07:27:14 UTC / 02:27:14 CDT**, targeting **17 October at the same time**. Its real hidden scheduled batch published two fresh locations and earned two units once. The offline sealer appended them to the eight previous contributions without changing old ordinals; native search returned all ten, charged two earned units once and recovered the identical paid reply across fresh processes. Primary D1 reconciles the account at eight banked units. The task is finite, windowless, SID-verified, non-overlapping and independent of Codex. It uses the qualified CPU1 profile and bounded day/night intervals within existing hosting limits. Preserve the separately failed first preparation/pilot/readback attempts. Physical interruptions, schedule transitions and final reconciliation remain pending; this is not the full Windows/Mac Scenes/Objects/Both gate or verified Maximum parallel acceptance.

- The [real Windows Scene trial](WINDOWS_SCENE_COHORT_20261010.md) passes current CPU1 fixed-input qualification, eight fresh native-audited publications across eight countries, eight earned units, one eight-unit native-search debit and exact fresh-process account/paid-result recovery after closure. Eight units remain banked; no synthetic funding was added. The finite staging trial is closed and compute stopped. Follow the installed hourly refresh and repeat genuine acceptance on Mac. The original live comparison and client recovery failures remain preserved. The 92 final affected checks have no failures or skips. Neither full accepted-work timer started; the installed background contributor was not changed by this finite foreground trial.

- The earlier [seven-day start check](evidence/accepted-work-start-preflight-20261010.json) records closed staging and an installed contributor waiting with zero accepted work in that run. The [private Object privacy follow-up](evidence/object-audit-privacy-20261010.json) passes 55 checks: explicit erasure survives partial cleanup/restart, cannot be undone by upload/retry/cancel replay, waits for active native work and refuses Windows junctions. Connect hosted ownership/deletion authority and the remaining admission/settlement pipeline; this private component is not deployed and does not complete account deletion.

- [Saved Object audit jobs](NATIVE_OBJECT_AUDIT_JOBS.md) now separate the short HTTP acknowledgement from bounded native work. Durable duplicate/conflict handling, complete-receipt recovery, an actual abrupt separate-process restart, retry bounds, cancellation and actual local workerd transport are checked with explicit synthetic inference. Connect this component to hosted qualification/quarantine, privacy cleanup, publication and once-only credit; the public Object gate remains closed. Do not route long Object recomputation through the synchronous Scene audit request.
- The [positive Gen4 cohort](GEN4_COHORT_20261009.md) is now supplied from R2: 100 locations across 22 countries, at most five each, fresh strict native validation and raw Google metadata agreement, all outside the real protected snapshot. Private VISION release asset 626998074 was uploaded and independently downloaded with all 40 file pins verified. Eight now have genuine Community Scene completions for the private handoff. These do not assert local MMA Scene membership or supply native Object import authority. The portable runtime/protected-database authority request is in private PR #15. Candidate discovery is no longer waiting on Andrew.
- The [full production-data upgrade rehearsal](PRODUCTION_DATA_REHEARSAL_20261009.md) passes after explicit private-transfer consent. All 364,056 historical rows, original schema/history and high-water marks survive independent generated-batch replay/late-failure rollback; 11 source schema objects match live readback and all 18 balances reconcile. Actual local workerd/D1 passes separately with synthetic deployed-schema data and a shorter private TEMP. Earlier export/conversion/access/simulator failures remain. Complete provider/paid recovery and controlled rollout are still open.

- Shared background retry recovery now bounds backward-clock waits and rejects oversized/invalid persisted retry state. The [affected Windows checks](evidence/background-retry-clock-recovery-20261009.json) pass 115/116 with one explicit symlink-privilege skip. Saved deliveries recover once across fresh processes; this is synthetic component evidence, with actual Mac execution still pending. The installed contributor and running diagnostic snapshots remain unchanged.
- The [Mac control follow-up](MAC_BACKGROUND_CONTROLS_20261004.md) shows saved report time separately from job liveness, bounds actual JSON reads and clarifies Medium/Maximum. Its Windows fixture selection passes 50/54 with four symlink-privilege skips; actual Mac verification remains pending. Include the Mac background, starter, removal and launch-agent modules in the next finite local Mac component check; no native model replay or Actions run is required.
- The finite offline Windows diagnostic **failed in round 4 recovery** at 18:04 CDT. Three one-location native rounds completed at 1/2/4 threads; round 4 never reached native work. Its PowerShell test helper received Windows interruption exit `0xC000013A`, whose cause remains unresolved. Original receipts, failure logs and pinned source are unchanged. The verified finite task was disabled after terminal failure. See the [terminal report](WINDOWS_NATIVE_DIAGNOSTIC_20261009.md#terminal-result).
- Correction: the earlier claim in `e99332b` that the task was missing and the four-thread round incomplete was wrong. Privileged readback found the windowless supervisor active at 18:02, before the recorded failure. Restricted process visibility and an earlier sampled receipt did not establish the claimed interruption. A fresh passing regression cannot repair the original failed run.
- The recorded complete Windows service suite passes **448 of 451 tests**, with **three explicit file-symlink permission skips** and zero failures. The restricted run's nine skips remain separate evidence. The focused pricing suite passes 39/39; actual local workerd/D1 recovery passes across three durable restarts. These synthetic checks do not qualify production inference, provider writes or accepted contributions.
- `e99332b8c8a5a8f550767a9c024bc862111300c6` was pushed to `codex/windows-production-readiness` and its remote SHA verified. The current positive cohort above supplements Andrew's allocation/protected packets; a legitimate native runtime import seal remains missing. No GitHub Actions job should be started.

## Ordered handoff

The [windowless process follow-up](WINDOWS_CONSOLE_RECOVERY_20261009.md) passes
157 affected local checks and retires four terminal legacy Scene test tasks.
The exact reported pop-up is not yet attributed. The private 20-minute trace
finished at 23:51:38 UTC with no detected terminal show/foreground events and
both hooks released. Its final private receipt is pinned in the
[completion evidence](evidence/windows-console-visibility-completion-20261009.json);
the limited negative observation does not prove the earlier issue is fixed.
Keep unrelated terminals and the contributor's recovery task unchanged.

The separate [windowless diagnostic](WINDOWS_WINDOWLESS_ENDURANCE_20261009.md#terminal-result--11-october-2026)
is terminal and its owned task is disabled. Three native rounds completed;
round 4 failed during Windows process-name resource measurement. Preserve its
original receipt and earlier failures. Do not poll or restart this finished
diagnostic; any new regression needs separate evidence and cannot start the
accepted-work clock.

1. **Complete:** actual browser price review, cancellation, reload, approval of the displayed amount and free paid replay. All four deliveries retained the original query/key and incurred one synthetic debit. See [pricing recovery](SEARCH_PRICING_RECOVERY_20261009.md).
2. **Complete:** push `e99332b` and verify the remote. Keep the historical default price until real accepted-work cost and capacity evidence supports a change. Use `[skip ci]` for the follow-up fixes/evidence too.
3. **Complete:** preserve the terminal diagnostic receipt and add a supplemental correction with all three completed native rounds and the actual round-4 failure. The older two-location timeout stays failed. Never relabel either failure as a successful multithreaded profile.
4. Retain the installed hourly Scene refresher and inspect a meaningful new append/failure receipt when available. Its real ten-location no-change baseline, dynamic paid search, guarded activation replay and component append/restart checks pass. Account deletion retention follows the existing anonymous-contribution contract; removal/changed history remains a separate fail-closed migration. In parallel, use the supplied cohort, genuine Community Scene completions, authentic native source and saved Object audit jobs. The explicit Community Scene bridge and exact coverage-input preparation now pass on eight real rows in private PR #17. Finish fresh legitimate portable protected-database/runtime import sealing, then connect Object qualification/quarantine, the short start/status protocol, privacy cancellation/cleanup, publication and once-only credit. Refresh coverage within its underlying metadata age limit and import window. Keep all source/runtime/model/quality pins and original manifests; owner-only Scene membership is absent and a fabricated MMA or rewritten historical seal cannot satisfy authority.
5. Full-data upgrade/replay/late-failure rollback and balance export now pass. [Actual local recovery](REAL_PAID_RECOVERY_20261010.md) now preserves all three genuine staged paid replies, contributions, R2 files and deletion archives across restart; the converter ordering fix reproduces the full historical production copy. Continue complete provider/secret recovery with independent current deletion/financial authority, strict whole-history accounting and a fresh drained-writer controlled migration. The approved historical production backup contains no paid-search rows and is not a current financial cutoff. Preserve the staged fixture histories; do not relabel them as real work to satisfy accounting.
6. Retain the running Scene-only Windows pilot and inspect its final receipts after 17 October 07:27:14 UTC; avoid routine polling. Exercise actual safe interruptions and day/night recovery, then independently reconcile publication and credit. Once an OS has authentic qualified Scene/Object/Both admission and genuinely earned-credit search, start its full seven-day accepted-work soak independently. Full Windows/Mac workload clocks have not started; public contribution flags stay closed.
7. Finish signed clean-device Windows x64 and Apple-silicon Mac acceptance when legitimate signing identities, clean devices and a nontechnical tester are available. Validate install, update, removal, restart recovery, accessibility and Scenes/Objects/Both from the signed bytes.
8. Only after all five launch gates have evidence, freeze the candidate, read back Cloudflare bindings/policies and financial state, run the live beginner smoke check, and open the controlled rollout with rollback ready.

No step above requires another Actions run or access to `geonections-images`. Private releases, database exports, signing identities and location imagery must stay in their approved private channels.
