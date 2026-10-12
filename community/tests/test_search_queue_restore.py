from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest

from community.financial_restore import (FinancialRestoreError, export_financial_snapshot,
                                         check_financial_restore, validate_snapshot)
from community.search_queue_restore import QueueRestoreError, queue_state
from community.search_snapshot import CONFIRMED_STAGING_RESOURCE, digest, encoded

ROOT = Path(__file__).resolve().parents[2]
ACCOUNT, JOB = 'a'*32, 'b'*32
QUERY = '{"lane":"scene","prompt":"PRIVATE search café","excluded":[{"lat":1e-7}]}'
KEY = 'q1.0000001900.' + 'c'*32
PIN = json.dumps({'contractVersion': 2, 'policyId': 'synthetic.fixture',
                  'runtimeSha256': 'd'*64, 'snapshotSha256': 'e'*64})


class QueuedFinancialRestoreTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.current = self.root / 'current.sqlite'
        self.repaired = self.root / 'repaired'; self.repaired.mkdir()
        self.restored = self.repaired / 'restored.sqlite'
        with closing(sqlite3.connect(self.current)) as sql, sql:
            sql.executescript('''CREATE TABLE accounts(id TEXT PRIMARY KEY,token_hash TEXT,units INTEGER,deleted_at INTEGER);
                CREATE TABLE ledger(id INTEGER PRIMARY KEY,account_id TEXT,units INTEGER,reason TEXT,reference TEXT UNIQUE);
                CREATE TABLE searches(id TEXT PRIMARY KEY,account_id TEXT,idempotency_key TEXT,query TEXT,result_json TEXT,
                    UNIQUE(account_id,idempotency_key));''')
            sql.executescript((ROOT / 'deploy/cloudflare/search-queue.sql').read_text())
            sql.execute('INSERT INTO accounts VALUES(?,?,100,NULL)', (ACCOUNT, 'PRIVATE session'))
            sql.execute("INSERT INTO ledger VALUES(1,?,100,'verified_work','lease:synthetic-only-not-real-work')", (ACCOUNT,))
            sql.execute('''INSERT INTO search_jobs(id,account_id,idempotency_key,query_digest,query_json,lane,
                binding_json,cost_units,state,created_at,expires_at) VALUES(?,?,?,?,?,'scene',?,30,'queued',1900,5500)''',
                (JOB, ACCOUNT, KEY, 'sha256:'+digest(QUERY.encode()), QUERY, PIN))
        self.export()
        self.copy_current()

    def export(self, name='export'):
        report = export_financial_snapshot(self.current, digest(self.current.read_bytes()), self.root / name,
                                           exported_at=2000, environment='staging')
        self.snapshot = self.root / name / 'financial-snapshot.private.json'
        self.snapshot_pin = report['snapshotSha256']

    def copy_current(self):
        shutil.copyfile(self.current, self.restored)
        self.repin()

    def repin(self):
        raw = encoded({'version': 1, 'scope': 'offline-privacy-repaired-community-copy', 'liveReady': False,
            'resource': CONFIRMED_STAGING_RESOURCE, 'databaseSha256': digest(self.restored.read_bytes())})
        (self.repaired / 'restore-report.json').write_bytes(raw)
        self.report_pin = digest(raw)

    def mutate(self, statement, values=(), *, source=None, immutable=False):
        with closing(sqlite3.connect(source or self.restored)) as sql, sql:
            trigger = sql.execute("SELECT sql FROM sqlite_master WHERE name='search_jobs_identity'").fetchone()
            if immutable: sql.execute('DROP TRIGGER search_jobs_identity')
            sql.execute(statement, values)
            if immutable: sql.execute(trigger[0])
        if source is None: self.repin()

    def check(self, name='check', **changes):
        return check_financial_restore(self.repaired, self.report_pin, self.snapshot, self.snapshot_pin,
            self.root / name, **({'not_before': 1900, 'now': 2100, 'environment': 'staging'} | changes))

    def failed(self, error, code):
        with self.assertRaisesRegex(error, code): self.check()
        report = (self.root / 'check/failure-report.json').read_bytes()
        self.assertFalse(json.loads(report)['complete'])
        self.assertFalse((self.root / 'check/financial-report.json').exists())
        for value in (ACCOUNT, JOB, KEY, QUERY, 'PRIVATE', str(self.root)):
            self.assertNotIn(value.encode(), report)

    def test_v2_cutoff_preserves_holds_and_private_raw_bytes_without_modifying_inputs(self):
        before = [p.read_bytes() for p in (self.current, self.restored, self.snapshot)]
        document = json.loads(self.snapshot.read_bytes())
        self.assertEqual(document['version'], 2)
        self.assertEqual(document['queue']['reservedUnits'], 30)
        self.assertNotIn(QUERY.encode(), self.snapshot.read_bytes())
        result = self.check()
        self.assertTrue(result['queuedFinancialStateMatchesTrustedCutoff'])
        self.assertEqual(result['queuedSearches'], 1); self.assertEqual(result['reservedSearchUnits'], 30)
        self.assertFalse(result['liveReady']); self.assertFalse(result['creditRecoveryVerified'])
        self.assertEqual(before, [p.read_bytes() for p in (self.current, self.restored, self.snapshot)])
        self.assertNotIn(ACCOUNT.encode(), (self.root/'check/financial-report.json').read_bytes())

    def test_missing_reservation_fails_even_when_balances_and_ledger_match(self):
        self.mutate('DELETE FROM search_jobs')
        self.failed(FinancialRestoreError, 'restored_queued_financial_state_differs')

    def test_changed_cost_with_same_bank_balance_cannot_pass(self):
        self.mutate('UPDATE search_jobs SET cost_units=35', immutable=True)
        self.failed(FinancialRestoreError, 'restored_queued_financial_state_differs')

    def test_exact_query_spelling_cannot_be_replaced_by_numerically_equivalent_json(self):
        other = QUERY.replace('1e-7', '0.0000001')
        self.mutate('UPDATE search_jobs SET query_json=?,query_digest=?', (other, 'sha256:'+digest(other.encode())), immutable=True)
        self.failed(FinancialRestoreError, 'restored_queued_financial_state_differs')

    def test_altered_raw_query_digest_is_invalid_even_before_authority_comparison(self):
        self.mutate('UPDATE search_jobs SET query_json=?', (QUERY+' ',), immutable=True)
        self.failed(QueueRestoreError, 'invalid_queued_financial_state')

    def test_lost_claim_token_and_attempt_counter_cannot_restore_an_old_owner(self):
        self.mutate("UPDATE search_jobs SET state='claimed',claim_token=?,claim_until=2200,attempts=1", ('f'*64,), source=self.current)
        self.export('claimed-export'); self.copy_current()
        self.mutate('UPDATE search_jobs SET claim_token=?', ('0'*64,))
        self.failed(FinancialRestoreError, 'restored_queued_financial_state_differs')

    def test_expired_wall_clock_does_not_silently_release_a_durable_hold_or_change_claims(self):
        before = self.restored.read_bytes()
        self.assertEqual(self.check(now=6000)['reservedSearchUnits'], 30)
        self.assertEqual(before, self.restored.read_bytes())

    def test_terminal_tombstones_are_preserved_even_without_any_reservation(self):
        self.mutate("UPDATE search_jobs SET state='cancelled',query_json=NULL,error_code='search_cancelled'", source=self.current)
        self.export('cancelled-export'); self.copy_current()
        self.assertEqual(self.check('terminal-ok')['reservedSearchUnits'], 0)
        self.mutate('DELETE FROM search_jobs')
        self.failed(FinancialRestoreError, 'restored_queued_financial_state_differs')

    def test_settled_queue_receipt_has_exact_once_only_debit_and_saved_price(self):
        with closing(sqlite3.connect(self.current)) as sql, sql:
            sql.execute("UPDATE search_jobs SET state='settled',query_json=NULL,completion_nonce=?,attempts=1", ('f'*64,))
            sql.execute("INSERT INTO ledger VALUES(2,?,-30,'search',?)", (ACCOUNT, 'search:'+JOB))
            sql.execute('INSERT INTO searches VALUES(?,?,?,?,?)', (JOB, ACCOUNT, KEY, 'sha256:'+digest(QUERY.encode()),
                json.dumps({'searchId': JOB, 'costUnits': 30, 'map': {'name': 'PRIVATE paid map'}})))
            sql.execute('UPDATE accounts SET units=70')
        self.export('paid-export'); self.copy_current()
        self.assertEqual(self.check('paid-ok')['reservedSearchUnits'], 0)
        self.mutate('UPDATE searches SET result_json=?', (json.dumps({'searchId': JOB, 'costUnits': 29}),))
        self.failed(QueueRestoreError, 'invalid_queued_financial_state')

    def test_missing_or_weakened_queue_guard_cannot_approve_an_empty_queue(self):
        self.mutate('DELETE FROM search_jobs')
        self.mutate('DROP TRIGGER search_jobs_credit_guard')
        self.failed(QueueRestoreError, 'queued_financial_schema_mismatch')

    def test_unreviewed_extra_queue_trigger_cannot_change_recovered_behavior(self):
        self.mutate('CREATE TRIGGER search_jobs_extra AFTER UPDATE ON search_jobs BEGIN DELETE FROM search_jobs; END')
        self.failed(QueueRestoreError, 'queued_financial_schema_mismatch')

    def test_whole_queue_schema_cannot_disappear_from_recovered_copy(self):
        with closing(sqlite3.connect(self.restored)) as sql, sql:
            for name, in sql.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'search_jobs%'").fetchall():
                sql.execute('DROP TRIGGER '+name)
            sql.executescript('DROP TABLE search_jobs; DROP TABLE search_queue_revision;')
        self.repin()
        self.failed(FinancialRestoreError, 'restored_queued_financial_state_differs')

    def test_v1_authority_cannot_ignore_new_queue_state(self):
        document = json.loads(self.snapshot.read_bytes()); document.pop('queue'); document['version'] = 1
        self.snapshot.write_bytes(encoded(document)); self.snapshot_pin = digest(self.snapshot.read_bytes())
        self.failed(FinancialRestoreError, 'queued_financial_authority_required')

    def test_incomplete_or_impossible_v2_summary_is_rejected(self):
        document = json.loads(self.snapshot.read_bytes())
        for changed in ({'active': 0, 'claimed': 1}, {'reservedUnits': -1}, {'jobsSha256': 'invalid'}, {'extra': True}):
            bad = {**document, 'queue': {**document['queue'], **changed}}
            with self.subTest(changed=changed), self.assertRaisesRegex(QueueRestoreError, 'invalid_queued_financial_snapshot'):
                validate_snapshot(bad, 'staging', 1900, 2100)

    def test_invalid_source_cannot_export_approval_or_private_failure_text(self):
        self.mutate('UPDATE search_jobs SET binding_json=?', ('PRIVATE malicious binding',), source=self.current, immutable=True)
        with self.assertRaisesRegex(QueueRestoreError, 'invalid_queued_financial_state'):
            self.export('bad-source')
        self.assertFalse((self.root/'bad-source/export-report.json').exists())
        self.assertNotIn(b'PRIVATE', (self.root/'bad-source/failure-report.json').read_bytes())

    def test_held_credit_cannot_exceed_bank_balance_even_with_restored_trigger_definitions(self):
        self.mutate('UPDATE search_jobs SET cost_units=101', immutable=True)
        self.failed(QueueRestoreError, 'invalid_queued_financial_state')

    def test_queue_comparison_rejects_deleted_account_rows(self):
        with closing(sqlite3.connect(self.restored)) as sql, sql:
            sql.execute('DROP TRIGGER search_jobs_delete_private')
            sql.execute('UPDATE accounts SET deleted_at=2000,units=0')
        with closing(sqlite3.connect(self.restored)) as sql:
            with self.assertRaisesRegex(QueueRestoreError, 'queued_financial_schema_mismatch'): queue_state(sql)


if __name__ == '__main__':
    unittest.main()
