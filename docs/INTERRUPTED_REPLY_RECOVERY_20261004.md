# Interrupted reply recovery

A connection can close after the service saves a submission or awards credit
but before the PC receives its reply. The earlier client did not catch Python's
partial-response HTTP exception; a temporary interruption could therefore stop
processing for manual review.

The repair uses existing bounded transport retries for incomplete/protocol
replies and malformed UTF-8. After those attempts, background processing saves
its ordinary service cooldown. Saved output remains in the delivery journal;
no approval or credit is inferred from a partial reply. An interrupted HTTP
error body retains its actual status: transient 503 retries, while revoked
access or rejection stops. Broken error text never overrides that distinction.

## Checks and limits

Four real loopback HTTP/SQLite checks use fresh Python processes and disposable
synthetic output. Interrupted submission replies, verifier outage, restart
inside a persisted cooldown, and audit replies cut off after one synthetic
award recover the same request. Acknowledged completion stops replay; the
disposable service records one award. Rejection preserves output and failure
evidence and sends no further request after restart. Interrupted 503 and 401
error bodies retain transient versus terminal handling. The saved account
remains unchanged and its code is absent from status/failure/journal files.

The initial partial-response failure and subsequent fixture-output/SQLite
cleanup failures are preserved in private logs. The corrected targeted suite
passes all 60 checks in 22.759 seconds.

These are actual HTTP connections and separate process restarts using ordinary
background/account/delivery code. A tiny synthetic storage allowance prevents
setup downloads, qualification, new leases and inference. Cooldown clocks are
simulated. The service and accounting are disposable fixtures, not production
or an accepted native contribution. OS restart, sleep/wake, accepted workload,
parallel budgets and long-term endurance remain separate release gates. The
installed contributor and earlier immutable previews are unchanged.

The complete local Windows suite passes 482 tests in 426.933 seconds with two
existing filesystem-link permission skips. All six Community CI jobs pass for
the repair and the synchronized-guide revision `1e85807`; its Windows job
passes all 482 tests in 320.233 seconds without skips.

The [separate recovery preview](https://github.com/Andrew454545/vision-community/releases/tag/windows-starter-preview-20261004-recovery)
contains all 274 public tracked files from `1e85807`. A fresh public download
matches every file and ZIP SHA-256:
`26b7b58a5e18361fee231ac62cac7ba3772a61aad66d301e3053ee8fdde86012`.
Twenty-four checks run against that downloaded copy pass in 52.509 seconds,
including HTTP recovery, guide links, progress and native control construction.
The configured PowerShell runtime is used; a separate check without that setting
hit the host's existing script policy and an incorrect test-module name. Its
log is retained; no security settings were changed.

The short guide is deployed to confirmed staging. All 13 assets, privacy
headers and expected bindings pass readback. Admission remains closed; no
account, credit or native work was created by those checks. This is a source
preview, not a signed or production-qualified runtime release.
