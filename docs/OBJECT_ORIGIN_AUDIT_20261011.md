# Object origin checks — 11 October 2026

The private native importer now writes the exact no-tunnel-evidence policy
accepted by Andrew's Rust program: `none-darkness-never-rejects-v1`. Its previous
`none-darkness-kept` label was incompatible. The sealer test reads the actual Rust
constant; the scheduler refuses the obsolete label. Existing historical seals
and failures were not rewritten. Private VISION commit
`5e57a26bad52fe195bc277cac55dd6c4a6a0cd07` is pushed and remote-verified on PR #17.

The Python Object auditor now consumes the independently pinned native protected
origin receipt. It binds the same coordinate snapshot, actual Main/WAL, selected
Arrow/delta members, exporter and explicit absent files, with the original
one-hour freshness limit. File IDs remain exact; Windows native ChangeTime is
used instead of treating Python's creation-time field as the Node change time.
This is an origin-machine guard, not permission to move or relabel the database.

The policy's `protectedOriginHandoffSha256`, import's `protectedOriginHandoff`
and `protectedSourceArtifactsSealed` invariant must agree. Any partial declaration
fails closed. Full source hashes are checked at admission and final settlement;
between native stages and on saved-status responses, the pinned receipt and exact
file identities, sizes and timestamps are rechecked without rereading Arrow
contents. A cached approval cannot be served after a source change or expiry.
Recovery must bind the same origin evidence. Historical receipts remain intact.
Legacy independently pinned authority remains unchanged; new origin-bound
profiles require the additional policy pin. No deployed policy was replaced.

## Evidence

- Windows Python: **93 checks**, 0 failures,
  0 errors and 0 explicit skips. The pinned evidence
  lists each skip rather than treating it as a pass.
- Native JavaScript: **112/113 pass**, one existing POSIX executable fixture skip.
- Actual Node-producer-to-Python-consumer interoperability passes on Windows
  using explicitly synthetic data/exporter and no model inference. Source changes,
  absent-file appearance, restored byte/mtime tricks, expiry, native-stage changes,
  cached replies and recovered-receipt binding are exercised.
- The initial Windows stat/handle representation failure, fixture log-capture
  failure and 300-second combined-harness timeout are preserved. The final
  complete regression uses a separate bounded test run; native audit deadlines
  and the frozen trials were not extended.

See [pinned component evidence](evidence/object-origin-audit-20261011.json).
The separate expired offline diagnostic is
[failed and retired](WINDOWS_WINDOWLESS_ENDURANCE_20261009.md#terminal-result--11-october-2026),
with all original evidence preserved. The Windows Scene-only pilot and hourly
refresher were not polled, restarted or modified.

## Remaining release work

A real current origin export, legitimate portable/live protected authority and
authentic Object qualification/publication/once-only credit/search are still
required. These component checks run no real models, grant no credit, open no
admission and do not replace Mac, signed-download, provider-recovery or seven-day
accepted-work evidence. No GitHub Actions workflow ran.

The [publisher plan](SIGNING-PUBLISHER-PLAN.md) records the organization route,
verified base fees and pending jurisdiction. The laptop user can recruit both
testers using the [simple walkthrough](TESTER-QUICKSTART.md). No enrollment,
purchase, booked test or signature is claimed.
