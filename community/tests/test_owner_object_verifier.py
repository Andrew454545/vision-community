"""Real local saved auditor and protection; explicitly synthetic native output."""
import copy
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import Mock, patch

from community.owner_object_verifier import OwnerObjectVerifier, MAX_RESPONSE
from community.object_audit_jobs import MAX_REQUEST
from community.search_snapshot import encoded
from community.tests import test_object_audit_jobs as fixture
from community.tests import test_protected_origin as origin_fixture
from community import protected_origin

ROOT=Path(__file__).resolve().parents[2]


class OwnerObjectVerifierTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixture.ObjectAuditJobTests('runTest');self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.guard=Mock()
        self.engine=OwnerObjectVerifier(self.fixture.service,guard=self.guard)
        self.raw=encoded(self.fixture.body)

    def submit(self):
        status,value=self.engine.handle('POST','/object-audits',self.raw)
        self.assertEqual(status,200,value)
        return value

    def work(self,runner=None):
        with patch.object(self.fixture.native.verifier,'run',side_effect=runner or self.fixture.native.fake_native):
            return self.engine.work_once()

    def test_construction_submission_and_status_never_open_a_socket_or_start_a_native_loop(self):
        with patch('socket.socket',side_effect=AssertionError('No socket permitted')), \
                patch.object(self.fixture.service,'start',side_effect=AssertionError('No background worker permitted')):
            job=self.submit()
            self.assertEqual(self.engine.handle('GET','/object-audits/'+job['jobId']),(200,job))
        self.assertIsNone(self.fixture.service.worker)
        self.assertEqual(self.fixture.native.calls,[])
        self.assertEqual(self.guard.call_count,4)

    def test_finite_local_work_retains_exact_audit_contract_without_publication_or_credit(self):
        job=self.submit()['jobId']
        self.assertEqual(self.work(),{'status':'worked'})
        status,value=self.engine.handle('GET','/object-audits/'+job)
        self.assertEqual(status,200)
        self.assertEqual((value['state'],value['attempts']),('approved',1))
        self.assertEqual((value['productionQualified'],value['serverAuthorization'],
                          value['acceptedContributions'],value['searchCreditsCreated']),(False,False,0,0))
        self.assertEqual(self.work(),{'status':'idle'})
        self.assertEqual(self.fixture.native.calls,['runtime-info','index-segment','verify-index','verify-index'])

    def test_submit_passes_original_bytes_and_restart_reuses_job_and_preserved_attempt(self):
        self.raw=json.dumps(self.fixture.body,ensure_ascii=False,indent=2).encode()+b'\n'
        with patch.object(self.fixture.service,'submit',wraps=self.fixture.service.submit) as submit:
            job=self.submit()['jobId'];submit.assert_called_once_with(self.raw)
        self.work();before=list(self.fixture.native.calls)
        report=self.fixture.attempt(job)/'audit-report.json';original=report.read_bytes()
        self.fixture.restart();self.engine=OwnerObjectVerifier(self.fixture.service,guard=self.guard)
        self.assertEqual(self.submit()['jobId'],job)
        self.assertEqual(self.work(),{'status':'idle'})
        self.assertEqual(self.fixture.native.calls,before)
        self.assertEqual(report.read_bytes(),original)

    def test_programs_paths_queries_authority_and_unknown_routes_are_refused(self):
        for path in ('https://elsewhere.invalid/object-audits','/object-audits?secret=x',
                     '/object-audits/../outside','/object-audits/'+'a'*32+'#x',
                     '/object-audits/'+'a'*32+'/run-native','C:/private/runtime.exe'):
            with self.subTest(path=path):
                self.assertEqual(self.engine.handle('POST',path,b'{}'),(404,{'error':'not_found'}))
        self.assertEqual(self.engine.handle('DELETE','/object-audits',b'{}')[0],404)
        original=copy.deepcopy(self.fixture.body)
        for field,value in (('binary','C:/caller.exe'),('policyId','caller'),('leaseId','f'*32),
                            ('profileId','f'*64),('assignmentSha256','f'*64)):
            self.raw=encoded({**original,field:value})
            with self.subTest(field=field):self.assertIn(self.engine.handle('POST','/object-audits',self.raw)[0],(400,403,409))
        self.assertEqual(self.fixture.native.calls,[])

    def test_malformed_oversized_duplicate_and_nonfinite_json_fail_before_staging(self):
        for raw in (None,'{}',b'',b'{"version":1,"version":1}',b'{"version":NaN}',
                    encoded({**self.fixture.body,'version':True}),b' '* (MAX_REQUEST+1)):
            with self.subTest(kind=type(raw).__name__):
                self.assertEqual(self.engine.handle('POST','/object-audits',raw),(400,{'error':'invalid_object_job'}))
        with self.fixture.service.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],0)

    def test_get_body_and_nonempty_control_or_overlarge_control_are_refused(self):
        job=self.submit()['jobId'];path='/object-audits/'+job
        for method,route,raw in (('GET',path,b'{}'),('POST',path+'/cancel',b'{"path":"PRIVATE"}'),
                                 ('POST',path+'/cancel',b' '*1025),('POST',path+'/erase',b'[]')):
            self.assertEqual(self.engine.handle(method,route,raw),(400,{'error':'invalid_object_job'}))
        self.assertEqual(self.fixture.service.get(job)['state'],'queued')

    def test_owner_retry_requires_once_only_nonce_and_old_replay_never_starts_another_attempt(self):
        job=self.submit()['jobId'];path='/object-audits/'+job+'/retry'
        failed=Mock(side_effect=ValueError('PRIVATE native failure'))
        self.work(failed);self.fixture.now+=120
        self.assertEqual(self.engine.handle('POST',path,b'{}'),(400,{'error':'invalid_object_job'}))
        intent=encoded({'requestId':'b'*64,'expectedAttempts':1})
        self.assertEqual(self.engine.handle('POST',path,intent)[1]['state'],'queued')
        self.work(failed);self.fixture.now+=120
        self.fixture.restart();self.engine=OwnerObjectVerifier(self.fixture.service,guard=self.guard)
        replay=self.engine.handle('POST',path,intent)
        self.assertEqual((replay[0],replay[1]['state'],replay[1]['attempts']),(200,'failed',2))
        self.assertEqual(self.work(),{'status':'idle'})
        with self.fixture.service.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM retry_intents').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0],2)

    def test_cancellation_during_native_work_wins_over_a_late_approval(self):
        job=self.submit()['jobId'];path='/object-audits/'+job
        def runner(command,folder,timeout):
            value=self.fixture.native.fake_native(command,folder,timeout)
            if command[1]=='index-segment':
                self.assertEqual(self.engine.handle('POST',path+'/cancel',b'{}')[1]['state'],'cancelled')
            return value
        self.assertEqual(self.work(runner),{'status':'worked'})
        self.assertEqual(self.engine.handle('GET',path)[1]['state'],'cancelled')
        self.assertEqual(self.submit()['state'],'cancelled')

    def test_assignment_erasure_before_start_persists_and_rejects_delayed_submission(self):
        lease=self.fixture.body['leaseId']
        status,value=self.engine.handle('POST','/object-assignments/'+lease+'/erase',b'{}')
        self.assertEqual((status,value['state']),(200,'erased'))
        self.fixture.restart();self.engine=OwnerObjectVerifier(self.fixture.service,guard=self.guard)
        self.assertEqual(self.engine.handle('POST','/object-audits',self.raw),(409,{'error':'object_assignment_revoked'}))
        self.assertEqual(self.fixture.native.calls,[])

    def test_pause_stop_prevent_guard_native_and_job_calls_without_clearing_markers(self):
        for marker,expected in (('PAUSE','paused'),('STOP','stopped')):
            path=self.fixture.work/marker;path.write_text('fixture-only hold')
            with patch.object(self.fixture.service,'submit',side_effect=AssertionError('No stage')):
                self.assertEqual(self.engine.handle('POST','/object-audits',self.raw),(503,{'error':'object_verifier_paused'}))
                self.assertEqual(self.engine.work_once(),{'status':expected})
            self.assertTrue(path.exists());path.unlink()
        self.guard.assert_not_called()

    def test_guard_revocation_after_staging_preserves_job_without_recomputation_or_disclosure(self):
        self.guard.side_effect=[None,ValueError('PRIVATE revoked activation')]
        self.assertEqual(self.engine.handle('POST','/object-audits',self.raw),(503,{'error':'object_verifier_unavailable'}))
        self.guard.side_effect=None
        self.assertEqual(self.submit()['state'],'queued')
        with self.fixture.service.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],1)
        self.assertEqual(self.fixture.native.calls,[])
        self.assertNotIn(b'PRIVATE',(self.fixture.work/'owner-object.failure.json').read_bytes())

    def test_unexpected_error_or_oversized_response_never_echoes_private_details_or_overwrites_failure(self):
        job=self.submit()['jobId'];path='/object-audits/'+job
        with patch.object(self.fixture.service,'get',side_effect=ValueError('PRIVATE paths and secrets')):
            self.assertEqual(self.engine.handle('GET',path),(503,{'error':'object_verifier_unavailable'}))
        report=self.fixture.work/'owner-object.failure.json';before=report.read_bytes()
        with patch.object(self.fixture.service,'get',return_value={'PRIVATE':'x'*(MAX_RESPONSE+1)}):
            self.assertEqual(self.engine.handle('GET',path),(503,{'error':'object_verifier_unavailable'}))
        self.assertEqual(report.read_bytes(),before)
        self.assertNotIn(b'PRIVATE',before)

    def test_already_running_background_worker_is_not_adopted_or_started_again(self):
        with patch.object(self.fixture.service,'worker',Mock()):
            with self.assertRaisesRegex(ValueError,'owner_object_configuration_required'):
                OwnerObjectVerifier(self.fixture.service,guard=self.guard)
            with patch.object(self.fixture.service,'run_next',side_effect=AssertionError('No competing native owner')):
                self.assertEqual(self.engine.work_once()['status'],'operator_required')

    def test_unexpected_echo_fields_changed_identity_or_financial_claims_are_not_transport_results(self):
        value=self.submit();path='/object-audits/'+value['jobId']
        for changes in ({'privatePath':'PRIVATE'},{'jobId':'f'*32},{'acceptedContributions':1},
                        {'searchCreditsCreated':False},{'productionQualified':True},
                        {'policyId':'C:/PRIVATE/runtime.exe'},{'version':True}):
            with self.subTest(changes=changes),patch.object(self.fixture.service,'get',return_value={**value,**changes}):
                self.assertEqual(self.engine.handle('GET',path),(503,{'error':'object_verifier_unavailable'}))

    def test_approval_without_live_origin_does_not_become_import_authority(self):
        job=self.submit()['jobId'];self.work()
        response=self.engine.handle('POST','/object-audits/'+job+'/settlement-evidence',b'{}')
        self.assertEqual(response,(503,{'error':'object_verifier_unavailable'}))
        self.assertEqual(self.fixture.service.get(job)['state'],'approved')


class OwnerObjectProtectionTests(unittest.TestCase):
    def setUp(self):
        self.fixture=origin_fixture.ProtectedOriginTests('runTest');self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.service,self.job,_=self.fixture.saved_job()
        self.engine=OwnerObjectVerifier(self.service,guard=lambda:None)
        self.path='/object-audits/'+self.job+'/settlement-evidence'

    def test_fresh_direct_evidence_passes_existing_js_contract_without_another_native_attempt(self):
        before=list(self.fixture.fixture.calls)
        status,value=self.engine.handle('POST',self.path,b'{}')
        self.assertEqual(status,200)
        self.assertEqual(value['expiresAt'],value['issuedAt']+30)
        self.assertEqual(self.fixture.fixture.calls,before)
        node=os.environ.get('VISION_TEST_NODE');self.assertTrue(node,'Use the existing private Node runtime')
        source=self.fixture.root/'interop.json';source.write_bytes(encoded(value))
        script="import{objectSettlementEvidence}from './deploy/cloudflare/native-object-verifier-bridge/worker.js';import{readFileSync}from'node:fs';const v=JSON.parse(readFileSync(process.argv[1],'utf8'));objectSettlementEvidence(v,{jobId:v.audit.jobId},v.issuedAt);console.log('DIRECT_OWNER_EVIDENCE_CONTRACT_PASSED_SYNTHETIC_ONLY');"
        child=subprocess.run([node,'--input-type=module','-e',script,str(source)],cwd=ROOT,capture_output=True,timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        evidence=os.environ.get('VISION_TEST_EVIDENCE_DIR')
        if evidence:
            folder=Path(evidence);folder.mkdir(exist_ok=True)
            (folder/'owner-object-interop.stdout.log').write_bytes(child.stdout)
            (folder/'owner-object-interop.stderr.log').write_bytes(child.stderr)
        self.assertEqual(child.returncode,0,child.stderr.decode(errors='replace'))
        self.assertIn(b'DIRECT_OWNER_EVIDENCE_CONTRACT_PASSED_SYNTHETIC_ONLY',child.stdout)

    def test_current_source_change_or_original_capture_expiry_cannot_reuse_saved_approval(self):
        report=self.fixture.root/'spool'/('attempts-'+self.job)/'attempt-1/audit-report.json'
        original=report.read_bytes()
        with patch.object(protected_origin.time,'time',return_value=protected_origin.time.time()+3602):
            self.assertEqual(self.engine.handle('POST',self.path,b'{}'),(503,{'error':'object_verifier_unavailable'}))
        (self.fixture.arrow/'0.arrow').write_bytes(b'fictional changed source')
        self.assertEqual(self.engine.handle('POST',self.path,b'{}'),(503,{'error':'object_verifier_unavailable'}))
        self.assertEqual(report.read_bytes(),original)
        with self.service.connect() as db:
            self.assertEqual(db.execute('SELECT state FROM jobs WHERE id=?',(self.job,)).fetchone()[0],'approved')


if __name__=='__main__':unittest.main()
