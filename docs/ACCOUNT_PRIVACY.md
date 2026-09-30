# Account deletion and retained contributions

This feature is implemented and tested locally on the development branch. It
has not yet been deployed or validated against live Community resources.

On the hosted website, open **Index → Delete my account**, read the warning,
type **DELETE**, and choose **Permanently delete my account**. The option is
shown only when the server advertises account-deletion support; the loopback
Python demonstration does not implement hosted account deletion.

Deleting an account permanently revokes its session and recovery code, removes
saved server search results, closes its unused credit balance, expires device
qualifications, and returns unfinished locations to the work queue. A desktop
worker using the old code loses access; it cannot earn more credits or publish
new contributions for that account. Already verified anonymous contributions
stay in the shared pool under their original opaque contributor identifier.
Deletion is not a way to revoke results that someone already downloaded.

The browser removes this account's pending searches and results, saved search
forms, preferences and this site's map-app connection. It preserves other
accounts' search journals and unrelated browser storage. A local tombstone
blocks delayed search results in other open tabs. Clearing browser storage or
using another browser removes that client-side marker; the server still
enforces deletion. Files downloaded to the PC, the desktop worker's private
folder, the clipboard and data sent to another map service are not erased.

## Interrupted deletion

Before sending the request, the browser saves an account-bound random receipt
key. If the response is lost, **Check deletion status** reuses that request,
including after browser restart or session revocation. This receipt only
confirms deletion and does not restore account access or return search data.
A different connected account cannot use it. A 401 response alone does not
confirm deletion: retain the browser data, restore the original account if its
code still works, and retry. Damaged browser storage or an unresolved outcome
needs operator help; do not silently erase the evidence.

## Server records and cleanup

The D1 transaction records one receipt, closes credits in the ledger, revokes
credentials, deletes search rows and expires/releases unfinished work together.
Database fences reject late credential recovery, search settlement, credits,
lease assignment, qualification and publication after the tombstone. Anonymous
account IDs, accounting entries, deletion receipts and published contribution
proofs are retained for integrity. They are pseudonymous records, not a claim
that the operator or provider cannot correlate activity.

Nonpublished candidate metadata is cleared and its quarantine blob enters a
durable cleanup queue. The deletion request tries at most 16 blobs immediately;
the hourly Worker trigger retries at most 64 globally. Storage failures remain
pending. Only generated `scene-quarantine/<lease>/<digest>.i8` paths may be
removed. Other paths are marked `needs_review`, never deleted by this routine.
Published indexes and input catalogs are outside this cleanup operation.

Deletion of active records does not instantly erase Cloudflare backup copies.
The release still needs a documented backup retention period and a tested
restore procedure that reapplies deletion records before exposing old data.
The operator must also resolve unreferenced storage produced by interrupted or
already in-flight uploads. That wider storage-retention policy is not completed
by the account-deletion button or its quarantine cleanup queue.

## Deployment and verification

`ready()` upgrades older account tables by adding `deleted_at`, creates receipt
and cleanup tables, and installs database fences after work-queue migrations.
It preserves existing accounts and published contributions. Future changes to
fence definitions need an explicit versioned migration; `IF NOT EXISTS` does
not replace an existing trigger. Back up and exercise this upgrade in staging
before deploying it to the confirmed Community database. Do not run it against
unrelated resources.

Both Worker configuration files include the hourly cleanup trigger. A deployment
must retain it, provide the confirmed private `INDEX` binding, enable the API
limiter and monitor failed scheduled runs plus `pending`/`needs_review` cleanup
counts. The local tests do not establish a live cleanup latency guarantee or a
resource budget. An unchanging set of failed jobs also requires operator review.

The JavaScript tests exercise deletion transactions, rollback, response loss,
account changes, browser-storage failures, delayed searches, qualifications and
audits. The bundled Worker is tested in local workerd/D1/R2 using the checked-in
compatibility date, including the real scheduled handler. No real user account
or live R2 object is deleted by these tests.
