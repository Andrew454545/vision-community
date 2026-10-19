# Saved Object result integrity — 11 October 2026

Saved private Object approvals and rejections now recheck their receipt and
supporting files before a status or duplicate-submission reply returns them.
Previously, completed jobs checked live origin evidence when present, but could
return a saved decision after other inputs or the report changed.

The check binds the original registry, assignment, trusted and staged source,
candidate manifest and feature files, report bytes, decision and saved receipt
hash. Runtime, policy, implementation, protected snapshot and Main/WAL file
identities are checked before and after reading the bounded job inputs. Full
content hashes remain mandatory at verifier startup, audit and settlement;
status requests do not rehash large model files or repeat inference. Each
added identity scan is limited to 512 files and five seconds. Live origin checks retain
their original expiry and source requirements.

Unavailable evidence returns a fixed 503 response. The historical decision,
attempt count and original report remain intact. Authenticated cancellation and
erasure remain available even after evidence changes or expires. A damaged
candidate encountered during recovery marks that attempt unconfirmed without
rerunning inference or rewriting the original report.

## Verification

Windows verification passes **105 distinct Python checks**, including sixteen
new integrity/revocation checks, **101 JavaScript checks** and **17 actual local
Cloudflare transport cases**. The broad Python run executed 103 checks with two
optional Node checks skipped; both were then run successfully with the existing
private Node runtime. No skips remain unresolved. Three HTTP checks were repeated
after adding the final fixed-error mapping, alongside its new retry check and
the actual Node-to-Python backup-recovery check.

Checks cover same-size model edits with restored modification time, identical-byte
file replacement, dependency/WAL appearance, changed trusted inputs, candidate
and receipt changes, late changes during validation, actual loopback HTTP and a
fresh hidden host process. Cancellation and explicit erasure also pass after
live origin change or expiry. The Node-produced protected handoff is checked by
Python on its original synthetic fixture machine.

The first focused run's two errors remain preserved: a damaged feature file
raised an uncaught `VisionIndexError`, and receipt revalidation prevented the
old control path from cancelling a job. Both paths are fixed and covered by
passing checks. The JavaScript child passed all its checks; its outer log-printing
helper subsequently hit a Windows console encoding error. The original child
logs and exit receipt are preserved, and later helper output uses ASCII escaping.

Private logs and receipts remain in `work/object-receipt-guard-20261011` outside
Git. [Redacted evidence and checksums](evidence/object-saved-result-integrity-20261011.json)
identify the tested source and preserved failures.

## Limits

Native inference, identities and coverage in these checks are explicit synthetic
fixtures. They prove component behavior, not authentic Object qualification,
accepted contributions, earned search credits or Mac acceptance. Public Object
admission stays closed. The frozen Scene pilot and its refresher were not polled,
changed or restarted. No live Cloudflare resources, private uploads, model
downloads, signing services or GitHub Actions were used.

Authentic source authority, full provider/data recovery, accepted-work soaks,
trusted clean-device installations and controlled rollout remain launch gates in
[production acceptance](PRODUCTION_ACCEPTANCE.md).
