# Object audit account cleanup

Hosted account-deletion code now queues erasure of every owned Object assignment
in the same D1 transaction that revokes credentials and forfeits credit. This
includes a native job whose start acknowledgement was lost. It closes a deletion
race in the saved-audit protocol; it does not qualify, publish or create credit.

## Deletion and recovery

- Private authenticated `POST /object-assignments/<leaseId>/erase` saves a
  revocation even before a job exists. Delayed uploads cannot recreate its
  payload after restart. Only the independently pinned registry's at most 64
  assignments can be revoked; callers cannot create arbitrary tombstones.
- Existing native work remains owned until its writer ends. Late approval cannot
  undo revocation. `erasing` stays pending; `erased` confirms both payload and
  attempt folders are absent. An unused assignment can immediately acknowledge
  erasure after saving its tombstone.
- D1 stores a logical `object-audit-jobs/<leaseId>` outbox entry, not an R2 object.
  Cleanup checks the deleted account, matching deletion receipt and owned Object
  lease before calling the private `OBJECT_VERIFIER` binding. Wrong ownership
  needs review; missing configuration, outage, an unregistered assignment or an
  uncorrelated reply stays pending.
- A pass selects at most its existing 16/64 outbox limit and shares a 20-second
  native-call budget. It never runs models. Scheduled cleanup resumes pending
  work; a failed acknowledgement cannot erase the intent.
- Account restoration requeues Object assignment revocation rather than trusting
  an old native acknowledgement. Conflicting ownership rolls back reconciliation.
  The R2 privacy checker refuses to certify native-spool recovery from an R2-only
  inventory, even when D1 remembers `erased`.

Preserve the spool database and revocations with their matching registry/policy.
A fresh empty spool cannot replace that privacy authority. Keep lease/outbox
ownership until cleanup and independent recovery reconcile it. Published anonymous
contributions retain the existing deletion contract; private audit inputs/logs
are erased separately. Future Object quarantine/index writers need their own
owned immutable storage and privacy fences.

## Verification

[Pinned evidence](evidence/object-account-cleanup-20261010.json):

| Check | Actual result |
| --- | --- |
| JavaScript privacy, bridge and storage recovery | 91 passed / 93; two Windows file-symlink privilege skips |
| Schema, account restore and financial recovery | 62 passed / 63; one Windows file-symlink privilege skip |
| Python saved audit service | 36 passed; zero skips |
| Python native auditor regression | 24 passed; zero skips; synthetic inference |
| Explicit old-spool upgrade follow-up | One passed; overlaps the saved-service suite |
| Actual local workerd private bridge | 15 cases passed; synthetic provider |
| Actual local workerd/D1 account cleanup | 15 cases across three separate processes; synthetic provider |

All final selections have zero failures. Actual D1 verifies immediate credential
and credit revocation, pending cleanup through outage/wrong identity, restart,
completion, deletion replay, unrelated-account preservation and refusal of late
assignments/credits. Python additionally tests native-writer races, interrupted
cleanup, delayed uploads, concurrency and real loopback HTTP.

Original failures remain privately pinned: the first bridge branch incorrectly
applied job-only fields to an assignment reply; restricted SQLite access prevented
workerd startup; a fixture lacked a module; and early restart fixtures used obsolete
per-resource persistence options. A fixed database ID alone did not repair the
last issue. The final fixture uses the installed simulator's
`resourcePersistencePath`, retaining the database across all three processes.
The initial combined restricted Python run recorded errors and reached its
230-second bound without completing; the separate authorized selections pass.

## Deployment limit

This is committed source and local integration evidence. No live Object binding,
host, admission flag or production resource changed. The frozen Scene pilot and
refresher are unchanged. Authentic import, hosted qualification/quarantine,
publication/once-only credit, independent native privacy recovery, actual Mac
execution and the remaining launch gates are required.

Implementation follows Cloudflare's [service-binding interface](https://developers.cloudflare.com/workers/runtime-apis/bindings/service-bindings/http/)
and [Workers guidance](https://developers.cloudflare.com/workers/best-practices/workers-best-practices/)
for private calls, bounded response reads and handled background promises.
