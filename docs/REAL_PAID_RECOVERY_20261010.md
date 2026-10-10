# Real paid-reply and storage recovery — 10 October 2026

An actual private staging D1 export and 13 actual R2 objects were restored into
an isolated local Cloudflare simulator. All 17 application tables, 256 rows,
schema objects and autoincrement values survived exactly. The restored files
include three contributed index blobs, nine deletion receipts and the active
native search bundle. Their bytes and observed metadata match the provider
readback, including after a fresh process starts.

The service returned all three genuinely paid Scene replies byte for byte,
including concurrent retries and a fresh-process restart. The account keeps
six banked units: 18 earned units minus 12 spent. No extra debit, award, native
execution or live write occurred. Local account recovery rotates only its local
session; all nine deleted accounts remain revoked, with zero credit and no saved
private searches. Their restored database fences reject reactivation.

The exercise passes 124 actual local workerd checks. It also found and fixed a
real converter defect: Cloudflare can export a dependent table's rows before
declaring its foreign-key parent. The converter now declares all tables first,
then replays the remaining statements in their original order inside the same
transaction. Foreign keys stay enabled and are checked before completion.
Data-derived declarations are refused; changed retained SQL cannot complete.

The corrected converter also reproduced the previously approved full production
copy: all 364,056 historical rows, every schema object and autoincrement value
match the preserved original. Conversion and complete comparison took 15.453
seconds. The affected export/financial regression passes 36 Windows checks
without skips or failures.

This is a point-in-time **local recovery exercise**, with no drained live-writer
cutoff, provider restore, secret restoration or new native inference. The strict
whole-history accounting checker still correctly rejects old staging fixture
credit reasons. Those original records were preserved, without relabeling them
as accepted work; exact recovery and the active earned-credit reconciliation
do not approve that complete historical ledger. A clean genuine-work accounting
source and independent current financial/deletion authority remain release
requirements.

Original converter failures, the initial restricted-folder/test-selector
failures, the first simulator launch and the schema comparison failure remain
private. The sole schema difference was independently identified as Cloudflare's
own `_cf_METADATA` table; every application schema object matches exactly.
The successful attempt uses a new private destination. Private database,
credentials, prompts, location data and object bodies stay outside Git.

The running Scene pilot and refresher were unchanged. Complete provider/secret
recovery, post-backup reconciliation, fresh writer drain, capacity and all other
launch gates remain open. See the [redacted receipt](evidence/real-paid-recovery-20261010.json).
