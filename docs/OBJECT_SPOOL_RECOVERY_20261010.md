# Restoring private Object audit work

**11 October follow-up:** [current submission cancellation authority](OBJECT_CANCELLATION_NATIVE_RECOVERY_20261011.md)
adds v2 recovery for active accounts. With any current cancellation records,
add both cancellation-ledger options described there; the deletion-only command
below deliberately refuses to certify that state. Its historical evidence is
preserved. Complete older-D1/provider recovery remains open.

Restoring a pre-deletion native backup must not revive an account's approval or
allow its delayed upload. The saved-job service now applies independently pinned
current deletion authority **before** recovering receipts or starting HTTP/native
work. Revocations, erasure intents and the application journal commit together;
an injected last-statement failure rolls them all back.

The offline exporter compares a complete, closed current Community database copy
with a separately pinned deletion ledger and the exact native assignment registry.
Every deleted account and receipt must agree. It selects only matching owned
Object assignments, including assignments whose hosted cleanup already says
`erased`: that old acknowledgement does not certify the restored native disk.
The authority expires ten minutes after the ledger's original capture time.
Exporting it does not refresh that clock. Active accounts and balances are untouched.

## Private operator procedure

1. Close admission and stop/drain all relevant writers. Obtain and independently
   pin the **current** complete database, deletion ledger, registry and policy.
   The deletion ledger must be captured after the writer cutoff. Neither the old
   backup nor an operator-edited timestamp supplies current deletion authority.
2. Using the existing private Node runtime, run the offline export below into a
   new private folder. Keep the current SQLite copy and its credentials outside
   GitHub. The tool refuses database sidecars, changed hashes, integrity failures,
   mismatched ownership/resources, stale ledgers and existing output folders.
   Invalid inputs in a new output folder leave a failure report without an
   authority or success marker. Require a successful command exit and matching
   report pins; partial output after a storage failure is not usable authority.
3. Restore the closed spool with its matching registry/policy and supply both
   recovery options below. Construction must succeed before starting the service.
   A failed authority check must leave ingress closed. Applied revocations survive
   restart; an older or conflicting authority cannot replace them, and a newer
   authority cannot remove saved revocations.
4. Let the owned cleanup worker finish. Verify every affected assignment returns
   `erased` and its candidate/attempt directories are absent. `erasing` is pending,
   not completed privacy recovery. Reconcile the current hosted outbox and every
   native spool before admitting work. Normal later starts use the saved
   tombstones; do not keep passing an expired one-time recovery file.

```text
node deploy/cloudflare/tools/object-erasure-recovery.mjs --current <closed-current.sqlite> --current-sha256 <trusted-pin> --registry <private-registry.json> --registry-sha256 <trusted-pin> --policy-sha256 <trusted-pin> --deletions <fresh-independent-ledger.json> --deletions-sha256 <trusted-pin> --writers-stopped-at <UTC-unix-seconds> --environment <staging-or-production> --out <new-private-folder>
```

Use the produced `object-erasure-authority.private.json` and
`export-report.json`'s `authoritySha256` with the existing saved-job command:

```text
--recovery-authority <absolute-private-authority-path> --recovery-authority-sha256 <trusted-export-pin>
```

This is an operator recovery procedure, not a contributor setup step or a public
API. Starting an arbitrary old backup without this reconciliation is unsupported.
The exporter makes no provider calls and cannot certify that live writers stopped.
Keep source backups, external authority inputs, R2 data, native bundles and secret
recovery in the separate complete recovery inventory.

## Verification and limits

[Pinned Windows evidence](evidence/object-spool-recovery-20261010.json):

| Selection | Result |
| --- | --- |
| Existing saved-job regression and first recovery cases | 46 passed; includes 36 existing and ten recovery cases |
| Final Python recovery selection | 11 passed; includes Node export to real restored Python/SQLite spool |
| Restore/privacy JavaScript regression | 86 passed / 88; two explicit Windows file-symlink privilege skips |
| Final offline export/recovery JavaScript selection | 18 passed; zero skips |

Selections overlap and must not be added as distinct cases. All final selections
have zero failures. Tests exercise actual files, SQLite, backup copying, startup
ordering, atomic rollback, restart, pin changes, stale input and output overwrite
refusal. Inference is explicitly synthetic; there are no live calls or credits.
An old backup's original audit report remains unchanged; explicit privacy cleanup
removes only the restored job's payload and attempt files.

This closes a component restore gap. Actual native-host recovery, complete
provider/R2/bundle/secret recovery, fresh drained authority, whole-history
accounting, authentic Object admission and Mac acceptance remain open. The
R2-only privacy checker still correctly refuses to certify a native spool from
an R2 inventory. No live binding, admission flag, pilot or balance changed.
