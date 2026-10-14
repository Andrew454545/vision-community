# Recover the existing Scene receipt

**Prepared and verified locally; live reconciliation still awaits new approval.**
The [original two-Scene trial](FINITE_SCENE_TRIAL.md) and its failure remain intact.
No replacement assignment, inference, upload or hosted request was made.

## Recover saved work, without resubmitting

The [offline preparer](../community/scene_receipt_recovery.py) opens the sealed
delivery journal read-only. Its one accepted entry retains the original two-unit
reply and payload digest; accepted payload JSON was deliberately retired by the
normal outbox. The preparer reconstructs the exact submitted bytes from saved
TSV IDs and four-view records **only to verify that digest**. It checks the pinned
original failed receipt, account/origin, complete native checkpoint/output,
unchanged input digest, CPU1/default-runner record and index layout. Mismatches,
ambiguous source/coordinator IDs, active journals and changed files refuse recovery.
Original files are never updated. The new private plan contains identities and
digests, not credentials or a claim of current server reconciliation.

The [operator-only recovery gateway](../deploy/cloudflare/tools/scene-receipt-recovery.mjs)
has one route and one pinned batch. It authenticates the saved account recovery
code without rotating its session, and checks current deletion state, published
candidate/policy, lease membership, all saved output digests and the original unique
qualified-device ledger award in one consistent SQL statement. It exposes only
SELECT to that helper. There is no R2/native binding, assignment, upload, audit
advancement, qualification renewal, search, credit mutation or background handler.
An unpublished/rejected/mismatched batch cannot be advanced through recovery.
An expired qualification cannot invalidate a historical accepted receipt or grant
a new qualification. Deleted accounts cannot recover forfeited balances.

The response distinguishes the **original award**, **current banked balance** and
**zero newly earned units**. It also returns the existing published-candidate replay
contract, whose zero accepted count means replay, not missing work. Two identical
readbacks are required; a concurrent balance/publication change leaves the check
incomplete. This checks current database acceptance and its unique award, not an
R2 artifact download, original inference authenticity, provider recovery or a new
credit award. There is no invented before/after balance when the old receipt did
not save that baseline.

## Local evidence

[Evidence](evidence/scene-acceptance-recovery-20261014.json) records four Node,
10 Python and 19 actual local workerd/D1 checks, without skips. The workerd
fixture uses synthetic authority/output records and 1,024 historical background
locations. Each successful recovery uses **15 reads, zero writes and no R2**;
the two-read sequence uses 30 reads. Wrong credentials/targets, publication/award
conflicts, unique-credit protection and account deletion are exercised. The first
SQL plan scanned 1,041 rows and correctly stopped. Explicit bounded join order
fixed that scan; the diagnostic and other original fixture/environment failures
remain preserved. The supervisor tests exercise success/timeout contracts; they
are not a real hosted child or a new endurance run.

Preparation against the actual preserved trial matched its reconstructed payload
and unchanged original files, with zero network requests. Private recovery and
rollback configurations both passed offline Wrangler dry runs. They have not been
deployed; the prepared candidate deadline is zero and therefore already closed.

## Proposed finite operational scope — not yet authorized

1. Inspect only the existing staging gateway's settings, subdomain and schedules;
   require them to match the pinned verified closure before changing anything.
   Preserve current variables/bindings/snapshot authority and existing secrets.
2. Apply at most the three additive `CREATE INDEX IF NOT EXISTS` statements in
   [migration 0005](../deploy/cloudflare/migrations/0005_coordinator_read_cost.sql),
   separately, and read back only those index definitions. No account, financial,
   publication, trigger or schema-contract data is rewritten. Record each operation's
   actual D1 usage. Stop further maintenance on missing metadata, unexpected failure
   or cumulative observed usage above **20,000 reads / 20,000 writes**. Index building
   itself can incur charges and cross an observed stop threshold; these limits are
   not a provider invoice cap. Completed additive indexes remain safe and idempotent
   if a later operation fails. Recovery's key lookups do not depend on these indexes;
   ordinary future assignment/upload does.
3. Temporarily deploy the prepared private recovery entrypoint on the same staging
   worker and D1. Pin a fresh credential, exact target and expiry no more than
   **20 minutes** ahead. Run only **two requests**, at most **2 KiB each**, with a
   **120-second supervised child**, at most **200 observed reads**, **zero database
   writes**, **zero R2 reads/writes/uploads** and no retry. Stop on any unexpected
   response, usage, credential or receipt conflict. No recovery code enters logs,
   GitHub, configuration variables or a new provider destination.
4. Restore the pinned closed gateway in a mandatory `finally` path, independently
   verify workers.dev/previews off, empty schedules and exact previous settings,
   and preserve both successful and failed private receipts. Do not mark child
   completion as verified closure. Native allowances and all paused tasks stay closed.

The private plan/configs/SQL live in `work/scene-receipt-recovery-20261014`.
Source must be pinned/frozen and configuration baseline checked again before any
approved execution. The earlier trial approval is consumed; this maintenance and
readback requires its own explicit scope. Small staging usage/storage charges are
possible. No recurring processing, provider/model test, cloud-native compute/search,
new account/resource/plan, public rollout or Actions run is included.

After current receipt recovery, finish automatic contributed-Scene snapshot refresh
and a separately bounded genuinely earned online search/paid-result replay. Existing
platform, trusted-download, cost/recovery and Scene endurance launch gates remain.
