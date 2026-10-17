"""Actual Worker protocol/native SQLite recovery; inference explicitly synthetic."""
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

class ObjectRecoveryInteropTests(unittest.TestCase):
    def test_lost_retry_acknowledgement_preserves_one_new_native_attempt(self):
        node=os.environ.get('VISION_TEST_NODE') or shutil.which('node')
        if not node:self.skipTest('existing private Node runtime not supplied')
        f=fixtures.ObjectAuditJobTests();f.setUp();self.addCleanup(f.doCleanups)
        service=f.service
        # Advance only the explicit fixture clock after a failed attempt. The
        # production retry delay is unchanged; this avoids a 60-second sleep.
        original_get=service.get
        def get_and_advance(job):
            value=original_get(job)
            if value['state']=='failed':f.now=max(f.now,value['retryAt'])
            return value
        service.get=get_and_advance
        first=True
        def runner(command,folder,timeout):
            nonlocal first
            if command[1]=='index-segment' and first:
                first=False;f.native.calls.append('index-segment')
                raise RuntimeError('synthetic first native attempt failed')
            return f.native.fake_native(command,folder,timeout)
        secret='synthetic-private-object-recovery-secret'
        server=make_server(service,secret);self.addCleanup(server.server_close)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(thread.join,5);self.addCleanup(server.shutdown)
        payload=f.root/'recovery-input.private.json'
        payload.write_bytes(encoded({'secret':secret,'origin':f'http://127.0.0.1:{server.server_port}',
            'objectIndex':f.body['objectIndex'],'authority':{'leaseId':f.body['leaseId'],'profileId':f.body['profileId'],
                'policyId':f.body['policyId'],'assignmentSha256':f.body['assignmentSha256'],'sourceSha256':digest(f.native.source)},
            'items':f.native.trusted['records']}))
        stdout=f.root/'recovery-node.stdout.private.log';stderr=f.root/'recovery-node.stderr.private.log'
        with patch.object(f.native.verifier,'run',side_effect=runner):
            service.start()
            try:
                with stdout.open('wb') as out,stderr.open('wb') as err:
                    completed=run_owned([node,str(REPO/'deploy/cloudflare/tools/object-recovery-interop.mjs'),str(payload)],
                        cwd=REPO,env=dict(os.environ),stdout=out,stderr=err,timeout=45)
            finally:service.close()
        with service.connect() as db:
            saved=[dict(row) for row in db.execute('SELECT * FROM jobs')]
            intents=[dict(row) for row in db.execute('SELECT * FROM retry_intents')]
            attempts=[dict(row) for row in db.execute('SELECT * FROM attempts ORDER BY number')]
        if os.environ.get('VISION_TEST_EVIDENCE_DIR'):
            evidence=Path(os.environ['VISION_TEST_EVIDENCE_DIR'])/'recovery';evidence.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(stdout,evidence/'node.stdout.private.log');shutil.copyfile(stderr,evidence/'node.stderr.private.log')
            (evidence/'native-jobs.private.json').write_bytes(encoded({'jobs':saved,'intents':intents,'attempts':attempts,
                'syntheticNativeCalls':f.native.calls,'fixtureRetryClockAdvanced':True}))
        self.assertEqual(completed.returncode,0,stderr.read_text(encoding='utf-8')[-10000:])
        result=json.loads(stdout.read_text(encoding='utf-8'));self.assertEqual(result['status'],'NODE_PYTHON_OBJECT_RECOVERY_INTEROP_PASSED')
        self.assertEqual(result['retryPosts'],2);self.assertEqual(len(intents),1)
        self.assertEqual([(row['state'],row['number']) for row in attempts],[('failed',1),('approved',2)])
        self.assertEqual((saved[0]['state'],saved[0]['attempts']),('erased',2))
        self.assertEqual(f.native.calls,['runtime-info','index-segment','runtime-info','index-segment','verify-index','verify-index'])

if __name__=='__main__':unittest.main()
