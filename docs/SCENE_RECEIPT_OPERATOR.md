# Direct read-only Scene receipt check

**Completed under the direct user's precise approval.** This is an
operator reconciliation of the already accepted two-Scene batch. It neither
retries the refused public gateway nor changes its authentication controls.

The user answered **"Approve the two direct database checks"**. Two actual D1
SELECT requests completed, with the first validated before the second started
inside the 120-second request-start window. Each used **16 reads / zero writes**
and reported one provider attempt: **32 reads total, no retries**. Both replies
confirmed two accepted Scenes, one original two-unit award, identical current
banked balance and zero new credit. The current account, recovery hash, schema,
lease, contributed publication digests and stored zero-credit replay contract
passed the existing validator. Balances and raw rows remain private.
[Execution evidence](evidence/scene-receipt-direct-20261014.json) records the result.

No Worker deployment/configuration change, index maintenance, R2 access,
inference, assignment, upload, search, credential rotation, qualification renewal
or task restart occurred. The previously verified closed staging posture was
untouched; this read-only path performed no new closure readback. The two-query
approval is consumed. This closes the existing-batch operator reconciliation,
not public gateway authentication, a full financial cutoff or production acceptance.

The corrected gateway attempt received one HTTP 403 without usage headers and
stopped before its second request. Its cause is unknown: the retained receipt
does not establish whether the refusal came from the gateway or an upstream
service, or how many database reads occurred. Staging restoration and independent
exact closed-state readback succeeded. The failure and original trial remain
unchanged. The later direct-D1 reconciliation above supplements that failure;
it does not rewrite the failed gateway attempt as a success.

The [offline operator helper](../deploy/cloudflare/tools/scene-receipt-operator.mjs)
captures the existing `recoverSceneReceipt` SELECT and its bound parameters,
including the saved account recovery hash. It adds the persisted schema revision
to the same SELECT snapshot. No new publication, credit or authentication writer
is introduced. The existing validator checks the actual returned schema, account/
deletion state, lease, publication digests, original qualified-device ledger award
and replay contract. The local capture fixture only obtains the query; its dummy
schema value cannot authorize a real response. Two validated identical replies
are required. Current balance and the original award remain distinct; replay earns
zero new units. The result explicitly does not verify public gateway authentication.

Private SQL/parameters and raw responses stay in the approved project folder,
outside GitHub and logs shown to users. No recovery code is printed or included
in SQL. The query file contains a derived authentication hash and is private.
Use the D1 **query API** with its structured SQL/parameters. Do not use Wrangler
`d1 execute --file`: the installed CLI implements that through a file-import
upload, which is outside this read-only/no-storage scope.

## Approved execution bounds — preserved

After explicit approval, use only the existing staging D1 database
`17043cb7-5dab-4a6f-84ca-19ae1c14cc05` in the confirmed Community account.
Pin the reviewed source, saved target and private query/parameter digests.
Send at most **two SELECT query requests**, at most **8 KiB per request**, with
no retries and a **120-second deadline for starting requests**. A provider call
already in flight may finish after that deadline; no continuing job is created.
Validate the first response before sending the second. Require complete actual
usage metadata, zero writes, one reported provider attempt and cumulative observed
reads at most **200**. Stop on any failure, missing metadata, changed authority,
balance or exceeded limit. One request may cross the observed stop; it is not a
provider invoice cap. Possible small D1 usage charges remain.

There is **no Worker deployment, endpoint opening, index maintenance, R2/storage
access, imagery/model work, assignment, upload, search, qualification renewal,
credential rotation, new resource or task restart**. Staging remains closed.
The previous gateway approvals did not authorize this distinct API route; the
user supplied its separate precise approval. It authorizes no further calls.

## Local evidence

Three Node checks and eight actual local workerd/D1 checks passed, zero skips.
With 1,024 synthetic historical locations, the composed query used 15 reads per
reply, 30 for the pair, zero writes and no R2 binding. Wrong authentication,
schema changes, publication conflicts, account deletion/forfeiture, changed credit,
missing usage and reported repeated provider attempts fail closed. The local
runtime does not supply remote `total_attempts`; that one field was explicitly
synthetic in the fixture. No hosted retry/capacity evidence is claimed.

The first unit check exposed error masking before query capture; the helper now
preserves that unauthorized error. The first workerd fixture attempted a schema
revision forbidden by the table constraint; its synthetic revision changed to a
permitted but unsupported version. Both failures remain private.
[Supplemental evidence](evidence/scene-receipt-readback-20261014.json) records
the refused hosted attempt, verified closure and these new local checks.
