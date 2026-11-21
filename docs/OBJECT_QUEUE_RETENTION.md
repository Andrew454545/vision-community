# Object queue continuity

Completed Object batches now release their hosted waiting slots in the same
transaction that publishes their indexes and awards credit. Failed or cancelled
batches release their slots without credit. Native approval alone cannot release
a slot. Original candidates, receipts, failures and acceptance records remain.

The hosted coordinator permits eight unfinished batches. Its former 64-row
history limit is removed; retained history uses database/storage capacity rather
than waiting slots. Storage allowances still need measurement and monitoring.
This does not remove the native auditor's separate 64-job/registry limit.

## Operator upgrade

Run the existing explicit `prepareObjectAuditDispatch(db)` operator setup.
It atomically upgrades the exact previous dispatch contract to
`private-object-dispatch-v2-20261012`, checks its original fences, preserves all
candidate and journal rows, and reserves slots for unfinished work. Altered or
unknown contracts fail without partial migration. HTTP requests install nothing.

Cancellation recovery uses the same migration. Offline SQL recovery also retains
the optional acceptance journal, its deletion fences, published work and credits.
A repeated restore or lost acknowledgement cannot award a second credit.

## Verification and remaining work

Windows passes 148 contribution checks and 269 of 275 wider recovery checks;
six existing file/directory-link privilege checks are skipped. The groups overlap.
Actual local Cloudflare checks pass 48 cases across six fresh processes, including
v1 upgrade, saved acceptance replay and populated-database restore rollback.
Seventy terminal synthetic batches preserve their history without filling the
queue. All model decisions, locations and credits in these checks are synthetic.
See the [machine-readable evidence](evidence/object-queue-retention-20261012.json).

Nothing is deployed and public Object admission remains closed. [Bounded native
registry rollover](OBJECT_REGISTRY_ROLLOVER.md) and [published native-job cleanup](OBJECT_NATIVE_RETENTION.md)
are implemented. Next: automatic trusted assignment delivery and verified deployment, then authentic
Mac/Windows score qualification, first real accepted batch and earned-credit
search, followed by the remaining [launch gates](PRODUCTION_ACCEPTANCE.md).
The frozen Windows Scene pilot and its refresher are unchanged.
