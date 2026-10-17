"""Current Node cancellation authority revokes a real older Python/SQLite spool.

Native model inference is explicitly synthetic. Original backups are preserved.
"""
import copy
import json
import os
from pathlib import Path
import shutil
import sqlite3
import unittest
from community import object_audit_jobs as jobs
from community.search_snapshot import digest,encoded
from community.process_owner import run_owned
from community.tests import test_object_audit_jobs as fixtures
REPO=Path(__file__).resolve().parents[2]

class ObjectCancellationRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.h=fixtures.ObjectAuditJobTests();self.h.setUp();self.addCleanup(self.h.doCleanups)
        self.path=self.h.root/'assignment/current-cancellations.private.json'
        self.document={'version':2,'scope':'private-object-erasure-recovery-v2','resource':self.h.native.policy['resource'],
          'policySha256':self.h.native.verifier.policy_sha256,'registrySha256':digest(self.h.registry.read_bytes()),
          'deletionLedgerSha256':'9'*64,'cancellationLedgerSha256':'8'*64,'capturedAt':1000,'expiresAt':1600,
          'revocations':[],'cancellations':[{'leaseId':self.h.body['leaseId'],'assignmentSha256':self.h.body['assignmentSha256'],
            'requestId':'7'*64,'cancelledAt':950}]}
    def pin(self,document=None):
        raw=encoded(document if document is not None else self.document);self.path.write_bytes(raw);return digest(raw)
    def apply(self,document=None):
        return self.h.service.apply_recovery_authority(self.path,self.pin(document))
    def rows(self,table):
        with self.h.service.connect() as db:return [dict(row) for row in db.execute('SELECT * FROM '+table)]
    def test_prestart_cancellation_revokes_without_a_job_and_survives_newer_omission(self):
        result=self.apply();self.assertEqual(result['revokedAssignments'],1);self.assertFalse(result['cleanupComplete'])
        self.h.restart()
        with self.assertRaisesRegex(jobs.JobError,'object_assignment_revoked'):self.h.submit()
        self.assertEqual(self.rows('jobs'),[])
        self.h.now=1001;self.apply({**self.document,'capturedAt':1001,'expiresAt':1601,'cancellations':[]})
        self.assertEqual(len(self.rows('assignment_revocations')),1)
        with self.assertRaisesRegex(jobs.JobError,'older_than_applied'):self.apply()
    def test_account_deletion_and_cancellation_for_same_lease_have_one_tombstone_and_earliest_time(self):
        self.document['revocations']=[{'leaseId':self.h.body['leaseId'],'assignmentSha256':self.h.body['assignmentSha256'],'deletedAt':975}]
        result=self.apply();self.assertEqual(result['revokedAssignments'],1)
        self.assertEqual(self.rows('assignment_revocations')[0]['requested'],950)
        self.assertEqual(self.apply(),result);self.assertEqual(len(self.rows('recovery_authorities')),1)
    def test_last_statement_failure_rolls_back_cancellation_and_recovery_receipt(self):
        with self.h.service.connect() as db:db.execute("CREATE TRIGGER fail_v2 BEFORE INSERT ON recovery_authorities BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.apply()
        self.assertEqual(self.rows('assignment_revocations'),[]);self.assertEqual(self.rows('recovery_authorities'),[])
    def test_v2_envelope_and_cancellation_records_are_strict_before_any_tombstone(self):
        for alter in [lambda v:v.pop('cancellationLedgerSha256'),lambda v:v.update(cancellationLedgerSha256='bad'),
          lambda v:v.update(version=True),lambda v:v.update(scope='private-object-erasure-recovery-v1'),
          lambda v:v.update(cancellations=v['cancellations']*2),lambda v:v['cancellations'][0].update(cancelledAt=True),
          lambda v:v['cancellations'][0].update(cancelledAt=1001),lambda v:v['cancellations'][0].update(requestId='bad'),
          lambda v:v['cancellations'][0].update(assignmentSha256='f'*64),lambda v:v['cancellations'][0].update(extra='private'),
          lambda v:v['cancellations'][0].update(leaseId='f'*32),lambda v:v.update(expiresAt=1000)]:
            value=copy.deepcopy(self.document);alter(value)
            with self.assertRaises(ValueError):self.apply(value)
            self.assertEqual(self.rows('assignment_revocations'),[])
        self.apply()
        with self.assertRaisesRegex(jobs.JobError,'authority_conflict'):self.apply({**self.document,'cancellationLedgerSha256':'a'*64})
    def test_actual_node_current_ledger_revokes_approved_old_spool_before_serving_or_recomputing(self):
        node=os.environ.get('VISION_TEST_NODE')
        if not node or not Path(node).is_file():self.skipTest('existing private Node runtime required')
        first=self.h.submit();self.h.run_next();self.assertEqual(self.h.service.get(first['jobId'])['state'],'approved')
        self.h.service.close();backup=self.h.root/'old-approved-spool';shutil.copytree(self.h.work,backup)
        original=backup/('attempts-'+first['jobId'])/'attempt-1/audit-report.json';original_bytes=original.read_bytes()
        output=self.h.root/'current-authority';input_path=self.h.root/'cancel-recovery-input.private.json'
        input_path.write_bytes(encoded({'registry':str(self.h.registry),'policySha256':self.h.native.verifier.policy_sha256,
          'objectIndex':self.h.body['objectIndex'],'authority':{'leaseId':first['leaseId'],'profileId':self.h.body['profileId'],
            'policyId':self.h.body['policyId'],'assignmentSha256':self.h.body['assignmentSha256'],'sourceSha256':digest(self.h.native.source)},
          'items':self.h.native.trusted['records']}))
        stdout=self.h.root/'cancel-recovery.stdout.private.log';stderr=self.h.root/'cancel-recovery.stderr.private.log'
        with stdout.open('xb') as out,stderr.open('xb') as err:
            completed=run_owned([node,str(REPO/'deploy/cloudflare/tools/native-cancellation-recovery.fixture.mjs'),str(input_path),str(output)],
              cwd=REPO,env=dict(os.environ),stdout=out,stderr=err,timeout=45)
        evidence_root=os.environ.get('VISION_TEST_EVIDENCE_DIR')
        if evidence_root:
            evidence=Path(evidence_root);evidence.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(stdout,evidence/'node.stdout.private.log');shutil.copyfile(stderr,evidence/'node.stderr.private.log')
        self.assertEqual(completed.returncode,0,stderr.read_text(encoding='utf-8')[-10000:])
        exported=json.loads(stdout.read_bytes());self.assertEqual(exported['cancelledAssignments'],1)
        self.assertTrue(exported['oldHostedCopyRepairedBeforeNativeExport']);self.assertTrue(exported['sameAuthorityAsIndependentCurrent'])
        self.document=json.loads((output/'export/object-erasure-authority.private.json').read_bytes())
        self.assertEqual(self.document['revocations'],[]);self.assertEqual(len(self.document['cancellations']),1)
        self.h.now=1002;target=self.h.root/'restored-spool';shutil.copytree(backup,target);self.h.work=target
        self.h.service=jobs.ObjectAuditJobs(self.h.native.verifier,self.h.registry,digest(self.h.registry.read_bytes()),target,
          clock=lambda:self.h.now,recovery_authority=self.path,recovery_sha256=self.pin())
        # Constructor applies current revocation BEFORE recover()/HTTP startup.
        saved=self.h.service.get(first['jobId']);self.assertEqual(saved['state'],'erasing');self.assertIsNone(saved['receiptSha256'])
        calls=list(self.h.native.calls);self.assertTrue(self.h.run_next());self.assertEqual(self.h.native.calls,calls)
        self.assertEqual(self.h.service.get(first['jobId'])['state'],'erased')
        self.assertEqual(original.read_bytes(),original_bytes)
        self.assertFalse((target/first['jobId']).exists());self.assertFalse((target/('attempts-'+first['jobId'])).exists())
        self.h.restart()
        with self.assertRaisesRegex(jobs.JobError,'object_assignment_revoked'):self.h.submit()
        self.assertEqual(len(self.rows('jobs')),1);self.assertEqual(len(self.rows('attempts')),1)
        with sqlite3.connect(output/'current.sqlite') as db:
            self.assertEqual(db.execute('SELECT units,deleted_at FROM accounts').fetchone(),(10,None))
            self.assertEqual(db.execute('SELECT COUNT(*) FROM ledger').fetchone()[0],0)
        if evidence_root:
            result={'status':'NODE_PYTHON_CURRENT_CANCELLATION_RESTORE_PASSED','approvedBackupRevokedBeforeServing':True,
              'originalBackupReportSha256':digest(original_bytes),'originalBackupPreserved':True,'extraNativeAttempts':0,
              'assignmentRevocations':len(self.rows('assignment_revocations')),'savedAttempts':len(self.rows('attempts')),
              'completedErasures':sum(row['completed'] is not None for row in self.rows('erasures')),
              'oldHostedCopyRepairedBeforeNativeExport':True,'sameAuthorityAsIndependentCurrent':True,
              'oldHostedBackupSha256':exported['oldHostedBackupSha256'],'accountActive':True,'bankedUnits':10,'earnedCredits':0,'liveCalls':0,'syntheticInference':True,'nativeInferences':0}
            (Path(evidence_root)/'restore.private.json').write_bytes(encoded(result))

if __name__=='__main__':unittest.main()
