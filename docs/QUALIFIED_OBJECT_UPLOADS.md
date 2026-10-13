# Object upload integrity for qualified devices

The read-only `inspectObjectUpload` entry point in
[the Object checker](../deploy/cloudflare/src/objectSettlementCheck.js) separates
routine upload integrity from native per-batch auditing. This is one component
of the [approved hybrid plan](HYBRID_LAUNCH_DECISION_20261013.md), not completed
qualified Object admission. It is not exposed as an HTTP approval route and no
deployment or service setting enables it.

The inspector checks the saved private candidate, exact owned submission digest,
artifact journal and privacy fence, bounded feature files, model identities,
finite values, source metadata, assignment membership and fresh trusted official
Gen4 coverage rows. It brackets asynchronous reads with the same database
snapshot and finite deadline, so deletion, cancellation, expiry, pose or coverage
changes invalidate inspection. It performs no native call and makes no database,
R2, publication or financial writes. The existing four-location and 4 MiB
transport limits remain; this is not measured production capacity.

Results have scope `object-upload-integrity-only`, no native audit receipt, and
explicitly grant no server authorization, production qualification, acceptance
or credit. A submitted checksum, quality marker or coverage row cannot establish
reusable device compatibility, real Scene membership or current protected-source
authority. Those require separate trusted evidence before settlement.

The original `checkObjectSettlement` entry point reuses the integrity checks and
still requires approved native state and a fresh correlated native receipt.
Callers cannot supply a request flag to bypass that requirement. Existing audited
settlement, fresh protected evidence, atomic acceptance/credit and paid recovery
are unchanged. Public Object qualification and assignments remain closed.

[Windows local evidence](evidence/object-upload-integrity-20261013.json): 116
checks passed, no skips, covering both entry points, stored-byte corruption,
official coverage, stale ownership, concurrent changes, deadlines, sanitized
metadata and the existing publication/credit flow. SQLite executes locally;
features, native replies, R2 and coverage are synthetic. Private logs are in
`work/object-upload-integrity-20261013` outside the checkout. No real device was
qualified and no provider, cloud, Actions or model execution occurred.

Next connect exact fixed-input Object profile qualification, independently
current Scene/protected authority and distinctly marked qualification-based
publication/once-only credit. Reuse this inspector; do not manufacture an
approved audit job to pass the original settlement gate. Activation and the
[real launch gates](PRODUCTION_ACCEPTANCE.md) remain outstanding.
