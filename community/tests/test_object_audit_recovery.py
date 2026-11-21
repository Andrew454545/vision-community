"""Actual closed-spool backup/recovery; native inference uses the explicit fixture."""
import copy
import json
import os
from pathlib import Path
import shutil
import sqlite3
import unittest

from community import object_audit_jobs as jobs
from community.search_snapshot import digest, encoded
from community.process_owner import run_owned
from community.tests import test_object_audit_jobs as fixtures


class ObjectAuditRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.h = fixtures.ObjectAuditJobTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.path = self.h.root / 'assignment/current-deletions.private.json'
        self.document = {'version': 1, 'scope': 'private-object-erasure-recovery-v1',
            'resource': self.h.native.policy['resource'], 'policySha256': self.h.native.verifier.policy_sha256,
            'registrySha256': digest(self.h.registry.read_bytes()), 'deletionLedgerSha256': '9' * 64,
            'capturedAt': 1000, 'expiresAt': 1600, 'revocations': [{
                'leaseId': self.h.body['leaseId'], 'assignmentSha256': self.h.body['assignmentSha256'], 'deletedAt': 950}]}

    def authority(self, document=None):
        raw = encoded(document if document is not None else self.document)
        self.path.write_bytes(raw)
        return digest(raw)

    def apply(self, document=None):
        return self.h.service.apply_recovery_authority(self.path, self.authority(document))

    def restore(self, backup):
        self.h.service.close()
        target = self.h.root / 'restored-spool'
        shutil.copytree(backup, target)
        self.h.work = target
        self.h.service = jobs.ObjectAuditJobs(self.h.native.verifier, self.h.registry,
            digest(self.h.registry.read_bytes()), target, clock=lambda: self.h.now,
            recovery_authority=self.path, recovery_sha256=self.authority())

    def count(self, table):
        with self.h.service.connect() as db:
            return db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]

    def test_old_approved_backup_is_revoked_before_any_receipt_can_be_served(self):
        first = self.h.submit()
        self.h.run_next()
        self.assertEqual(self.h.service.get(first['jobId'])['state'], 'approved')
        self.h.service.close()
        backup = self.h.root / 'old-backup'
        shutil.copytree(self.h.work, backup)
        old_report = backup / ('attempts-' + first['jobId']) / 'attempt-1/audit-report.json'
        original = old_report.read_bytes()
        self.h.service = self.h.open()
        self.h.service.erase_assignment(first['leaseId'])
        self.h.run_next()
        self.assertEqual(self.h.service.get(first['jobId'])['state'], 'erased')
        calls = list(self.h.native.calls)
        self.restore(backup)
        self.assertEqual(self.h.service.get(first['jobId'])['state'], 'erasing')
        self.assertIsNone(self.h.service.get(first['jobId'])['receiptSha256'])
        self.assertTrue(self.h.run_next())
        self.assertEqual(self.h.service.get(first['jobId'])['state'], 'erased')
        self.assertEqual(self.h.native.calls, calls)
        self.assertEqual(old_report.read_bytes(), original)
        self.assertFalse((self.h.work / first['jobId']).exists())
        self.assertFalse((self.h.work / ('attempts-' + first['jobId'])).exists())
        self.h.restart()
        with self.assertRaisesRegex(jobs.JobError, 'object_assignment_revoked'):
            self.h.submit()

    def test_prestart_revocation_survives_restart_without_creating_a_candidate(self):
        reply = self.apply()
        self.assertFalse(reply['cleanupComplete'])
        self.assertEqual(self.count('assignment_revocations'), 1)
        self.h.restart()
        with self.assertRaisesRegex(jobs.JobError, 'object_assignment_revoked'):
            self.h.submit()
        self.assertEqual(self.count('jobs'), 0)
        self.assertFalse(self.h.native.calls)

    def test_manifest_validation_precedes_all_tombstones_and_preserves_original(self):
        original = copy.deepcopy(self.document)
        self.document['revocations'].append({'leaseId': 'f' * 32, 'assignmentSha256': 'f' * 64, 'deletedAt': 950})
        raw = encoded(self.document)
        with self.assertRaisesRegex(ValueError, 'invalid_object_recovery_authority'):
            self.apply()
        self.assertEqual(self.path.read_bytes(), raw)
        self.assertEqual(self.count('assignment_revocations'), 0)
        self.assertEqual(self.count('recovery_authorities'), 0)
        self.document = original

    def test_last_statement_failure_rolls_back_every_revocation(self):
        with self.h.service.connect() as db:
            db.execute("CREATE TRIGGER fail_recovery BEFORE INSERT ON recovery_authorities BEGIN SELECT RAISE(ABORT,'fixture failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.apply()
        self.assertEqual(self.count('assignment_revocations'), 0)
        self.assertEqual(self.count('recovery_authorities'), 0)

    def test_newer_authority_cannot_remove_a_saved_revocation(self):
        self.apply()
        newer = {**self.document, 'capturedAt': 1001, 'expiresAt': 1601, 'revocations': []}
        self.h.now = 1001
        self.apply(newer)
        self.assertEqual(self.count('assignment_revocations'), 1)
        self.assertEqual(self.count('recovery_authorities'), 2)
        with self.assertRaisesRegex(jobs.JobError, 'older_than_applied'):
            self.apply()

    def test_same_capture_conflict_and_exact_replay_are_distinct(self):
        first = self.apply()
        self.assertEqual(self.apply(), first)
        self.assertEqual(self.count('recovery_authorities'), 1)
        with self.assertRaisesRegex(jobs.JobError, 'authority_conflict'):
            self.apply({**self.document, 'deletionLedgerSha256': '8' * 64})

    def test_stale_future_wrong_resource_and_mismatched_pins_are_refused(self):
        mutations = [
            {'expiresAt': 1000}, {'capturedAt': 1001}, {'expiresAt': 1601},
            {'resource': {}}, {'policySha256': 'f' * 64}, {'registrySha256': 'f' * 64},
            {'capturedAt': True}, {'version': True}, {'deletionLedgerSha256': 'untrusted'},
            {'revocations': [{**self.document['revocations'][0], 'assignmentSha256': 'f' * 64}]},
            {'revocations': self.document['revocations'] * 2},
        ]
        for change in mutations:
            with self.subTest(change=list(change)):
                with self.assertRaises(ValueError): self.apply({**self.document, **change})
                self.assertEqual(self.count('assignment_revocations'), 0)

    def test_reconciliation_is_refused_after_worker_start(self):
        self.h.service.start()
        with self.assertRaisesRegex(jobs.JobError, 'requires_offline_spool'):
            self.apply()

    def test_recovery_authority_and_pin_are_both_required(self):
        with self.assertRaisesRegex(jobs.JobError, 'object_recovery_authority_required'):
            jobs.ObjectAuditJobs(self.h.native.verifier, self.h.registry, digest(self.h.registry.read_bytes()),
                self.h.root / 'another-spool', recovery_authority=self.path)

    def test_failed_boot_authority_never_serves_a_restored_approval(self):
        first = self.h.submit()
        self.h.run_next()
        self.h.service.close()
        backup = self.h.root / 'invalid-authority-backup'
        shutil.copytree(self.h.work, backup)
        self.document['expiresAt'] = 1000
        with self.assertRaises(ValueError): self.restore(backup)
        # The constructor failed before recover()/HTTP startup; the closed
        # database still retains the original evidence, not a fabricated result.
        with sqlite3.connect(self.h.work / 'jobs.sqlite') as db:
            self.assertEqual(db.execute('SELECT state FROM jobs').fetchone()[0], 'approved')

    def test_current_database_export_revokes_a_real_restored_spool_across_node_and_python(self):
        node = os.environ.get('VISION_TEST_NODE')
        if not node or not Path(node).is_file():
            self.skipTest('existing private Node runtime required for cross-language recovery')
        first = self.h.submit()
        self.h.run_next()
        self.h.service.close()
        backup = self.h.root / 'pre-deletion-backup'
        shutil.copytree(self.h.work, backup)
        self.h.service = self.h.open()
        database = self.h.root / 'current-hosted-copy.sqlite'
        owner = 'a' * 32
        with sqlite3.connect(database) as db:
            db.executescript('''CREATE TABLE accounts(id TEXT,deleted_at INTEGER,units INTEGER,recovery_hash TEXT);
                CREATE TABLE account_deletion_receipts(account_id TEXT,request_key TEXT,deleted_at INTEGER,units_forfeited INTEGER);
                CREATE TABLE leases(id TEXT,account_id TEXT,lane TEXT);
                CREATE TABLE account_cleanup(artifact_key TEXT,account_id TEXT,state TEXT);''')
            db.execute('INSERT INTO accounts VALUES (?,950,0,NULL)', (owner,))
            db.execute('INSERT INTO account_deletion_receipts VALUES (?,?,950,4)', (owner, 'c' * 64))
            db.execute("INSERT INTO leases VALUES (?,?,'object')", (first['leaseId'], owner))
            db.execute("INSERT INTO account_cleanup VALUES (?,?,'erased')", ('object-audit-jobs/' + first['leaseId'], owner))
        tools = Path(__file__).resolve().parents[2] / 'deploy/cloudflare/tools'
        output = self.h.root / 'exported-authority.private.json'
        script = '''
          import {readFileSync,writeFileSync} from 'node:fs';
          import {createHash} from 'node:crypto';
          import {DatabaseSync} from 'node:sqlite';
          const [database,registry,policy,out]=process.argv.slice(1);
          const {exportDeletionLedger}=await import(RESTORE);
          const {prepareObjectErasureRecovery}=await import(ERASURE);
          const sql=new DatabaseSync(database,{readOnly:true});
          try {
            const registryRaw=readFileSync(registry);
            const deletionLedgerRaw=Buffer.from(JSON.stringify(exportDeletionLedger(sql,1000,'staging')));
            const sha=raw=>createHash('sha256').update(raw).digest('hex');
            const ledger=out+'.ledger.json';
            writeFileSync(ledger,deletionLedgerRaw,{flag:'wx'});
            const report=prepareObjectErasureRecovery({current:database,currentSha256:sha(readFileSync(database)),
              registry,registrySha256:sha(registryRaw),policySha256:policy,deletions:ledger,
              deletionsSha256:sha(deletionLedgerRaw),notBefore:1000,now:1000,environment:'staging',out:out+'.export'});
            const raw=readFileSync(out+'.export/object-erasure-authority.private.json');
            if(sha(raw)!==report.authoritySha256)throw Error('export pin mismatch');
            writeFileSync(out,raw,{flag:'wx'});
          } finally {sql.close();}
        '''.replace('RESTORE', json.dumps((tools / 'account-restore.mjs').as_uri())).replace(
            'ERASURE', json.dumps((tools / 'object-erasure-recovery.mjs').as_uri()))
        with (self.h.root / 'export.stdout').open('xb') as stdout, (self.h.root / 'export.stderr').open('xb') as stderr:
            result = run_owned([node, '--input-type=module', '-e', script, str(database), str(self.h.registry),
                self.h.native.verifier.policy_sha256, str(output)], env=dict(os.environ), cwd=self.h.root,
                stdout=stdout, stderr=stderr, timeout=30)
        self.assertEqual(result.returncode, 0)
        self.document = json.loads(output.read_bytes())
        self.assertEqual(len(self.document['revocations']), 1)
        self.restore(backup)
        self.assertEqual(self.h.service.get(first['jobId'])['state'], 'erasing')
        calls = list(self.h.native.calls)
        self.h.run_next()
        self.assertEqual(self.h.service.get(first['jobId'])['state'], 'erased')
        self.assertEqual(self.h.native.calls, calls)
        self.h.restart()
        with self.assertRaisesRegex(jobs.JobError, 'object_assignment_revoked'):
            self.h.submit()
