"""Finite Python->Worker->SQLite integration, no sockets/cloud/model execution.

Coverage, model inference, vault and R2 are fixtures. Python job persistence,
protected-source hashing, Worker routes, publication and ledger SQL are real.
"""
import base64
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import unittest
from unittest.mock import patch

from community.object_audit_jobs import ObjectAuditJobs
from community.owner_object_agent import OwnerObjectAuditAgent
from community.owner_object_verifier import OwnerObjectVerifier
from community.owner_search_agent import OwnerSearchError
from community.search_snapshot import digest, encoded
from community.tests import test_protected_origin as fixtures
from community import owner_object_service as service
from community import native_object_verifier as native
from community.owner_object_retirement import OwnerObjectRetirementAgent

NODE_FIXTURE=r'''
import readline from 'node:readline';
import {ownerFixture,SECRET} from './deploy/cloudflare/src/ownerObjectAudit.fixture.mjs';
import worker from './deploy/cloudflare/src/worker.js';
import {prepareObjectAuditRetention} from './deploy/cloudflare/tools/prepare-object-audit-retention.mjs';
globalThis.fetch=()=>{throw Error('fixture_network_forbidden');};
let fixture,offset=0,cleanups=[];const realNow=Date.now;Date.now=()=>realNow()+offset*1000;
try {
 for await(const raw of readline.createInterface({input:process.stdin,crlfDelay:Infinity})) {
  try {
   const input=JSON.parse(raw);let answer;
   if(input.action==='initialize'){
    fixture=await ownerFixture({after:f=>cleanups.push(f)},input.overrides);
    fixture.env.RATE_LIMITS_REQUIRED='1';
    for(const name of ['API_RATE_LIMITER','API_INGRESS_LIMITER','API_VIEW_LIMITER'])fixture.env[name]={async limit(){return {success:true};}};
    answer={ready:true};
   } else if(input.action==='advance'){offset=input.seconds;answer={advanced:true};}
   else if(input.action==='prepareRetirement'){await prepareObjectAuditRetention(fixture.env.DB);answer={prepared:true};}
   else if(input.action==='counts')answer=fixture.counts();
   else {
    const reply=await worker.fetch(new Request('https://fixture.invalid/api/object-audit-agent/'+input.action,{
     method:'POST',headers:{authorization:'Bearer '+SECRET,'content-type':'application/json'},body:JSON.stringify(input.body)}),fixture.env);
    answer={status:reply.status,raw:await reply.text()};
   }
   process.stdout.write(JSON.stringify(answer)+'\n');
  }catch(error){process.stdout.write(JSON.stringify({fixtureFailure:String(error)})+'\n');}
 }
} finally {for(const close of cleanups)close();}
'''


class PipeCoordinator:
    def __init__(self,node,root):
        self.error_mode=None;self.calls=[];self.completions=[];self.lock=threading.Lock()
        self.stderr=(root/'node.stderr.log').open('xb')
        env={k:os.environ[k] for k in ('SystemRoot','TEMP','TMP','TMPDIR') if k in os.environ}
        self.process=subprocess.Popen([node,'--input-type=module','-e',NODE_FIXTURE],
            cwd=Path(__file__).resolve().parents[2],env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
            stderr=self.stderr,shell=False,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    def close(self):
        self.process.stdin.close()
        try:self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=5)
        self.process.stdout.close();self.stderr.close()
    def rpc(self,value):
        # Fixture protocol is bounded and one-at-a-time; kill only our child on
        # a hang. It cannot contact the network or launch a hosted verifier.
        with self.lock:
            timer=threading.Timer(30,self.process.kill);timer.daemon=True;timer.start()
            try:
                self.process.stdin.write(encoded(value));self.process.stdin.flush()
                raw=self.process.stdout.readline(6*1024*1024)
                answer=json.loads(raw)
                if 'fixtureFailure' in answer:raise AssertionError(answer)
                return answer
            finally:timer.cancel()
    def post(self,action,body):
        self.calls.append(action)
        if action=='complete':
            self.completions.append(encoded(body))
            if self.error_mode=='before':raise OwnerSearchError('coordinator_unavailable',503)
        answer=self.rpc({'action':action,'body':body})
        if answer['status']!=200:
            code=json.loads(answer['raw'])['error']
            code={'owner_object_evidence_refresh_required':'object_evidence_refresh_required',
                  'owner_object_claim_lost':'object_claim_lost'}.get(code,code)
            raise OwnerSearchError(code,answer['status'])
        if action=='complete' and self.error_mode=='after':raise OwnerSearchError('coordinator_unavailable',503)
        if action=='retirement-ack' and self.error_mode=='retirement-after':raise OwnerSearchError('coordinator_unavailable',503)
        return answer['raw'].encode() if action=='candidate' else json.loads(answer['raw'])


class OwnerObjectPipelineTests(unittest.TestCase):
    def setUp(self):
        node=os.environ.get('VISION_TEST_NODE')
        if not node:self.skipTest('Explicit existing private Node runtime needed')
        self.origin=fixtures.ProtectedOriginTests('runTest');self.origin.setUp();self.addCleanup(self.origin.doCleanups)
        f=self.fixture=self.origin.fixture;self.offset=0
        def pin(path):return {'path':str(path),'bytes':path.stat().st_size,'sha256':digest(path.read_bytes())}
        registry=f.root/'assignment/registry.json'
        registry.write_bytes(encoded({'version':1,'scope':'private-object-audit-registry',
            'policyId':f.policy['policyId'],'resource':f.policy['resource'],
            'assignments':[{'leaseId':f.trusted['leaseId'],'profileId':f.trusted['profileId'],
                'assignment':pin(f.assignment),'source':pin(f.source_path)}]}))
        self.jobs=ObjectAuditJobs(f.verifier,registry,digest(registry.read_bytes()),f.root/'spool',clock=self.clock)
        self.addCleanup(self.jobs.close)
        self.engine=OwnerObjectVerifier(self.jobs,guard=lambda:None)
        self.state=f.root/'owner-state';self.state.mkdir()
        self.binding={'version':1,'scope':'object-batch-parity-v1','policyId':f.policy['policyId'],
            'policySha256':f.verifier.policy_sha256,'runtimeProfileSha256':f.verifier.profile['sha256'],
            'qualityImplementationIdentity':f.policy['qualityImplementationIdentity'],
            'protectedAuthoritySha256':f.policy['protectedAuthority']['sha256'],
            'protectedOriginHandoffSha256':f.policy['protectedOriginHandoffSha256'],
            'profiles':f.policy['profiles'],'resource':f.policy['resource']}
        self.coordinator=PipeCoordinator(node,f.root);self.addCleanup(self.coordinator.close)
        self.coordinator.rpc({'action':'initialize','overrides':{
            'index':{'manifest':json.loads((f.candidate/'manifest.json').read_bytes()),
                'sourceTsv':base64.b64encode(f.source).decode(),
                'files':{name:base64.b64encode(raw).decode() for name,raw in f.files.items()}},
            'authority':{'leaseId':f.trusted['leaseId'],'profileId':f.trusted['profileId'],'policyId':f.policy['policyId'],
                'assignmentSha256':digest(f.assignment.read_bytes()),'sourceSha256':digest(f.source)},
            'pins':{k:self.binding[k] for k in ('policySha256','runtimeProfileSha256','qualityImplementationIdentity',
                'protectedAuthoritySha256','protectedOriginHandoffSha256')}}})
    def clock(self):return time.time()+self.offset
    def agent(self):return OwnerObjectAuditAgent(self.coordinator,self.engine,self.state,self.binding,guard=lambda:None,clock=self.clock)
    def counts(self):return self.coordinator.rpc({'action':'counts'})
    def advance(self,seconds):self.offset=seconds;self.coordinator.rpc({'action':'advance','seconds':seconds})
    def interrupted(self,mode):
        self.coordinator.error_mode=mode
        with patch.object(self.fixture.verifier,'run',side_effect=self.fixture.fake_native):
            with self.assertRaisesRegex(OwnerSearchError,'coordinator_unavailable'):self.agent().run_once()
        self.assertEqual(self.fixture.calls,['runtime-info','index-segment','verify-index','verify-index'])
        return (self.state/'object-outbox.json').read_bytes()

    def test_actual_saved_audit_publication_once_credit_and_lost_ack_replay_without_native_access(self):
        saved=self.interrupted('after')
        self.assertEqual(self.counts(),{'publications':2,'ledger':1,'accepted':1,'units':20})
        self.coordinator.error_mode=None
        with patch.object(self.engine,'handle',side_effect=AssertionError('committed replay needs no native files')) as handle:
            self.assertEqual(self.agent().run_once(),{'status':'completed','accepted':2,'unitsEarned':0})
            handle.assert_not_called()
        self.assertEqual(self.coordinator.completions[-1],encoded(json.loads(saved)['body']))
        self.assertEqual(self.counts(),{'publications':2,'ledger':1,'accepted':1,'units':20})
        self.assertEqual(self.coordinator.calls,['claim','candidate','complete','complete'])

    def test_expired_uncommitted_proof_rechecks_actual_protection_without_new_inference(self):
        saved=self.interrupted('before');self.advance(31);self.coordinator.error_mode=None
        self.assertEqual(self.counts(),{'publications':0,'ledger':0,'accepted':0,'units':0})
        with patch.object(self.fixture.verifier,'run',side_effect=AssertionError('no new inference')):
            self.assertEqual(self.agent().run_once(),{'status':'completed','accepted':2,'unitsEarned':20})
        self.assertEqual((self.state/'object-outbox-before-refresh.private.json').read_bytes(),saved)
        old=json.loads(saved)['body'];new=json.loads(self.coordinator.completions[-1])
        self.assertEqual(old['audit'],new['audit']);self.assertGreater(new['evidence']['issuedAt'],old['evidence']['issuedAt'])
        self.assertEqual(self.counts(),{'publications':2,'ledger':1,'accepted':1,'units':20})
        self.assertEqual(self.fixture.calls,['runtime-info','index-segment','verify-index','verify-index'])

    def test_changed_protected_source_prevents_refresh_keeps_outbox_and_preserves_native_receipt(self):
        saved=self.interrupted('before');audit=json.loads(saved)['body']['audit'];self.advance(31)
        report=self.jobs.work/('attempts-'+audit['jobId'])/'attempt-1/audit-report.json';original=report.read_bytes()
        (self.origin.arrow/'0.arrow').write_bytes(b'changed-protected-source')
        self.coordinator.error_mode=None
        with patch.object(self.fixture.verifier,'run',side_effect=AssertionError('no inference')):
            with self.assertRaisesRegex(OwnerSearchError,'owner_object_verification_unavailable'):self.agent().run_once()
        self.assertEqual((self.state/'object-outbox.json').read_bytes(),saved);self.assertEqual(report.read_bytes(),original)
        self.assertEqual(self.counts(),{'publications':0,'ledger':0,'accepted':0,'units':0})
        self.assertFalse((self.state/'object-outbox-before-refresh.private.json').exists())

    def test_configured_runner_constructs_real_saved_auditor_and_replays_committed_reply_lazily(self):
        self.jobs.close()  # The configured runner acquires/owns this exact spool.
        f=self.fixture
        config={'version':1,'scope':service.SCOPE,'origin':'https://fixture.invalid','environment':'staging',
            'state':str(self.state),'binding':self.binding,'native':{
                'binary':str(f.binary),'models':str(f.models),'policy':str(f.policy_path),
                'policySha256':f.verifier.policy_sha256,'registry':str(f.root/'assignment/registry.json'),
                'registrySha256':digest((f.root/'assignment/registry.json').read_bytes()),'spool':str(self.jobs.work)}}
        path=f.root/'owner.private.json';path.write_bytes(encoded(config));pin=digest(path.read_bytes())
        (self.state/service.ACTIVATION).write_bytes(encoded({'version':1,'scope':'explicit-owner-object-audit-activation',
            'approved':True,'configSha256':pin,'origin':config['origin'],'environment':'staging'}))
        self.coordinator.error_mode='after'
        with patch.object(service.HTTPSObjectCoordinator,'from_os_credentials',return_value=self.coordinator),\
                patch.object(native.NativeObjectVerifier,'validate_model_paths'),\
                patch.object(native.NativeObjectVerifier,'run',side_effect=f.fake_native):
            self.assertEqual(service.run_service(path,pin,once=True)['status'],'retry_wait')
        self.assertEqual(self.counts(),{'publications':2,'ledger':1,'accepted':1,'units':20})
        saved=(self.state/'object-outbox.json').read_bytes();self.coordinator.error_mode=None
        deadline=self.state/'supervisor.json';doc=json.loads(deadline.read_bytes());doc['nextAttemptAt']=0;deadline.write_bytes(encoded(doc))
        f.policy_path.unlink()  # Committed replay requires no new native inputs.
        with patch.object(service.HTTPSObjectCoordinator,'from_os_credentials',return_value=self.coordinator),\
                patch.object(service,'NativeObjectVerifier',side_effect=AssertionError('lazy replay')) as constructor:
            self.assertEqual(service.run_service(path,pin,once=True)['status'],'completed');constructor.assert_not_called()
        self.assertEqual(self.coordinator.completions[-1],encoded(json.loads(saved)['body']))
        self.assertEqual(f.calls,['runtime-info','index-segment','verify-index','verify-index'])
        self.assertEqual(self.counts(),{'publications':2,'ledger':1,'accepted':1,'units':20})

    def test_owner_retirement_releases_only_successful_bulk_and_recovers_ack_without_native_inputs(self):
        saved=self.interrupted('after');self.coordinator.error_mode=None;self.agent().run_once()
        audit=json.loads(saved)['body']['audit'];job=audit['jobId']
        attempt=self.jobs.work/('attempts-'+job)/'attempt-1';report=attempt/'audit-report.json';original=report.read_bytes()
        self.assertTrue((self.jobs.work/job/'candidate').exists());self.assertTrue((attempt/'reference').exists())
        self.coordinator.rpc({'action':'prepareRetirement'});self.coordinator.error_mode='retirement-after'
        with patch.object(self.fixture.verifier,'run',side_effect=AssertionError('cleanup cannot infer')):
            with self.assertRaisesRegex(OwnerSearchError,'coordinator_unavailable'):
                OwnerObjectRetirementAgent(self.agent()).run_once()
        self.assertFalse((self.jobs.work/job).exists());self.assertFalse((attempt/'reference').exists())
        self.assertEqual(report.read_bytes(),original);self.assertEqual(self.jobs.get(job)['state'],'retired')
        pending=(self.state/'retirement-outbox.json').read_bytes();self.coordinator.error_mode=None
        with patch.object(self.engine,'handle',side_effect=AssertionError('saved ack needs no native files')) as handle:
            self.assertEqual(OwnerObjectRetirementAgent(self.agent()).run_once()['status'],'completed');handle.assert_not_called()
        self.assertFalse((self.state/'retirement-outbox.json').exists())
        self.assertEqual(json.loads(pending)['audit']['state'],'retired')
        self.assertEqual(self.fixture.calls,['runtime-info','index-segment','verify-index','verify-index'])
        self.assertEqual(self.counts(),{'publications':2,'ledger':1,'accepted':1,'units':20})
