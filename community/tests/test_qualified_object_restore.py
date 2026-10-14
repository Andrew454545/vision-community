"""Actual cross-runtime SQLite recovery; all coverage, scores and authority synthetic."""
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import time
import unittest

from community.financial_restore import (FinancialRestoreError, export_financial_snapshot, check_financial_restore)
from community.qualified_object_restore import (QualifiedObjectRestoreError, qualified_object_state,
                                                SCHEMA_SHA256, validate_qualified_object_snapshot)
from community.search_snapshot import CONFIRMED_STAGING_RESOURCE, digest, encoded

ROOT = Path(__file__).resolve().parents[2]
ACCOUNT = 'b'*32


class QualifiedObjectRestoreTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = os.environ.get('VISION_TEST_NODE') or shutil.which('node')
        if not cls.node:
            raise RuntimeError('existing_node_runtime_required_for_qualified_object_fixture')

    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.current = self.root / 'current.sqlite'
        self.repaired = self.root / 'repaired'; self.repaired.mkdir()
        self.restored = self.repaired / 'restored.sqlite'
        self.now = int(time.time())

    def seed(self, mode='published'):
        r = subprocess.run([self.node, str(ROOT / 'deploy/cloudflare/tools/fixtures/export-qualified-object.mjs'), str(self.current), mode],
                           cwd=ROOT, capture_output=True, text=True, timeout=30,
                           creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(json.loads(r.stdout)['nativeInference'])
        self.now = int(time.time())
        self.export()
        shutil.copyfile(self.current, self.restored); self.repin()

    def export(self, name='export'):
        report = export_financial_snapshot(self.current, digest(self.current.read_bytes()), self.root / name,
                                           exported_at=self.now, environment='staging')
        self.snapshot = self.root / name / 'financial-snapshot.private.json'
        self.snapshot_pin = report['snapshotSha256']

    def repin(self):
        raw = encoded({'version': 1, 'scope': 'offline-privacy-repaired-community-copy', 'liveReady': False,
                      'resource': CONFIRMED_STAGING_RESOURCE, 'databaseSha256': digest(self.restored.read_bytes())})
        (self.repaired / 'restore-report.json').write_bytes(raw); self.report_pin = digest(raw)

    def check(self, name='check'):
        return check_financial_restore(self.repaired, self.report_pin, self.snapshot, self.snapshot_pin,
                                      self.root / name, not_before=self.now-20, now=self.now, environment='staging')

    def mutate(self, query, params=()):
        with closing(sqlite3.connect(self.restored)) as sql, sql:
            sql.execute(query, params)
        self.repin()

    def test_v3_cutoff_preserves_acceptance_registry_owned_artifacts_credit_and_paid_reply(self):
        self.seed()
        value = json.loads(self.snapshot.read_bytes())
        self.assertEqual(value['version'], 3); self.assertIsNone(value['queue'])
        self.assertEqual(value['qualifiedObjects']['schemaSha256'], SCHEMA_SHA256)
        self.assertEqual(value['qualifiedObjects']['acceptances'], 1)
        self.assertNotIn(b'synthetic exact saved reply', self.snapshot.read_bytes())
        result = self.check(); self.assertTrue(result['qualifiedObjectStateMatchesTrustedCutoff'])
        self.assertFalse(result['liveReady']); self.assertFalse(result['creditRecoveryVerified'])
        self.assertEqual(self.current.read_bytes(), self.restored.read_bytes())

    def test_whole_sql_dump_restore_keeps_fences_history_and_once_only_award(self):
        self.seed()
        with closing(sqlite3.connect(self.current)) as sql:
            dump = '\n'.join(sql.iterdump())
        self.restored.unlink()
        with closing(sqlite3.connect(self.restored)) as sql:
            sql.executescript(dump); sql.commit()
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'immutable'):
                sql.execute('UPDATE qualified_object_acceptances SET units=0')
        self.repin(); self.assertEqual(self.check()['qualifiedObjectAcceptances'], 1)

    def test_current_deletion_cutoff_retains_publications_and_forfeits_credits(self):
        self.seed('deleted')
        self.assertTrue(self.check()['qualifiedObjectStateMatchesTrustedCutoff'])
        with closing(sqlite3.connect(self.restored)) as sql:
            self.assertEqual(sql.execute('SELECT units FROM accounts WHERE id=?', (ACCOUNT,)).fetchone()[0], 0)
            self.assertEqual(sql.execute('SELECT COUNT(*) FROM qualified_object_acceptances').fetchone()[0], 1)

    def test_pending_candidates_and_policy_cannot_be_omitted_from_cutoff(self):
        self.seed('staged')
        self.mutate('UPDATE qualified_object_policy SET generation=generation+1')
        with self.assertRaisesRegex(FinancialRestoreError, 'restored_qualified_object_state_differs'): self.check()
        self.assertTrue((self.root / 'check/failure-report.json').exists())

    def test_revocation_history_change_requires_new_consistent_authority(self):
        self.seed()
        self.mutate('UPDATE object_qualification_controls SET epoch=epoch+1')
        with self.assertRaisesRegex(FinancialRestoreError, 'restored_qualified_object_state_differs'): self.check()

    def test_missing_publication_or_wrong_ledger_reason_is_not_recovered(self):
        self.seed()
        self.mutate("UPDATE ledger SET reason='verified_work' WHERE reason='qualified_device_work'")
        with self.assertRaisesRegex(QualifiedObjectRestoreError, 'award_mismatch'): self.check()

    def test_missing_accepted_publication_is_not_recovered(self):
        self.seed()
        self.mutate("DELETE FROM published_index WHERE object_index_key IS NOT NULL")
        with self.assertRaisesRegex(QualifiedObjectRestoreError, 'publication_mismatch'): self.check()

    def test_v3_coexists_with_the_existing_exact_queue_authority(self):
        self.seed()
        with closing(sqlite3.connect(self.current)) as sql, sql:
            sql.executescript((ROOT / 'deploy/cloudflare/search-queue.sql').read_text())
        self.export('queue-export'); shutil.copyfile(self.current, self.restored); self.repin()
        value = json.loads(self.snapshot.read_bytes())
        self.assertEqual(value['version'], 3); self.assertEqual(value['queue']['jobs'], 0)
        result = self.check(); self.assertTrue(result['queuedFinancialStateMatchesTrustedCutoff'])
        self.assertTrue(result['qualifiedObjectStateMatchesTrustedCutoff'])

    def test_lost_artifact_journal_blocks_matching_cutoff(self):
        self.seed()
        self.mutate("DELETE FROM account_artifact_writes WHERE artifact_key LIKE 'object-index-v4/%'")
        with self.assertRaisesRegex(FinancialRestoreError, 'restored_qualified_object_state_differs'): self.check()

    def test_weakened_optional_fence_and_empty_partial_namespace_fail_closed(self):
        self.seed()
        self.mutate('DROP TRIGGER qualified_object_acceptance_immutable')
        with self.assertRaisesRegex(QualifiedObjectRestoreError, 'schema_mismatch'): self.check()
        with closing(sqlite3.connect(':memory:')) as sql:
            sql.execute('CREATE TABLE qualified_object_candidates(lease_id TEXT)')
            with self.assertRaisesRegex(QualifiedObjectRestoreError, 'schema_mismatch'): qualified_object_state(sql)

    def test_legacy_financial_snapshot_cannot_authorize_a_qualified_namespace(self):
        self.seed()
        value = json.loads(self.snapshot.read_bytes()); value['version'] = 1
        del value['queue']; del value['qualifiedObjects']
        raw = encoded(value); self.snapshot.write_bytes(raw); self.snapshot_pin = digest(raw)
        with self.assertRaisesRegex(FinancialRestoreError, 'qualified_object_financial_authority_required'): self.check()

    def test_snapshot_fields_are_bounded_and_no_namespace_is_legacy(self):
        with closing(sqlite3.connect(':memory:')) as sql:
            self.assertIsNone(qualified_object_state(sql))
        with self.assertRaisesRegex(QualifiedObjectRestoreError, 'invalid_qualified_object_recovery_snapshot'):
            validate_qualified_object_snapshot({'scope': 'untrusted'})
