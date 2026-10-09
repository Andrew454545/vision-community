# Remaining launch work

Updated 2026-10-09 after browser recovery and terminal diagnostic readback.

## Current state

- The finite offline Windows diagnostic **failed in round 4 recovery** at 18:04 CDT. Three one-location native rounds completed at 1/2/4 threads; round 4 never reached native work. Its PowerShell test helper received Windows interruption exit `0xC000013A`, whose cause remains unresolved. Original receipts, failure logs and pinned source are unchanged. The verified finite task was disabled after terminal failure. See the [terminal report](WINDOWS_NATIVE_DIAGNOSTIC_20261009.md#terminal-result).
- Correction: the earlier claim in `e99332b` that the task was missing and the four-thread round incomplete was wrong. Privileged readback found the windowless supervisor active at 18:02, before the recorded failure. Restricted process visibility and an earlier sampled receipt did not establish the claimed interruption. A fresh passing regression cannot repair the original failed run.
- The recorded complete Windows service suite passes **448 of 451 tests**, with **three explicit file-symlink permission skips** and zero failures. The restricted run's nine skips remain separate evidence. The focused pricing suite passes 39/39; actual local workerd/D1 recovery passes across three durable restarts. These synthetic checks do not qualify production inference, provider writes or accepted contributions.
- `e99332b8c8a5a8f550767a9c024bc862111300c6` was pushed to `codex/windows-production-readiness` and its remote SHA verified. Andrew's latest private PR #15 owner comment and release inventory still contain the allocation/protected packets, not a sealed positive Gen4 cohort. No GitHub Actions job should be started.

## Ordered handoff

The [windowless process follow-up](WINDOWS_CONSOLE_RECOVERY_20261009.md) passes
157 affected local checks and retires four terminal legacy Scene test tasks.
The exact reported pop-up is not yet attributed. A private 20-minute trace runs
independently of Codex; on a later session inspect its final
`work/console-audit-20261009/visibility-trace.private.json` once, without polling.
Keep unrelated terminals and the contributor's recovery task unchanged.

1. **Complete:** actual browser price review, cancellation, reload, approval of the displayed amount and free paid replay. All four deliveries retained the original query/key and incurred one synthetic debit. See [pricing recovery](SEARCH_PRICING_RECOVERY_20261009.md).
2. **Complete:** push `e99332b` and verify the remote. Keep the historical default price until real accepted-work cost and capacity evidence supports a change. Use `[skip ci]` for the follow-up fixes/evidence too.
3. **Complete:** preserve the terminal diagnostic receipt and add a supplemental correction with all three completed native rounds and the actual round-4 failure. The older two-location timeout stays failed. Never relabel either failure as a successful multithreaded profile.
4. Check Andrew's private VISION handoff for a legitimate **unprotected current official Gen4** Object cohort and portable import authority. Validate the real source/runtime/model/quality pins, strict coverage, Scene membership and protected-database fingerprints before running any qualification or publication test. The protected snapshot remains rejection authority, not a positive cohort.
5. If the pending specific consent for a full private production database copy is granted, rehearse the real schema upgrade, late-failure rollback, D1/R2/native-bundle/secret recovery, accounting reconciliation and paid-search replay in the private verification folder. Consent remains pending. Do not export through another route or substitute synthetic data.
6. Once an OS has authentic qualified Scene/Object/Both admission and genuinely earned-credit search, start its seven-day accepted-work soak independently. Reconcile actual publications, interruptions, day/night settings, credits and storage recovery. Neither clock has started; keep public contribution flags closed.
7. Finish signed clean-device Windows x64 and Apple-silicon Mac acceptance when legitimate signing identities, clean devices and a nontechnical tester are available. Validate install, update, removal, restart recovery, accessibility and Scenes/Objects/Both from the signed bytes.
8. Only after all five launch gates have evidence, freeze the candidate, read back Cloudflare bindings/policies and financial state, run the live beginner smoke check, and open the controlled rollout with rollback ready.

No step above requires another Actions run or access to `geonections-images`. Private releases, database exports, signing identities and location imagery must stay in their approved private channels.
