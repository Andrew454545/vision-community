"""Offline transport/outbox tests. Native results and OS vault calls are fictional."""
import base64
import copy
import ctypes
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from community import owner_object_agent as agent
from community import owner_object_credentials as vault
from community import owner_search_credentials as search_vault
from community.owner_search_agent import OwnerSearchError, _exclusive
from community.owner_search_supervisor import OwnerSearchSupervisor, OwnerSupervisorError
from community.search_snapshot import CONFIRMED_STAGING_RESOURCE, digest, encoded

NOW=2_000_000_000
BINDING={'version':1,'scope':'object-batch-parity-v1','policyId':'staging.synthetic',
    'policySha256':'5'*64,'runtimeProfileSha256':'6'*64,'qualityImplementationIdentity':'1'*64,
    'protectedAuthoritySha256':'2'*64,'protectedOriginHandoffSha256':'7'*64,
    'profiles':['1'*64],'resource':CONFIRMED_STAGING_RESOURCE}
INDEX={'manifest':{},'sourceTsv':base64.b64encode(b'fictional source').decode(),'files':{}}


def job():
    return {'version':1,'leaseId':'a'*32,'claimToken':'b'*32,'claimUntil':NOW+1200,'binding':copy.deepcopy(BINDING),
        'profileId':'1'*64,'assignmentSha256':'2'*64,'sourceSha256':digest(b'fictional source'),
        'submissionSha256':digest(encoded(INDEX).rstrip(b'\n')),'payloadBytes':len(encoded(INDEX))-1,'locations':2,
        'jobId':None,'candidateManifestSha256':None,'nativeAttempts':0}


def audit(state='approved'):
    return {'version':1,'jobId':'c'*32,'leaseId':'a'*32,'profileId':'1'*64,'policyId':BINDING['policyId'],
        'assignmentSha256':'2'*64,'submissionSha256':job()['submissionSha256'],'candidateManifestSha256':'3'*64,
        'state':state,'decision':state if state in {'approved','rejected'} else 'pending',
        'attempts':1,'retryAt':0,'receiptSha256':'4'*64 if state in {'approved','rejected'} else None,
        'serverAuthorization':False,'productionQualified':False,'acceptedContributions':0,'searchCreditsCreated':0}


class Coordinator:
    def __init__(self):
        self.job=job();self.calls=[];self.error=None;self.reply=None
        self.candidate=encoded({'version':1,**{k:self.job[k] for k in ('leaseId','profileId','assignmentSha256','submissionSha256')},
            'policyId':BINDING['policyId'],'objectIndex':INDEX})
    def post(self,action,value):
        self.calls.append((action,copy.deepcopy(value)))
        if action=='claim':return {'job':copy.deepcopy(self.job)} if self.job else {'job':None,'retryAfterSeconds':30}
        if action=='candidate':return self.candidate
        if self.error:raise self.error
        if self.reply is not None:return copy.deepcopy(self.reply)
        if action=='fail':return {'failed':True,'charged':False,'retryAt':NOW+900,'needsAttention':False}
        return {'completed':True,'submissionId':'a'*32,'accepted':2,'unitsEarned':20,'pendingAudit':False}


class Engine:
    def __init__(self):self.calls=[];self.state='approved';self.now=NOW;self.failure=None;self.hook=None
    def handle(self,method,path,raw=None):
        self.calls.append((method,path,raw))
        if self.failure:return self.failure
        value=audit(self.state)
        if path.endswith('/settlement-evidence'):
            return 200,{'audit':value,**{k:BINDING[k] for k in BINDING_KEYS},
                'qualificationScope':'batch-only','issuedAt':self.now,'expiresAt':self.now+30}
        return 200,value
    def work_once(self):
        self.calls.append(('WORK',None,None));self.state='approved'
        if self.hook:self.hook()
        return {'status':'worked'}


BINDING_KEYS=('policySha256','runtimeProfileSha256','qualityImplementationIdentity','protectedAuthoritySha256',
    'protectedOriginHandoffSha256','resource')


class OwnerObjectAgentTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup);self.root=Path(folder.name).resolve()
        self.coordinator=Coordinator();self.engine=Engine();self.now=NOW;self.guard=MagicMock()
    def agent(self):
        return agent.OwnerObjectAuditAgent(self.coordinator,self.engine,self.root,BINDING,guard=self.guard,clock=lambda:self.now)
    def pending(self):
        self.coordinator.error=OwnerSearchError('coordinator_unavailable',503)
        with self.assertRaisesRegex(OwnerSearchError,'coordinator_unavailable'):self.agent().run_once()
        return (self.root/'object-outbox.json').read_bytes()

    def test_full_candidate_is_digest_bound_before_native_and_only_current_proof_is_sent(self):
        self.assertEqual(self.agent().run_once(),{'status':'completed','accepted':2,'unitsEarned':20})
        self.assertEqual([x[0] for x in self.coordinator.calls],['claim','candidate','complete'])
        self.assertEqual(self.engine.calls[0],('POST','/object-audits',self.coordinator.candidate))
        self.assertEqual(self.coordinator.calls[-1][1]['evidence']['issuedAt'],NOW)
        self.assertFalse((self.root/'object-outbox.json').exists())

    def test_lost_reply_restart_replays_exact_completion_before_any_native_or_claim(self):
        saved=self.pending();calls=len(self.engine.calls)
        self.coordinator.error=None;self.engine.handle=MagicMock(side_effect=AssertionError('no native access'))
        self.assertEqual(self.agent().run_once()['status'],'completed')
        self.assertEqual(self.coordinator.calls[-1],('complete',json.loads(saved)['body']))
        self.assertEqual(len(self.engine.calls),calls);self.engine.handle.assert_not_called()

    def test_explicit_expired_proof_refresh_preserves_old_completion_and_native_identity(self):
        saved=self.pending();self.now+=31;self.engine.now=self.now
        original=self.coordinator.post
        def post(action,value):
            if action=='complete' and value['evidence']['expiresAt']<=self.now:
                raise OwnerSearchError('object_evidence_refresh_required',409)
            self.coordinator.error=None;return original(action,value)
        self.coordinator.post=post
        self.assertEqual(self.agent().run_once()['status'],'completed')
        self.assertEqual((self.root/'object-outbox-before-refresh.private.json').read_bytes(),saved)
        body=self.coordinator.calls[-1][1]
        self.assertEqual(body['audit'],json.loads(saved)['body']['audit'])
        self.assertEqual(body['evidence']['issuedAt'],self.now)
        self.assertEqual([x[0] for x in self.engine.calls],['POST','POST','POST'])

    def test_refresh_requires_real_proof_and_keeps_old_outbox_on_changed_source(self):
        saved=self.pending();self.coordinator.error=OwnerSearchError('object_evidence_refresh_required',409)
        self.engine.failure=(503,{'error':'object_verifier_unavailable'})
        with self.assertRaisesRegex(OwnerSearchError,'owner_object_verification_unavailable'):self.agent().run_once()
        self.assertEqual((self.root/'object-outbox.json').read_bytes(),saved)
        self.assertFalse((self.root/'object-outbox-before-refresh.private.json').exists())

    def test_refresh_atomic_rename_crash_promotes_saved_new_proof_without_recomputation(self):
        saved=self.pending();self.now+=31;self.engine.now=self.now
        self.coordinator.error=OwnerSearchError('object_evidence_refresh_required',409)
        with patch.object(agent.os,'replace',side_effect=OSError('private disk')):
            with self.assertRaises(OSError):self.agent().run_once()
        self.assertEqual((self.root/'object-outbox.json').read_bytes(),saved)
        pending=(self.root/'object-outbox.pending').read_bytes();calls=len(self.engine.calls)
        self.coordinator.error=None
        self.assertEqual(self.agent().run_once()['status'],'completed')
        self.assertEqual(self.coordinator.calls[-1][1],json.loads(pending)['body'])
        self.assertEqual(len(self.engine.calls),calls)

    def test_outage_auth_quota_and_ambiguous_ack_retain_original_exact_outbox(self):
        saved=self.pending();calls=len(self.engine.calls)
        for status in (401,403,429,503):
            self.coordinator.error=OwnerSearchError('coordinator_unavailable',status)
            with self.assertRaises(OwnerSearchError):self.agent().run_once()
            self.assertEqual((self.root/'object-outbox.json').read_bytes(),saved)
        self.coordinator.error=None
        for reply in ({'completed':True},{'completed':True,'private':'SECRET'},
            {'completed':True,'submissionId':'a'*32,'accepted':True,'unitsEarned':10,'pendingAudit':False}):
            self.coordinator.reply=reply
            with self.assertRaisesRegex(OwnerSearchError,'invalid_owner_reply'):self.agent().run_once()
            self.assertEqual((self.root/'object-outbox.json').read_bytes(),saved)
        self.assertEqual(len(self.engine.calls),calls)

    def test_claim_lost_discards_only_delivery_not_native_saved_work(self):
        self.pending();self.coordinator.error=OwnerSearchError('object_claim_lost',409)
        self.assertEqual(self.agent().run_once(),{'status':'claim_lost'})
        self.assertFalse((self.root/'object-outbox.json').exists());self.assertEqual(len(self.engine.calls),2)

    def test_claim_lost_after_fresh_proof_also_stops_without_new_submission(self):
        saved=self.pending();self.now+=31;self.engine.now=self.now;calls=0
        def post(*_):
            nonlocal calls
            calls+=1;raise OwnerSearchError('object_evidence_refresh_required' if calls==1 else 'object_claim_lost',409)
        self.coordinator.post=post
        self.assertEqual(self.agent().run_once(),{'status':'claim_lost'})
        self.assertEqual((self.root/'object-outbox-before-refresh.private.json').read_bytes(),saved)

    def test_candidate_mismatch_is_not_native_work_or_private_echo(self):
        for raw in (self.coordinator.candidate.replace(base64.b64encode(b'fictional source'),base64.b64encode(b'changed source')),
            self.coordinator.candidate.replace(b'"version":1',b'"version":1,"version":1',1),
            b'{"secret":"PRIVATE"}',b'NaN'):
            self.coordinator.candidate=raw
            self.assertEqual(self.agent().run_once()['status'],'failed')
            self.assertEqual(self.coordinator.calls[-1][0],'fail')
        self.assertFalse(self.engine.calls)
        self.assertEqual(json.loads((self.root/'failure-owner_object_failed.json').read_bytes()),
                         {'success':False,'error':'owner_object_failed'})

    def test_malformed_claim_binding_cannot_reach_candidate_or_native(self):
        for changes in ({'claimUntil':NOW},{'payloadBytes':True},{'extra':'PRIVATE'},
            {'nativeAttempts':4},{'jobId':'c'*32},{'binding':{**BINDING,'version':True}},
            {'binding':{**BINDING,'policySha256':'0'*64}}):
            self.coordinator.job={**job(),**changes}
            with self.assertRaises(OwnerSearchError):self.agent().run_once()
        self.assertFalse(self.engine.calls);self.assertTrue(all(x[0]=='claim' for x in self.coordinator.calls))

    def test_saved_job_is_read_without_fetch_or_automatic_retry_even_when_failed(self):
        self.coordinator.job.update(jobId='c'*32,candidateManifestSha256='3'*64,nativeAttempts=1)
        self.engine.state='failed'
        self.assertEqual(self.agent().run_once()['status'],'completed')
        self.assertEqual([x[0] for x in self.coordinator.calls],['claim','complete'])
        self.assertEqual(self.engine.calls,[('GET','/object-audits/'+'c'*32,None)])
        self.assertIsNone(self.coordinator.calls[-1][1]['evidence'])

    def test_queued_work_is_one_finite_step_and_pause_during_work_preserves_job(self):
        self.engine.state='queued';self.engine.hook=lambda:(self.root/'PAUSE').touch()
        self.assertEqual(self.agent().run_once(),{'status':'paused'})
        self.assertEqual([x[0] for x in self.coordinator.calls],['claim','candidate'])
        self.assertEqual([x[0] for x in self.engine.calls],['POST','WORK'])
        self.assertFalse((self.root/'failure-owner_object_failed.json').exists())
        self.assertFalse((self.root/'object-outbox.json').exists())

    def test_healthy_capacity_wait_has_no_failure_report_and_durable_fifteen_minute_pacing(self):
        self.engine.failure=(503,{'error':'object_job_queue_full'})
        owner=self.agent();supervisor=OwnerSearchSupervisor(owner,wall_clock=lambda:self.now,jitter=lambda:0,
            native_failure='native_verification_failed')
        self.assertEqual(supervisor.step(),{'status':'idle','waitSeconds':900})
        self.assertEqual(supervisor.step(),{'status':'deferred','waitSeconds':900})
        self.assertFalse((self.root/'failure-owner_object_failed.json').exists())
        self.assertFalse((self.root/'supervisor.failure.json').exists())

    def test_unavailable_verification_is_distinct_from_search_and_supervisor_preserves_hint(self):
        self.engine.failure=(503,{'error':'object_verifier_unavailable'})
        supervisor=OwnerSearchSupervisor(self.agent(),wall_clock=lambda:self.now,jitter=lambda:0,
            native_failure='native_verification_failed')
        self.assertEqual(supervisor.step(),{'status':'retry_wait','error':'native_verification_failed','waitSeconds':900})
        self.assertEqual(json.loads((self.root/'supervisor.json').read_bytes())['lastError'],'native_verification_failed')

    def test_pause_stop_and_competing_writer_never_touch_coordinator_native_or_guard(self):
        owner=self.agent()
        for marker in ('PAUSE','STOP'):
            path=self.root/marker;path.touch();self.assertEqual(owner.run_once(),{'status':'paused'});path.unlink()
        with _exclusive(self.root):
            with self.assertRaisesRegex(OwnerSearchError,'owner_agent_busy'):owner.run_once()
        self.assertFalse(self.engine.calls);self.assertFalse(self.coordinator.calls);self.guard.assert_not_called()

    def test_complete_pending_recovers_and_incomplete_pending_bytes_are_preserved(self):
        saved=self.pending();(self.root/'object-outbox.json').replace(self.root/'object-outbox.pending')
        self.coordinator.error=None
        self.assertEqual(self.agent().run_once()['status'],'completed')
        self.assertEqual(self.coordinator.calls[-1][1],json.loads(saved)['body'])
        self.coordinator.job=None;partial=b'{"action":';(self.root/'object-outbox.pending').write_bytes(partial)
        self.assertEqual(self.agent().run_once()['status'],'idle')
        self.assertEqual((self.root/'object-outbox-incomplete.private').read_bytes(),partial)
        (self.root/'object-outbox.pending').write_bytes(b'other incomplete')
        with self.assertRaisesRegex(OwnerSearchError,'invalid_owner_outbox'):self.agent().run_once()
        self.assertEqual((self.root/'object-outbox-incomplete.private').read_bytes(),partial)
        self.assertEqual((self.root/'object-outbox.pending').read_bytes(),b'other incomplete')

    def test_outbox_private_echo_and_unrelated_pending_are_preserved_never_delivered(self):
        saved=self.pending();doc=json.loads(saved);doc['body']['audit']['secret']='PRIVATE'
        (self.root/'object-outbox.json').write_bytes(encoded(doc));before=len(self.coordinator.calls)
        with self.assertRaisesRegex(OwnerSearchError,'invalid_owner_outbox'):self.agent().run_once()
        self.assertEqual(len(self.coordinator.calls),before)
        (self.root/'object-outbox.json').write_bytes(saved)
        doc=json.loads(saved);doc['body']['claimToken']='d'*32
        (self.root/'object-outbox.pending').write_bytes(encoded(doc))
        with self.assertRaisesRegex(OwnerSearchError,'invalid_owner_outbox'):self.agent().run_once()
        self.assertEqual((self.root/'object-outbox.json').read_bytes(),saved)

    def test_private_state_cannot_overlap_source_or_native_spool(self):
        source=Path(agent.__file__).resolve().parents[1]
        with self.assertRaisesRegex(OwnerSearchError,'owner_object_private_state_required'):
            agent.OwnerObjectAuditAgent(self.coordinator,self.engine,source,BINDING,guard=self.guard)
        self.engine.jobs=SimpleNamespace(work=self.root)
        with self.assertRaisesRegex(OwnerSearchError,'owner_object_private_state_required'):self.agent()


class ObjectTransportTests(unittest.TestCase):
    def test_permanent_protocol_or_policy_mismatch_requests_operator_repair_not_endless_retry(self):
        client=agent.HTTPSObjectCoordinator('https://fixture.invalid','f'*64)
        with patch.object(agent.http.client,'HTTPSConnection') as factory:
            response=factory.return_value.getresponse.return_value
            for status in (400,404,405,409,413,422):
                response.status=status;response.read.return_value=b'{"error":"PRIVATE upstream"}'
                with self.assertRaisesRegex(OwnerSearchError,'^owner_protocol_configuration_required$'):
                    client.post('complete',{})
            response.status=409;response.read.return_value=b'{"error":"object_settlement_policy_mismatch"}'
            with self.assertRaisesRegex(OwnerSearchError,'^owner_binding_configuration_required$'):
                client.post('complete',{})

    def test_https_fixed_origin_route_and_bounded_raw_candidate_without_redirects(self):
        client=agent.HTTPSObjectCoordinator('https://fixture.invalid/', 'f'*64)
        with patch.object(agent.http.client,'HTTPSConnection') as factory:
            connection=factory.return_value;response=connection.getresponse.return_value
            raw=b'{ "objectIndex" : { "a":1 } }';response.status=200;response.read.return_value=raw
            self.assertEqual(client.post('candidate',{}),raw)
            connection.request.assert_called_once_with('POST','/api/object-audit-agent/candidate',body=b'{}\n',
                headers={'Authorization':'Bearer '+'f'*64,'Content-Type':'application/json','Accept':'application/json'})
            response.read.assert_called_once_with(agent.MAX_REQUEST+1);connection.close.assert_called_once()
        for invalid in ('http://fixture.invalid','https://fixture.invalid/private','https://a:b@fixture.invalid'):
            with self.assertRaises(ValueError):agent.HTTPSObjectCoordinator(invalid,'f'*64)
        with patch.object(agent.http.client,'HTTPSConnection') as factory:
            with self.assertRaisesRegex(OwnerSearchError,'invalid_owner_route'):client.post('../other',{})
            with self.assertRaisesRegex(OwnerSearchError,'owner_payload_limit'):client.post('complete',{'x':'a'*agent.MAX_OUTBOX})
            factory.assert_not_called()

    def test_transport_error_codes_are_fixed_and_all_statuses_and_limits_close_connection(self):
        client=agent.HTTPSObjectCoordinator('https://fixture.invalid','f'*64)
        with patch.object(agent.http.client,'HTTPSConnection') as factory:
            response=factory.return_value.getresponse.return_value
            for status,upstream,code in ((302,'PRIVATE','coordinator_unavailable'),(401,'PRIVATE','coordinator_unavailable'),
                (429,'PRIVATE','coordinator_unavailable'),(409,'owner_object_claim_lost','object_claim_lost'),
                (409,'owner_object_evidence_refresh_required','object_evidence_refresh_required'),
                (409,'owner_object_binding_changed','owner_binding_configuration_required')):
                response.status=status;response.read.return_value=encoded({'error':upstream,'secret':'PRIVATE'})
                with self.assertRaisesRegex(OwnerSearchError,'^'+code+'$') as failure:client.post('complete',{})
                self.assertEqual(failure.exception.status,status)
            response.status=200;response.read.return_value=b'x'*8193
            with self.assertRaisesRegex(OwnerSearchError,'owner_reply_limit'):client.post('claim',{})
            response.read.return_value=b'{"a":1,"a":2}'
            with self.assertRaisesRegex(OwnerSearchError,'coordinator_unavailable'):client.post('claim',{})
            self.assertEqual(factory.call_count,8);self.assertEqual(factory.return_value.close.call_count,8)


class ObjectCredentialTests(unittest.TestCase):
    def test_credential_scope_is_distinct_and_never_falls_back_to_search(self):
        origin='https://coordinator.example'
        self.assertNotEqual(vault.credential_target(origin),search_vault.credential_target(origin))
        self.assertEqual(vault.credential_target(origin),vault.credential_target('https://COORDINATOR.example:443/'))
        for platform,helper in (('win32','_windows_read'),('darwin','_mac_read')):
            with patch.object(search_vault.sys,'platform',platform),patch.object(search_vault,helper,return_value='a'*64) as read:
                self.assertEqual(vault.read_owner_object_secret(origin),'a'*64)
                read.assert_called_once_with(vault.credential_target(origin),account=vault.ACCOUNT)
            with patch.object(search_vault.sys,'platform',platform),patch.object(search_vault,helper,side_effect=OSError('PRIVATE')) as read:
                with self.assertRaisesRegex(search_vault.OwnerCredentialError,'owner_credentials_unavailable'):
                    vault.read_owner_object_secret(origin)
                self.assertEqual(read.call_count,1)
        with patch.object(search_vault,'_windows_read') as read:
            with self.assertRaises(ValueError):vault.read_owner_object_secret('http://invalid')
            read.assert_not_called()

    def test_windows_requires_exact_dedicated_account_and_frees_native_memory(self):
        origin='https://coordinator.example';raw=b'a'*64;blob=(ctypes.c_ubyte*64).from_buffer_copy(raw)
        item=search_vault._Credential(Type=1,TargetName=vault.credential_target(origin),UserName=vault.ACCOUNT,
            CredentialBlobSize=64,CredentialBlob=blob,Persist=2)
        def read(target,kind,flags,out):
            self.assertEqual(target,vault.credential_target(origin))
            ctypes.cast(out,ctypes.POINTER(ctypes.POINTER(search_vault._Credential)))[0]=ctypes.pointer(item)
            return 1
        api=SimpleNamespace(CredReadW=MagicMock(side_effect=read),CredFree=MagicMock())
        with patch.object(search_vault.sys,'platform','win32'),patch.object(search_vault.ctypes,'WinDLL',return_value=api,create=True):
            self.assertEqual(vault.read_owner_object_secret(origin),'a'*64)
            item.UserName=search_vault.ACCOUNT
            with self.assertRaises(search_vault.OwnerCredentialError):vault.read_owner_object_secret(origin)
        self.assertEqual(api.CredFree.call_count,2)

    def test_mac_uses_only_dedicated_account_and_login_item_no_secret_arguments(self):
        process=SimpleNamespace(stdout=io.BytesIO(b'a'*64+b'\n'),wait=MagicMock(return_value=0),poll=MagicMock(return_value=0))
        with patch.object(search_vault.sys,'platform','darwin'),patch.object(search_vault.subprocess,'Popen',return_value=process) as popen,\
                patch.object(search_vault.threading,'Timer'):
            self.assertEqual(vault.read_owner_object_secret('https://coordinator.example'),'a'*64)
            args=popen.call_args.args[0];self.assertEqual(args[args.index('-a')+1],vault.ACCOUNT)
            self.assertEqual(args[args.index('-s')+1],vault.credential_target('https://coordinator.example'))
            self.assertNotIn('a'*64,repr(popen.call_args))


class ObjectSupervisionTests(unittest.TestCase):
    def test_invalid_backoff_hint_latches_without_repeated_work(self):
        for value in (-1,True,3601,float('nan'),'PRIVATE'):
            with tempfile.TemporaryDirectory() as folder:
                fake=SimpleNamespace(state=Path(folder),run_once=MagicMock(return_value={'status':'idle','retryAfterSeconds':value}))
                supervisor=OwnerSearchSupervisor(fake,wall_clock=lambda:NOW,jitter=lambda:0)
                self.assertEqual(supervisor.step()['status'],'operator_required')
                self.assertEqual(supervisor.step()['status'],'operator_required');self.assertEqual(fake.run_once.call_count,1)
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(OwnerSupervisorError):
                OwnerSearchSupervisor(SimpleNamespace(state=Path(folder),run_once=lambda:None),native_failure='PRIVATE')
