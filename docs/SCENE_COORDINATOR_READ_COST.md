# Bounded Scene coordinator reads

**Implemented and checked locally; not deployed or migrated.** The real
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

## Activation boundary

[Migration 0005](../deploy/cloudflare/migrations/0005_coordinator_read_cost.sql)
contains only the three `CREATE INDEX IF NOT EXISTS` statements. Fresh offline
initialization includes them. Existing databases need explicit operator maintenance;
no HTTP request creates indexes and historical migration 0004 stays unchanged.
`schema-plan.mjs --read-cost --output <new-file>` generates the same data-free plan.
It can be applied repeatedly without changing account, ledger, publication, paid
reply, trigger or schema-contract data. Building indexes itself can incur database
read/write/storage charges and needs resolved activation scope; it was not applied
to Cloudflare here. Do not deploy the next trial assuming those indexes exist.

The single hosted-trial consent is consumed. [Recovery is now prepared](SCENE_ACCEPTANCE_RECOVERY.md)
from the real sealed local delivery and saved native files, with a read-only private
route checked locally. It still needs new resolved operational scope, with the current
configuration/financial authority preserved and mandatory closure. Do not raise the
old threshold, take another assignment or renew qualification from these fixtures.
Automatic contributor-only snapshot refresh and genuinely earned online search,
trusted Windows/Mac installation, measured provider costs/recovery and endurance
remain separate launch work. Larger-corpus shard pruning and cached dashboard
summaries are not established by this bounded fixture.
