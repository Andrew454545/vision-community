# Private Object job bridge

This bridge carries saved native audit jobs over authenticated HTTPS. It has no
public contribution, qualification or credit endpoint and is not bound to the
live Community Worker.

Private erasure acknowledges `erasing` first. Only `erased` confirms removal of
that job's spool files; cancellation alone preserves its evidence.

See [the operator contract and recovery evidence](../../../docs/NATIVE_OBJECT_AUDIT_JOBS.md).
Keep `NATIVE_OBJECT_VERIFIER_ORIGIN` and `NATIVE_OBJECT_VERIFIER_SECRET` private.
Do not deploy or open Object admission until trusted qualification, quarantine,
publication, privacy cleanup and credit settlement are integrated and verified.
