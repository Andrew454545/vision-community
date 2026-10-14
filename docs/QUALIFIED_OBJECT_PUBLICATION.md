# Qualified Object publication

**Source only, inactive and undeployed.** Qualified Object uploads now have their
own staging and atomic publication path. It binds an already prepared exclusive
Object lease to a current account/profile qualification, without creating or
consuming a native audit approval. Automatic assignment, public routing and actual
private transport/setup remain unfinished. Default Object capability stays closed.

## Separate admission and current authority

[`prepareQualifiedObject`](../deploy/cloudflare/tools/prepare-qualified-object.mjs)
is an explicit operator migration for the optional namespace, after the existing
dispatch and qualification schemas. It verifies exact SQL definitions and records
`qualified-object-publication-v1-20261014`. No request installs it. A separate
policy-control row pins the eligibility policy and qualification authority;
changed authority requires explicit generation rotation. Lost control/revision
records cannot be silently recreated over retained work.

[`stageQualifiedObjectUpload`](../deploy/cloudflare/src/qualifiedObjectPublication.js)
accepts only the prepared lease, complete profile, policy, assignment digest and
source digest. It checks complete source/pose/model/features/quality integrity,
current profile expiry/revocation, exact contributed Scene membership, fresh
trusted official Gen4 coverage and a new original-source protection challenge.
The private original-source lookup must independently recognize that assignment.
An uploader's pins alone grant no assignment or protection authority.

The bounded private payload uses existing create-only artifact ownership journals
and deletion fences. After delivery, all eligibility checks repeat. One guarded
D1 transaction binds the qualification and payload to the separate candidate,
then moves its lease to submitted and locations to quarantine. Staging earns zero
credit. There are at most eight pending qualified candidates, each holding one to
four locations. The old audited and new qualified namespaces cannot share a lease.

[`settleQualifiedObjectUpload`](../deploy/cloudflare/src/qualifiedObjectPublication.js)
rechecks current eligibility, writes the sanitized index artifacts and repeats
eligibility after delivery. Its final transaction compares the complete captured
candidate, account, qualification generation, lease generation/expiry, locations,
coverage, contributed Scenes, policy authority and owned artifact journals. The
fresh protection receipt and policy must still be valid at the transaction's
current time. A changed/deleted/revoked/expired dependency refuses admission.

The same transaction writes an immutable qualified acceptance, publishes all
locations, records one unique `lease:<id>` ledger entry with reason
`qualified_device_work`, and increases the banked balance. A per-operation token
fences every subsequent statement. A late statement failure rolls back the whole
award and publication. Concurrent settlement and lost replies recover the same
acceptance; retries earn zero additional credit and need no repeated private
check after acceptance. Removing a runtime policy or revoking a profile does not
erase an already accepted receipt. Account deletion revokes access, cancels pending
work and forfeits unused credit while retaining published work and financial history.

Receipts explicitly say `admissionMode: qualified-device-v1`,
`verification: qualified-profile-and-upload-integrity` and
`independentlyRecomputed: false`. Qualification proves numerical compatibility of
the saved sample, not authentic computation of every later upload. The fully
audited writer keeps its separate native approval requirements.

## Offline recovery

[`financial_restore`](../community/financial_restore.py) now exports version 3
when the qualified namespace exists. In addition to balances, ledger, paid replies
and optional queued-search holds, it captures the exact qualification/publication
schema and the current policy, requests, revocations, candidates, acceptances,
leases, locations, coverage, publications and owned artifact journals. Accepted
work must reconcile to its once-only qualified award and exact publication prefix.

An older financial snapshot cannot authorize the new namespace. A restored copy
with changed qualification generations, missing journals/publications, changed
policy or weakened SQL fences fails comparison. Current deletion and financial
authority still need independently consistent cutoffs; this checker never repairs
balances, grants eligibility, imports provider data or opens admission.

The whole-SQL-dump rehearsal preserves these records and fences locally. Existing
legacy upgrade/provider import tools are **not** expanded by this change; they
continue to refuse unsupported optional schemas. Integrated provider/secret/R2
recovery and larger bounded corpus import remain release work.

## Evidence and next work

[Windows evidence](evidence/qualified-object-publication-20261014.json): **61 Node,
47 Python and 16 actual local workerd checks** pass, with no skips. Fifteen Node
cases and twelve Python cases are new; the rest verify the affected audited,
eligibility, financial and queued-search paths. Four fresh workerd processes use
real local D1/R2 persistence for staging, publication, receipt replay and deletion.
Coverage, accounts, qualifications, models, protection, outputs and credits in
every fixture are synthetic. Original failed attempts are preserved privately.

No actual model/Mac qualification, live coverage test, cloud account read, provider
call, deployment, Actions run or indexing restart occurred. Next connect automatic
qualified assignment/delivery and actual approved private setup; finish Object
search execution, shared allocation for qualification/other paid work, and bounded
sealed corpus/import/recovery. The operational hold and real
[launch gates](PRODUCTION_ACCEPTANCE.md) remain in force.
