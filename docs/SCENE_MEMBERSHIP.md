# Sealed Scene search membership

**Offline source only.** Nothing is enabled, deployed or migrated. The
[cost hold](COST_STOP_20261012.md) continues. This is an operator component;
contributors have no extra setup step.

The optional path checks each returned Scene against one independently pinned
snapshot root. It supplies authoritative location/output/pose membership without
looking up each result in D1. Scores still come from the existing pinned native
engine; its numerical parity requirements are unchanged. Objects continue to
require their existing publication and exact official Generation 4 authority.

## Independent authority

[`scene_membership.py`](../community/scene_membership.py) accepts only a verified
operator-sealed contributed Scene snapshot with its independent SHA-256 pin.
The existing snapshot builder requires contributed publications, approved record
hashes and the confirmed environment/resource pair. Andrew's personal reference
corpus and uploader-reported approvals cannot establish membership.

The seal binds the environment, resource pair, Scene lane, policy, runtime,
snapshot, location count and root. It contains a bounded digest tree, without
duplicating account credentials or a member database. Every engine restart
reconstructs that tree from the pinned snapshot; changing the tree and its local
checksum together is insufficient. Before and after each search, the original
snapshot, seal and tree are rechecked. Changed/partial files remain untouched.

The optional Scene definition in the [owner runner](OWNER_SEARCH_SERVICE.md)
adds **both** `membership` (absolute manifest path) and `membershipSha256`.
Missing one, Object-lane use or overlap with private runner state is refused.
The wrapper preserves exact query bytes and native scores, attaching only
bounded membership proofs. Its source is included in the native runtime's source
pins; existing real runtime policies are not silently updated or reapproved.

The coordinator's optional `SEARCH_SCENE_MEMBERSHIP` JSON is the independently
reviewed `coordinatorBinding` header returned by the builder. It is **not** read
from the search reply or contributor. Its exact fields are:
`version`, `scope`, `lane`, `environment`, `resource`, `policyId`, `runtimeSha256`,
`snapshotSha256`, `locations`, `rootSha256`. Scope is
`operator-sealed-scene-membership-v1`; version is 1. Use the exact currently
confirmed Community resource pair, never recombined resources or another bucket.
New account/resource support requires separate approval and implementation.

No checked-in deployment sets this option. Absence retains existing D1 checks;
malformed configuration/proofs fail closed and never fall back. Static snapshots
are required. Queue claims still require matching independent lane capabilities.
An invalid Scene root cannot disclose new Scene queries or consume claim attempts;
a separately healthy Object lane remains available. Root changes cannot authorize
old proofs, retarget saved jobs or spend credit on a refused completion.

## Finite bounds and recovery

- At most 100,000 sealed Scenes, 64 returned hits per search, 17 sibling digests
  per hit, 8 KiB per member and 4 KiB coordinator configuration.
- The browser shows the advertised lane limit before new searches. It preserves
  existing form values and immutable pending queries; paid recovery bypasses new
  limits. Unsupported counts fail explicitly before inference/reservation.
- Proofs hash the exact original member JSON bytes, including Unicode and Python
  floating-point spelling. Ordinals, location IDs, record hashes and poses are
  checked against the root; ordering, filters, exclusions and score rules still
  use the shared gateway validator.
- Cancellation, account deletion and once-only financial settlement retain their
  existing transaction fences. Saved paid replies replay even with unavailable
  seal files or a broken/removed root; no recomputation or extra debit occurs.

Account deletion retains previously verified anonymous contributions under the
existing policy. A separate withdrawal or invalidated publication requires a
fresh independently approved snapshot/root and consistent cutoff. Do not keep an
obsolete root active or restore it from a stale local backup. Preserve pending
reservations, deletion authority and exact paid replies through any rollback.

## Evidence and remaining work

[The Windows synthetic receipt](evidence/scene-membership-20261013.json) records
80 passing Node cases and 60 passing Python cases across the final applicable
runs, plus one existing host symlink skip. It includes actual Python-produced
proofs checked by the JavaScript gateway, with mocked native scores, exponent
notation/Unicode, empty per-location catalogs, once-only debit, deletion fences
and the browser's real readiness function. Initial failures remain preserved;
the receipt identifies their fixes rather than erasing them.

This removes per-result Scene catalog lookups only. Admission, Object membership,
status reporting and historical publication rows still use D1. Trusted outbound
verification/import, bounded batch metadata, withdrawal/recovery authority and
catalog migration remain work. Paid replies also need an approved finite storage
design. No Free-plan CPU/row capacity, real inference, Mac execution, signing,
live recovery or endurance acceptance was measured. Those gates and explicit
activation authority remain required before use.
