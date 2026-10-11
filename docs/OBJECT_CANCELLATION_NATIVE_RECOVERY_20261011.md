# Current cancellation authority for native recovery — 11 October 2026

Restoring an older native backup now reapplies an active contributor's submission
cancellation before any saved approval can be returned. Account deletion is not
required. This closes the native-spool part of the
[cancellation recovery gap](OBJECT_AUDIT_CANCELLATION_20261011.md); complete
older-D1/provider recovery and public Object integration remain open.

The offline exporter accepts a separately pinned **current cancellation ledger**
alongside the existing independently pinned deletion ledger. It verifies the
complete current cancellation set, including completed erasures, against a closed
current Community database. Exact account/lease/candidate/upload ownership,
policy, assignment/submission hashes, request ID and original cancellation time
must agree. An older database cannot be represented as current when the independent
ledger contains a later cancellation. Unknown schemas, missing events, extra or
changed records, stale captures and mismatched resources fail without authority.

The resulting v2 manifest contains only the selected registry's cancellation
identities and source pins; account IDs, artifact keys and candidate bytes are
excluded. Both original ledger freshness windows bound expiry. Exporting a new
manifest does not refresh them. V1 remains available for deletion-only state and
still refuses current cancellation records without the additional ledger.

The native host validates either exact format and applies the union of deletion
and cancellation revocations in one transaction before receipt recovery or HTTP
startup. Overlap creates one tombstone. Rollback, exact replay, conflicting or
older authority, pre-start cancellation and restart retain their existing guards.
A newer manifest cannot remove saved revocation. The native host still rechecks
its actual registry/policy/source inputs. No recovery path approves work or
creates publication or credit.

A related cleanup race is fixed: once a cancelled location is released, another
lease may later publish it. That distinct canonical bundle no longer prevents
cleanup or current cancellation export for the old lease. The new bundle remains
untouched. Same-lease, unknown or older publication still requires review; the
initial cancellation transaction continues to refuse already-published work.

## Private operator use

With admission closed and writers drained, independently capture/pin both current
ledgers after the cutoff. `exportObjectCancellationLedger` produces the complete
ledger from a current closed copy; it must never use the old restored backup as
its source. Keep all inputs and copies private. The component bounds the ledger
to 4,096 events, the input to 4 MiB, and each native registry to 64 assignments.
Retention/compaction beyond those bounds is not implemented.

Use the existing [spool recovery procedure](OBJECT_SPOOL_RECOVERY_20261010.md),
adding both options to `object-erasure-recovery.mjs`:

```text
--cancellations <absolute-fresh-independent-ledger.json> --cancellations-sha256 <trusted-pin>
```

Upgrade the native consumer before using v2. Older consumers reject it safely.
Supply the exported authority and its independently checked SHA-256 through the
existing `--recovery-authority` and `--recovery-authority-sha256` options while the
spool is offline. Require successful construction, then finish and verify private
file erasure. An `erasing` response is pending. This tool cannot attest that live
writers were drained or that independently restored D1/R2/secrets are reconciled.
The separate R2-only recovery checker continues to refuse cancellation recovery.

## Evidence and limits

[Pinned Windows evidence](evidence/object-cancellation-native-recovery-20261011.json):

- **211/214 affected JavaScript checks passed**, zero failures and three existing
  file-symlink privilege skips. Ten new current-authority cases and the cleanup
  reassignment case are included.
- **60 Python regression checks passed**, including both legacy and v2 recovery,
  saved jobs, retry intent handling and actual dispatch/retry/cancellation HTTP
  interoperability. The new five-case focused selection also passed; it overlaps.
- **Eleven actual local workerd/D1/R2 checks across four fresh processes** prove
  cleanup survives restart/reassignment and preserves the later owner's bundle.
- Actual Node export is consumed by the real Python restored-spool constructor.
  An old approved job becomes `erasing` before it can serve approval, then erases
  without another inference attempt. The preserved backup report is unchanged.
  The active hosted account retains its ten synthetic units; no credit is earned.

Inference is explicitly synthetic. Actual files, closed SQLite snapshots, source
pins, cross-language contracts, startup ordering, transaction rollback and local
Cloudflare storage execute. No authentic Object/model/Mac acceptance is claimed.

The first JavaScript selection preserved one fixture failure: its corruption
setup tried to alter an immutable upload intent and was correctly refused before
reaching the recovery check. The fixture now tests a missing ownership record;
the protection is unchanged. All final selections pass, and the original failure
and diagnostic reports remain preserved.

No live deployment, schema change, private upload, Actions run, global install or
frozen Scene pilot/refresher change occurred. Authentic portable protection and
Object qualification/publication/credit/search, older-D1 cancellation replay,
complete provider/secret/financial reconciliation, Mac/signed-device acceptance
and full accepted-work soaks remain launch tasks. Andrew's narrow fresh-origin
export request remains unchanged.
