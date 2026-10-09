# Next steps when the stronger model is available

Updated 2026-10-09 after the local Windows check.

## Current state

- The finite offline Windows diagnostic is **not running**. Its scheduled task is missing and no Node or Python worker is active.
- Its receipt is retained as an interrupted/incomplete diagnostic: 1-thread and 2-thread rounds completed; the 4-thread round has an incomplete native attempt. The receipt still says `RUNNING` because the supervisor stopped before writing its terminal state. Do not count this as a completed endurance or production qualification run.
- The local Cloudflare service suite currently passes **442 of 451 tests**, with **9 explicit Windows link/symlink privilege skips** and zero failures. The focused pricing and recovery suite passes 39/39. The actual local workerd/D1 pricing recovery check passes across three durable restarts. These are local checks; they do not qualify production inference, provider writes or accepted contributions.
- GitHub is synchronized at `31985e9`. Andrew's latest owner update is the complete allocation handoff at 10:41 UTC; no newer owner message is present after the engineering handoff at 20:15 UTC. No GitHub Actions job should be started.

## Ordered handoff

1. Finish the browser recovery walkthrough using the in-page price review dialog. Verify that a stale quote opens an accessible review, that Continue preserves the original request key and query, that Cancel leaves the request saved, and that a paid replay remains free. Keep the browser fixture synthetic and loopback-only.
2. Commit and push the dynamic-price/recovery changes with `[skip ci]`. Re-run `git diff --check`, the focused pricing tests, the full local Worker suite, the local workerd/D1 recovery tool and the Python interface checks. Keep the current historical default until real accepted-work cost and capacity evidence supports a change.
3. Correct the private diagnostic receipt in a follow-up evidence-only change: preserve all completed rounds and native failure details, mark the supervisor as interrupted/incomplete, and link the retained older two-location failure. Never relabel either failure as a successful multithreaded profile.
4. Check Andrew's private VISION handoff for a legitimate **unprotected current official Gen4** Object cohort and portable import authority. Validate the real source/runtime/model/quality pins, strict coverage, Scene membership and protected-database fingerprints before running any qualification or publication test. The protected snapshot remains rejection authority, not a positive cohort.
5. If the pending specific consent for a full private production database copy is granted, rehearse the real schema upgrade, late-failure rollback, D1/R2/native-bundle/secret recovery, accounting reconciliation and paid-search replay in the private verification folder. If consent is absent, do not export or substitute a synthetic database.
6. Once both OS runtimes have authentic qualified Scene/Object/Both admission, start the seven-day accepted-work soak independently on each OS. Reconcile actual publications, interruptions, day/night settings, credits and storage recovery. Until then, keep public contribution flags closed.
7. Finish signed clean-device Windows and Apple acceptance when Andrew supplies legitimate signing identities, clean devices and a nontechnical tester. Validate install, update, removal, restart recovery, accessibility and Scenes/Objects/Both from the signed bytes.
8. Only after all five launch gates have evidence, freeze the candidate, read back Cloudflare bindings/policies and financial state, run the live beginner smoke check, and open the controlled rollout with rollback ready.

No step above requires another Actions run or access to `geonections-images`. Private releases, database exports, signing identities and location imagery must stay in their approved private channels.
