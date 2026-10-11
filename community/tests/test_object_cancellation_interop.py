"""Real loopback HTTP and native saved-job SQLite; inference is synthetic."""
import json
import os
from pathlib import Path
import shutil
import threading
import unittest
from unittest.mock import patch
from community.object_audit_jobs import make_server
from community.process_owner import run_owned
from community.search_snapshot import digest,encoded
from community.tests import test_object_audit_jobs as fixtures
REPO=Path(__file__).resolve().parents[2]

class ObjectCancellationInteropTests(unittest.TestCase):
    def test_cancel_running_assignment_after_lost_start_reply_without_deleting_account(self):
        node=os.environ.get('VISION_TEST_NODE') or shutil.which('node')
        if not node:self.skipTest('existing private Node runtime not supplied')
        f=fixtures.ObjectAuditJobTests();f.setUp();self.addCleanup(f.doCleanups)
        service=f.service;entered=threading.Event();revoked=threading.Event()
        original_submit=service.submit;original_erase=service.erase_assignment
        def submit_while_running(raw):
            result=original_submit(raw)
            if not entered.wait(8):raise RuntimeError('synthetic native work did not start')
            return result
        def erase_then_release(lease):
            result=original_erase(lease);revoked.set();return result
        def runner(command,folder,timeout):
            if command[1]=='index-segment':
                entered.set()
                if not revoked.wait(8):raise RuntimeError('synthetic assignment was not revoked')
            return f.native.fake_native(command,folder,timeout)
        service.submit=submit_while_running;service.erase_assignment=erase_then_release
        secret='synthetic-private-object-cancellation-secret'
        server=make_server(service,secret);self.addCleanup(server.server_close)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(thread.join,5);self.addCleanup(server.shutdown)
        payload=f.root/'cancel-input.private.json'
        payload.write_bytes(encoded({'secret':secret,'origin':f'http://127.0.0.1:{server.server_port}',
            'objectIndex':f.body['objectIndex'],'authority':{'leaseId':f.body['leaseId'],'profileId':f.body['profileId'],
                'policyId':f.body['policyId'],'assignmentSha256':f.body['assignmentSha256'],'sourceSha256':digest(f.native.source)},
            'items':f.native.trusted['records']}))
        stdout=f.root/'cancel-node.stdout.private.log';stderr=f.root/'cancel-node.stderr.private.log'
        with patch.object(f.native.verifier,'run',side_effect=runner):
            service.start()
            try:
                with stdout.open('wb') as out,stderr.open('wb') as err:
                    completed=run_owned([node,str(REPO/'deploy/cloudflare/tools/object-cancellation-interop.mjs'),str(payload)],
                        cwd=REPO,env=dict(os.environ),stdout=out,stderr=err,timeout=45)
            finally:revoked.set();service.close()
        with service.connect() as db:
            saved=[dict(row) for row in db.execute('SELECT * FROM jobs')]
            revocations=[dict(row) for row in db.execute('SELECT * FROM assignment_revocations')]
            erasures=[dict(row) for row in db.execute('SELECT * FROM erasures')]
            attempts=[dict(row) for row in db.execute('SELECT * FROM attempts ORDER BY number')]
        if os.environ.get('VISION_TEST_EVIDENCE_DIR'):
            evidence=Path(os.environ['VISION_TEST_EVIDENCE_DIR'])/'cancellation';evidence.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(stdout,evidence/'node.stdout.private.log');shutil.copyfile(stderr,evidence/'node.stderr.private.log')
            (evidence/'native-jobs.private.json').write_bytes(encoded({'jobs':saved,'revocations':revocations,'erasures':erasures,
                'attempts':attempts,'syntheticNativeCalls':f.native.calls,'runningBeforeStartReply':entered.is_set()}))
        self.assertEqual(completed.returncode,0,stderr.read_text(encoding='utf-8')[-10000:])
        result=json.loads(stdout.read_text(encoding='utf-8'));self.assertEqual(result['status'],'NODE_PYTHON_OBJECT_CANCELLATION_INTEROP_PASSED')
        self.assertEqual((result['starts'],len(saved),len(attempts)),(1,1,1))
        self.assertTrue(entered.is_set());self.assertTrue(revoked.is_set())
        self.assertEqual((saved[0]['state'],saved[0]['attempts'],saved[0]['receipt']),('erased',1,None))
        self.assertEqual(len(revocations),1);self.assertEqual(len(erasures),1)
        self.assertIsNotNone(erasures[0]['completed'])
        self.assertFalse((f.work/saved[0]['id']).exists());self.assertFalse((f.work/('attempts-'+saved[0]['id'])).exists())

if __name__=='__main__':unittest.main()
