# Account deletion and retained contributions

This feature is deployed on the isolated Community staging site. Disposable
live checks passed account recovery, session revocation, deletion and lost-response
receipt recovery. Production rollout, retention and a complete restore exercise
remain release requirements.

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

Nonpublished candidate metadata is cleared. Before every new scene quarantine
or final-index upload, an immutable D1 write intent records the account, lease,
key, digest, size and time. Account deletion queues these intents atomically
with its tombstone, including uploads that failed or have not yet created a
candidate. The deletion request tries at most 16 keys immediately; the hourly
Worker trigger retries at most 64 globally. Storage failures or unconfirmed
writes remain `pending`.

Cleanup replaces the private payload with a permanent 30-byte marker rather
than removing the key. New scene writers use R2 create-only conditional writes,
so a delayed upload cannot overwrite that marker and recreate private data.
The marker has `visionPrivacyFence=1` metadata, contains no account or location
data, and must never be physically deleted or expired by a storage lifecycle
rule. Its key, journal entry and associated pseudonymous records remain. The
conditional-write contract is documented in Cloudflare's
[R2 Workers API](https://developers.cloudflare.com/r2/api/workers/workers-api-reference/).

Only generated `scene-quarantine/<lease>/<digest>.i8` or journaled
`four-view-v4/<lease>.i8` keys with a deleted owner and an owned scene lease may
be fenced. Legacy quarantine keys may lack an intent but still need lease
ownership. Malformed or conflicting provenance is marked `needs_review`;
published keys are marked `retained` and their bytes are preserved. Successful
cleanup is `fenced`. Published indexes and input catalogs are retained.

Deletion of active records does not instantly erase Cloudflare backup copies.
An [offline restore safeguard](PRIVATE_RESTORE.md) now reapplies independently
pinned current deletion receipts to a new private SQLite copy before exposure.
It revokes restored access, removes private results and preserves contributions;
synthetic tests cover rollback, repeat repair and immutable outputs. The release
still needs a documented backup retention period and a complete staging
restore/import exercise before reopening D1.

Required-archive deployments also store each deletion receipt independently in
the private Community R2 bucket before acknowledging success. Keys contain an
account-ID hash; object metadata contains only a format marker and checksum.
The private body retains the minimum pseudonymous receipt needed for restore.
Conditional creation and bounded checksum readback prevent uncertain or changed
copies from being acknowledged. The hourly handler retries unarchived receipts.
An outage preserves revocation and returns a retryable error; the original
private deletion request can recover the response without restoring access.

Configure `DELETION_ARCHIVE_REQUIRED=1`, the exact
`DELETION_ARCHIVE_ENVIRONMENT` (`production` or `staging`), matching
`DELETION_ARCHIVE_DB_ID` and `INDEX_BUCKET_NAME`. Only the two confirmed Community
resource mappings are accepted. A wrong or missing required binding refuses
deletion before changing credentials. Local demonstrations may omit archival.
Unit and actual local workerd/D1/R2 tests cover readback, response loss, damaged
storage, database acknowledgement failure and scheduled recovery. This archive
extension passed live staging rollout on 2026-10-02: a disposable anonymous
account stayed revoked, exact deletion replay succeeded, and the database
recorded one deletion debit and a matching archived checksum. A separate
signed-in R2 dashboard read matched the 387-byte canonical receipt checksum,
resource and account. All 13 website assets and privacy headers remained intact.
This is archive/deletion evidence; complete restore/import remains unverified.
During restore, freeze
writers and establish a fresh, complete archive inventory, including any
pending D1 receipts; a directory of selected objects is insufficient.
The new journal/fence protocol covers scene writes by this Worker version,
including writes already in flight at deletion. It does not inventory historical
untracked storage, clean up abandoned work from active accounts, or protect
object/prototype uploads. A wider storage-retention policy and those separate
writer protocols remain release requirements. Intent/fence counts and retained
storage grow over time; measure their resource cost before release.

## Deployment and verification

`ready()` upgrades older account tables by adding `deleted_at`, creates receipt,
cleanup and scene-intent tables/indexes, and installs database fences after
work-queue migrations. Installing the new protocol and requeuing old `removed`
jobs as `pending` happens in one D1 batch, so a partial upgrade cannot leave
old deletions without the new storage protection.
It preserves existing accounts and published contributions. Future changes to
fence definitions need an explicit versioned migration; `IF NOT EXISTS` does
not replace an existing trigger. Back up and exercise this upgrade in staging
before deploying it to the confirmed Community database. Do not run it against
unrelated resources.

Before this protocol is enabled in a live environment, close contributions,
stop and drain all old scene upload/audit writers, then deploy only compatible
create-only writers and exercise the upgrade in staging. An old unconditional
writer can overwrite the marker; a gradual rollout or rollback to those writers
does not preserve this guarantee. Keep writes closed during an incompatible
rollback. Do not remove markers, journals or ownership records while an old
request could still finish. For pre-journal data, retain uncertain keys and
resolve provenance through operator review rather than a broad bucket delete.

Both Worker configuration files include the hourly cleanup trigger. A deployment
must retain it, provide the confirmed private `INDEX` binding, enable the API
limiter and monitor failed scheduled runs plus `pending`/`needs_review` cleanup
counts. The local tests do not establish a live cleanup latency guarantee or a
resource budget. An unchanging set of failed jobs also requires operator review.

The JavaScript tests exercise deletion transactions, rollback, response loss,
account changes, browser-storage failures, delayed searches, qualifications,
audits, immutable intents, failed storage, provenance and migration rollback.
The bundled Worker is tested in local workerd/D1/R2 using the checked-in
compatibility date, including the real scheduled handler and quarantine/final
uploads paused both before and after R2 commit while deletion goes through the
API. The permanent marker blocks subsequent conditional creates. No real user
account or live R2 object is changed by these tests.
