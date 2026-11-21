# Private native compute allowance — 9 October 2026

The existing private staging model host now reserves a durable allowance before
native work: **48 compute operations and 12 container starts per UTC day**.
This closes a restart/redeploy loophole in native activity limits and prevents
status reads from keeping idle compute alive. It does not close the production
spending, capacity or recovery gate.

## Behavior

- Health checks that start/contact the native server, activation, model
  diagnostics, qualification, auditing and search reserve an operation first.
  A new/recovery container start also reserves a start.
- The existing single host stores one bounded SQLite record with only its UTC
  day, limits and counters. No account, location, prompt or credential is added.
  Transactions and a storage flush complete before native side effects.
- Eviction/restart/redeploy preserve usage. A configuration increase cannot
  raise a limit already reserved that day. A decrease is persisted even when
  usage already exceeds it. The next UTC day uses the current configuration.
  Failed, interrupted or uncertain work is never refunded.
- Missing/invalid settings, corrupt state, failed writes/flushes and a clock
  rollback deny work. Exhaustion stops uncertain compute while preserving the
  sealed bundle, and returns a fixed 503 response with a retry delay.
- Saved status and stop do not need an allowance. Status and rejected operator
  calls cannot extend the durable idle deadline. The three-minute idle alarm
  remains independent of status polling and the container monitor.

These limits count operations and starts, not dollars, total account requests,
storage or wall-clock compute. They do not replace realistic load measurements,
account billing controls or privacy/financial recovery testing. No production
quota, admission gate, model tolerance or contributor credit was changed.

## Verification and deployment

The full local service regression ran **414 tests: 412 passed, two Windows
file-symlink privilege skips, zero failures**. Directory-junction checks ran and
passed. This selection includes the native host and both bridge suites; the
earlier 314-test restricted run remains separate historical evidence. No Python
application source changed, so its previously recorded 772-test result was not
rerun or relabeled.

Actual local workerd checks passed:

- Twenty concurrent reservations granted exactly four; the other sixteen were
  refused. Two starts were granted and the third refused. After disposing and
  reopening the entire runtime against the same on-disk SQLite state, the four
  operations and two starts remained spent.
- Raised/lowered limits, UTC rollover, clock rollback and missing configuration
  behaved as required; 37 private-host boundary checks and three real SQLite
  idle-alarm checks also passed. No model or cloud resource was used by these
  local fixtures.

Initial local failures are retained privately. A long workspace temporary path
produced internal SQLite errors; the successful runs used the normal Windows
temporary folder. An ignored persistence option initially lost fixture counters
on restart; the corrected Miniflare 5 `resourcePersistencePath` proves disk
recovery. These failed runs were not counted as passes. The exact cause of the
temporary-path failure is not established.

Private staging deployment **`0790c6f3-9cbf-46a0-994a-4d23950919de`** uses the
complete existing container configuration. Provider readback confirms the same
Durable Object namespace/container attachment, R2 binding, pinned image/runtime,
secret binding names, private routes, imagery setting and 5,000 ms Worker CPU
limit. The two new allowance settings read back as 48 and 12. Read-only service
checks before and after deployment show the exact same sealed bundle and prior
failure metadata, with zero new operations/starts consumed. No model diagnostic,
imagery retrieval or bundle replacement was requested.

Only the existing private staging host was deployed. The public website and
production database were unchanged; public contribution admission remains
closed. GitHub Actions was not run. The offline fixture was added to the existing
test workflow for future authorized runs, without removing checks or gates.

See the [aggregate evidence](evidence/hosted-compute-allowance-20261009.json) and
[five remaining release gates](LAUNCH_PLAN.md).
