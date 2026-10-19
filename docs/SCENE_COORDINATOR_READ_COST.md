# Bounded Scene coordinator reads

**Lookup indexes applied; normal coordinator/browser changes remain undeployed.** The real
[two-Scene trial](FINITE_SCENE_TRIAL.md) remains incomplete. Its accepted work,
credit replies, failure and independently verified closure are unchanged.

## Changed behavior

The normal account dashboard computes corpus totals, import parts and country/
generation lists. The finite contributor previously requested that full dashboard
just to read its balance. Assignment and upload also scanned historical published
locations. Those reads grow even when a batch contains only two new locations.

- `GET /api/me?credit=1` now returns a versioned, authenticated account-only credit
  summary. It reads the account's balance without corpus statistics or R2 access.
  Queued mode retains the existing bounded reservation expiry and banked/reserved/
  spendable-credit calculation. Missing queue schema fails closed. Full dashboard
  and browser `lite=1` behavior are preserved; they are not made constant-cost.
- The finite client explicitly selects/checks that credit contract. It never falls
  back to the costly dashboard. Processing files/models and native provenance are
  unchanged; this is not a new runtime qualification.
- Three additive lookup indexes cover unpublished locations, non-null active lease
  IDs and active account leases. Pending selection repeats `state!='published'`,
  already implied by its existing state conditions, so the partial index can skip
  historical publications. All existing assignment, catalog, qualification,
  generation, account/deletion and atomic publication/credit fences remain.
- Future private receipts retain at most 32 per-attempt method/path/status/usage
  entries. No query strings, authorization, bodies, scores or location IDs are
  recorded. The first usage/network stop reason survives subsequent blocked calls;
  the original trial's generic stop code is preserved, not rewritten.

## Measured local result

An actual local workerd/D1/R2 fixture adds **1,024 synthetic published background
records** around the two pending locations. The full-dashboard probe used 2,053
reads and stopped under the unchanged 2,000-read limit. After selecting account-only
credit but before adding lookup indexes, assignment used 1,048 reads and upload
1,064; their combined path stopped before publication. Those diagnostic failures
are preserved privately.

With the lookup indexes and account-only credit path, the synthetic assignment,
upload, qualified publication, zero-credit replay and balance check passed using
**139 reads, 49 writes, two R2 puts and 12,320 stored bytes**. Each account-only
credit request used three reads including authentication/schema checks. One batch
ledger entry awards two units; replay adds none. Synthetic account/qualification/
feature data is not authentic inference or a reconciliation of the real trial.
This fixture does not include account recovery, native startup or imagery costs.

[Evidence](evidence/scene-read-cost-20261014.json) records 31 Node, 10 Python and
14 actual local workerd checks without skips, plus a separate actual local workerd
upgrade rehearsal using synthetic data in the older deployed schema shape. That
rehearsal preserved credentials, credits, paid replies, publications, rollback and
privacy fences. It is not a live provider/secret recovery test.

## Browser credit and search controls

The browser now uses versioned `GET /api/me?controls=1` after queued/completed
searches, price changes and cancellation. It returns current account credit,
price, search configuration/cohort availability and result limits without corpus
statistics, work history, R2 access or a native service call. The existing
`credit=1` contract is unchanged. Anonymous/revoked sessions use
`GET /api/status?controls=1`, which exposes no account balance and retains saved
deletion-receipt recovery. Rate limits, schema/authentication and pricing gates stay
in place. Queued mode keeps the existing bounded reservation-expiry maintenance;
that can update expired job state, but does not debit credit or execute a search.

The client validates the complete control/credit contract, including spendable
versus reserved units. Unknown/malformed responses fail closed without retrying a
full dashboard. Shared filters/counts remain at their last full refresh; initial
load, account recovery and explicit service checks still load the full dashboard.
Changing accounts drops old private work/results/price approval; an older response
cannot overwrite a newer account refresh. Saved requests/replies stay in their
existing account-scoped journal, and a changed price still requires explicit review.
The account text is shorter, with a reserved-credit explanation shown only when needed.

[Browser evidence](evidence/browser-account-controls-20261014.json) records **29
Node checks and 15 actual local workerd/D1/R2/rate-limit checks**, no skips.
Actual browser refresh/search/cancel code ran in a local VM; this is not a real
browser/device installation or hosted walkthrough. With 1,024 synthetic published
Scene records, the current controls path used **three reads**, and fresh qualified
Scene capability checking added **one read**. Both made zero writes, R2 accesses
or native calls. That fixture's older `lite=1` dashboard used **4,100 reads**;
its data shape differs from the earlier 2,053-read fixture above. Queued reservation,
price-review, cancellation, account-switch/deletion and stale-response paths were
checked with synthetic authority. No source-only result establishes provider prices,
capacity or a live release. Worker/assets must be deployed together after approval;
the existing-receipt maintenance scope does not include this website update.

## Activation boundary

[Migration 0005](../deploy/cloudflare/migrations/0005_coordinator_read_cost.sql)
contains only the three `CREATE INDEX IF NOT EXISTS` statements. Fresh offline
initialization includes them. Existing databases need explicit operator maintenance;
no HTTP request creates indexes and historical migration 0004 stays unchanged.
`schema-plan.mjs --read-cost --output <new-file>` generates the same data-free plan.
It can be applied repeatedly without changing account, ledger, publication, paid
reply, trigger or schema-contract data. Building indexes itself can incur database
read/write/storage charges. The laptop user approved the specific maintenance:
all three were applied to existing staging and their definitions read back at
409 observed reads / 88 writes in total. [The operation](SCENE_ACCEPTANCE_RECOVERY.md)
restored and independently verified exact closed staging. No normal source/browser
activation or invoice-cap/capacity proof follows from index installation.

The single hosted-trial consent is consumed. [Recovery is now prepared](SCENE_ACCEPTANCE_RECOVERY.md)
from the real sealed local delivery and saved native files, with a read-only private
route checked locally. The approved maintenance/recovery attempt then stopped on
a local launcher failure before any receipt request. Its fix is checked with an
actual offline owned child. A separately approved corrected attempt stopped on its
first HTTP 403 without usage metadata; exact closed staging was verified again.
The separately approved [direct D1 operator path](SCENE_RECEIPT_OPERATOR.md) then
confirmed the existing two-Scene award and stable balance twice at 32 actual reads /
zero writes, without deployment. Its scope is consumed. Do not raise the
old threshold, take another assignment or renew qualification from these fixtures.
Automatic contributor-only snapshot refresh and genuinely earned online search,
trusted Windows/Mac installation, measured provider costs/recovery and endurance
remain separate launch work. Larger-corpus shard pruning and cached dashboard
summaries are not established by this bounded fixture.
