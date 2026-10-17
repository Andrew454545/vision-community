"""Prepared Object allocation recovery on synthetic actual SQLite state."""
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

from community.financial_restore import export_financial_snapshot, check_financial_restore, FinancialRestoreError
from community.qualified_object_restore import QualifiedObjectRestoreError, qualified_object_state
from community.search_snapshot import digest, encoded, CONFIRMED_STAGING_RESOURCE

ROOT = Path(__file__).resolve().parents[2]


class ObjectWorkRestoreTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve(); self.current = self.root / 'current.sqlite'
        self.repaired = self.root / 'repaired'; self.repaired.mkdir(); self.restored = self.repaired / 'restored.sqlite'

    def seed(self, mode='work-ready'):
        node = os.environ.get('VISION_TEST_NODE') or shutil.which('node')
        if not node: raise RuntimeError('existing_node_runtime_required')
        r = subprocess.run([node, str(ROOT / 'deploy/cloudflare/tools/fixtures/export-qualified-object.mjs'), str(self.current), mode],
            cwd=ROOT, capture_output=True, text=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.now = int(time.time())
        report = export_financial_snapshot(self.current, digest(self.current.read_bytes()), self.root / 'export',
                                           exported_at=self.now, environment='staging')
        self.snapshot = self.root / 'export/financial-snapshot.private.json'; self.snapshot_pin = report['snapshotSha256']
        shutil.copyfile(self.current, self.restored); self.repin()

    def repin(self):
        raw = encoded({'version': 1, 'scope': 'offline-privacy-repaired-community-copy', 'liveReady': False,
                      'resource': CONFIRMED_STAGING_RESOURCE, 'databaseSha256': digest(self.restored.read_bytes())})
        (self.repaired / 'restore-report.json').write_bytes(raw); self.report_pin = digest(raw)

    def check(self):
        return check_financial_restore(self.repaired, self.report_pin, self.snapshot, self.snapshot_pin,
            self.root / 'check', not_before=self.now-30, now=self.now, environment='staging')

    def test_ready_request_lease_and_original_source_bytes_survive_matching_v3_cutoff(self):
        self.seed(); value = json.loads(self.snapshot.read_bytes())
        self.assertEqual(value['qualifiedObjects']['assignmentPool']['savedRequests'], 1)
        self.assertTrue(self.check()['qualifiedObjectStateMatchesTrustedCutoff'])
        self.assertNotIn(b'synthetic-pano-a', self.snapshot.read_bytes())

    def test_ready_request_and_qualified_acceptance_survive_whole_sql_dump_restore(self):
        self.seed('work-published')
        with closing(sqlite3.connect(self.current)) as sql: dump = '\n'.join(sql.iterdump())
        self.restored.unlink()
        with closing(sqlite3.connect(self.restored)) as sql: sql.executescript(dump); sql.commit()
        self.repin(); self.assertEqual(self.check()['qualifiedObjectAcceptances'], 1)

    def test_cancelled_request_cannot_replace_current_ready_authority(self):
        self.seed()
        with closing(sqlite3.connect(self.restored)) as sql, sql: sql.execute("UPDATE leases SET state='expired'")
        self.repin()
        with self.assertRaisesRegex(FinancialRestoreError, 'restored_qualified_object_state_differs'): self.check()

    def test_weakened_assignment_retention_guard_is_rejected(self):
        self.seed()
        with closing(sqlite3.connect(self.restored)) as sql, sql: sql.execute('DROP TRIGGER object_work_request_retained')
        self.repin()
        with self.assertRaisesRegex(QualifiedObjectRestoreError, 'object_work_recovery_schema_mismatch'): self.check()

    def test_partial_namespace_is_not_treated_as_a_legacy_copy(self):
        with closing(sqlite3.connect(':memory:')) as sql:
            sql.execute('CREATE TABLE object_work_requests(id TEXT)')
            with self.assertRaisesRegex(QualifiedObjectRestoreError, 'schema_mismatch'): qualified_object_state(sql)

    def test_older_qualified_cutoff_cannot_ignore_prepared_request_history(self):
        self.seed(); value = json.loads(self.snapshot.read_bytes()); del value['qualifiedObjects']['assignmentPool']
        raw = encoded(value); self.snapshot.write_bytes(raw); self.snapshot_pin = digest(raw)
        with self.assertRaisesRegex(FinancialRestoreError, 'restored_qualified_object_state_differs'): self.check()
