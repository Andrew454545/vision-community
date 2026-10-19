"""Synthetic contributor seals, mocked native scores and real Python/JS proof parity."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import Mock, patch

from community import scene_membership as seal
from community import native_scene_search as native
from community import owner_search_service as service
from community.owner_search_agent import OwnerSearchError
from community.search_snapshot import digest, encoded
from community.tests import test_search_snapshot as snapshot_fixture
from community.tests import test_native_scene_search as native_fixture

ROOT = Path(__file__).resolve().parents[2]


class LocalWorkerCoordinator:
    """Finite real Worker/SQLite calls, no HTTPS, vault, model or cloud access."""

    def __init__(self, root, header, raw_query):
        self.root, self.header, self.raw_query = root, header, raw_query
        self.node = os.environ.get('VISION_TEST_NODE') or shutil.which('node')
        if not self.node:
            raise AssertionError('Use the existing private Node runtime')
        self.database = root/'fictional.sqlite'
        self.calls, self.sequence = [], 0
        self.lose_reply, self.delete_before_complete, self.invalid_root = False, False, False
        self.step('initialize')

    def step(self, action, body=None):
        self.sequence += 1
        stem = self.root/('bridge-'+str(self.sequence))
        document = {'header':self.header, 'rawQuery':self.raw_query, 'action':action,
                    'body':body, 'invalidRoot':self.invalid_root}
        command = stem.with_suffix('.json'); command.write_bytes(encoded(document))
        script = "import{transportStep}from './deploy/cloudflare/src/sceneMembership.fixture.mjs';import{readFileSync}from'node:fs';console.log(JSON.stringify(await transportStep(JSON.parse(readFileSync(process.argv[1],'utf8')),process.argv[2])));"
        environment = {k:v for k,v in os.environ.items() if k in {'SystemRoot','SYSTEMROOT','TEMP','TMP','TMPDIR'}}
        child = subprocess.run([self.node,'--disable-warning=ExperimentalWarning','--input-type=module','-e',script,
                                str(command),str(self.database)],cwd=ROOT,env=environment,
                               capture_output=True,timeout=30,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        # Every finite child's evidence stays private, including the first failure.
        stem.with_suffix('.stdout.log').write_bytes(child.stdout)
        stem.with_suffix('.stderr.log').write_bytes(child.stderr)
        if child.returncode:
            raise AssertionError(child.stderr.decode(errors='replace'))
        return json.loads(child.stdout)

    def post(self, action, body):
        self.calls.append((action,copy.deepcopy(body)))
        if action=='complete' and self.delete_before_complete:
            self.step('delete'); self.delete_before_complete=False
        response = self.step(action,body)
        if response['status'] != 200:
            code = 'search_claim_lost' if response['status']==409 and response['document'].get('error')=='search_claim_lost' else 'coordinator_unavailable'
            raise OwnerSearchError(code,response['status'])
        if action=='complete' and self.lose_reply:
            self.lose_reply=False
            raise OwnerSearchError('coordinator_unavailable')
        return response['document']


class SceneMembershipTests(unittest.TestCase):
    def setUp(self):
        # Composition avoids unittest rediscovering another fixture's full suite.
        self.fixture = snapshot_fixture.SearchSnapshotTest('runTest')
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root.resolve()
        if self._testMethodName.startswith('test_actual_owner_service_'):
            self.addCleanup(self.preserve_bridge_evidence,self._testMethodName,self.root/'owner-state')
        self.fixture.rows[0]['country'] = 'Côte d’Ivoire'
        self.fixture.rows[0]['lat'] = 1e-7
        for reference in self.fixture.policy['references']:
            if reference['assetId'] == self.fixture.rows[0]['asset_id']:
                reference['lat'] = 1e-7
        self.snapshot = self.root/'snapshot'
        self.snapshot_pin = self.fixture.build()['snapshotSha256']
        self.runtime_pin = 'b'*64
        self.report = seal.build_membership(self.snapshot, self.snapshot_pin, self.root/'membership',
            environment='production', policy_id='synthetic-test-only', runtime_sha256=self.runtime_pin)
        self.path = self.root/'membership/membership.json'
        self.proofs = self.open()

    def open(self, **changes):
        args = dict(environment='production', policy_id='synthetic-test-only', runtime_sha256=self.runtime_pin)
        args.update(changes)
        return seal.SceneMembershipProofs(self.snapshot, self.snapshot_pin, self.path,
            self.report['membershipSha256'], **args)

    def packet(self):
        h = self.proofs.header
        return {'contractVersion': 2, **{k:h[k] for k in ('policyId','runtimeSha256','snapshotSha256')},
            'processedLocations': len(self.proofs.members), 'requestSha256':'f'*64,
            'hits': [{**{k:m[k] for k in ('locationId','sourceIndex','outputSha256')},
                      'score': .9-i*.1, 'viewOffset':0} for i,m in enumerate(self.proofs.members)]}

    def test_deterministic_seal_contains_only_digests_and_no_account_or_private_paths(self):
        second = seal.build_membership(self.snapshot, self.snapshot_pin, self.root/'second',
            environment='production', policy_id='synthetic-test-only', runtime_sha256=self.runtime_pin)
        self.assertEqual(second, self.report)
        self.assertEqual(set(p.name for p in self.path.parent.iterdir()), {'tree.bin','membership.json'})
        for path in self.path.parent.iterdir():
            self.assertNotIn(b'private-anonymous-account-id', path.read_bytes())
            self.assertNotIn(str(self.root).encode(), path.read_bytes())
        self.assertIn(b'1e-07', self.proofs.raw_members[1])
        self.assertIn('Côte d’Ivoire', self.proofs.proof(1)['memberJson'])

    def test_changed_manifest_tree_or_snapshot_is_refused_without_repair_or_overwrite(self):
        for path in (self.path, self.path.parent/'tree.bin', self.snapshot/'members.json'):
            original = path.read_bytes(); changed = original[:-1]+bytes([original[-1]^1])
            path.write_bytes(changed)
            with self.subTest(file=path.name), self.assertRaises(ValueError): self.proofs.verify_inputs()
            self.assertEqual(path.read_bytes(), changed)
            path.write_bytes(original)

    def test_self_reported_tree_hash_cannot_replace_derivation_from_contributed_snapshot(self):
        tree = self.path.parent/'tree.bin'; tree.write_bytes(b'forged-tree')
        document = json.loads(self.path.read_bytes())
        document['files']['tree.bin'] = {'bytes':10, 'sha256':digest(tree.read_bytes())}
        self.path.write_bytes(encoded(document)); self.report['membershipSha256'] = digest(self.path.read_bytes())
        with self.assertRaises(ValueError): self.open()
        self.assertEqual(tree.read_bytes(), b'forged-tree')

    def test_exact_environment_runtime_policy_and_pin_are_required(self):
        for changes in ({'environment':'staging'}, {'policy_id':'other'}, {'runtime_sha256':'e'*64}):
            with self.subTest(changes=changes), self.assertRaises(ValueError): self.open(**changes)
        self.report['membershipSha256'] = 'e'*64
        with self.assertRaises(ValueError): self.open()

    def test_build_cannot_overwrite_source_existing_seal_or_accept_an_unpinned_snapshot(self):
        for destination, pin in ((self.snapshot, self.snapshot_pin), (self.path.parent, self.snapshot_pin),
                                 (self.root/'wrong-pin', 'e'*64)):
            with self.subTest(destination=destination.name), self.assertRaises((ValueError, FileExistsError)):
                seal.build_membership(self.snapshot, pin, destination, environment='production',
                    policy_id='synthetic-test-only', runtime_sha256=self.runtime_pin)
        self.proofs.verify_inputs()

    def test_member_schema_numeric_and_duplicate_identity_limits_fail_closed(self):
        originals = self.proofs.members
        for change in (lambda m:m[0].update(locationId=[]), lambda m:m[0].update(sourceIndex=True),
                       lambda m:m[0]['pose'].update(lat=float('nan')), lambda m:m[0]['pose'].update(panoId=''),
                       lambda m:m[0]['pose'].update(country='private\nname'),
                       lambda m:m[1].update(locationId=m[0]['locationId'])):
            members = copy.deepcopy(originals); change(members)
            with self.assertRaises(ValueError): seal.tree_for(members, self.proofs.header)

    def test_wrapping_preserves_exact_query_bytes_and_native_scores(self):
        engine = Mock(); packet = self.packet(); engine.search.return_value = packet
        raw = b'{"resultCount":2,"minimumGlobalLocation":1e-7}'
        request = {'query':json.loads(raw)}
        result = seal.SceneMembershipEngine(engine,self.proofs).search(request,raw_query=raw)
        engine.search.assert_called_once_with(request,raw_query=raw)
        self.assertEqual(result['hits'], packet['hits'])
        self.assertEqual(result['membership'], [self.proofs.proof(i) for i in range(2)])
        self.assertNotIn('membership', packet)

    def test_request_cap_refuses_before_native_and_native_binding_mismatches_never_attach_proofs(self):
        engine = Mock(); wrapper = seal.SceneMembershipEngine(engine,self.proofs)
        for value in (None, 0, True, 65, 1.5):
            with self.assertRaises(ValueError): wrapper.search({'query':{'resultCount':value}},raw_query=b'{}')
        engine.search.assert_not_called()
        changes = [lambda p:p.update(processedLocations=True),lambda p:p.update(processedLocations=3),
            lambda p:p.update(snapshotSha256='e'*64),lambda p:p['hits'][0].update(sourceIndex=1),
            lambda p:p['hits'][0].update(locationId=99),lambda p:p['hits'][0].update(outputSha256='e'*64)]
        for change in changes:
            packet=self.packet();change(packet);engine.search.return_value=packet
            with self.assertRaises(ValueError): wrapper.search({'query':{'resultCount':2}},raw_query=b'{}')

    def test_change_during_computation_is_refused_and_evidence_remains(self):
        changed = self.path.read_bytes()+b' '
        def compute(*args,**kwargs):
            self.path.write_bytes(changed);return self.packet()
        engine=Mock();engine.search.side_effect=compute
        with self.assertRaises(ValueError):
            seal.SceneMembershipEngine(engine,self.proofs).search({'query':{'resultCount':2}},raw_query=b'{}')
        self.assertEqual(self.path.read_bytes(),changed)

    def test_python_native_adapter_proofs_pass_actual_js_gateway_once_only_payment_and_deletion(self):
        node = os.environ.get('VISION_TEST_NODE') or shutil.which('node')
        self.assertTrue(node, 'Use the existing private Node runtime for cross-language acceptance')
        f=native_fixture.NativeSceneSearchTest('runTest');f.setUp();self.addCleanup(f.doCleanups)
        report=seal.build_membership(f.snapshot,f.snapshot_pin,f.root/'membership',environment='production',
            policy_id='synthetic-only',runtime_sha256=f.engine.runtime_sha256)
        proofs=seal.SceneMembershipProofs(f.snapshot,f.snapshot_pin,f.root/'membership/membership.json',
            report['membershipSha256'],environment='production',policy_id='synthetic-only',runtime_sha256=f.engine.runtime_sha256)
        q=native_fixture.query(resultCount=4,prompt='café road');request=f.request(q)
        raw=json.dumps(q,ensure_ascii=False,separators=(',',':')).encode()
        with patch.object(native,'run_native',side_effect=f.fake_native) as child:
            packet=seal.SceneMembershipEngine(f.engine,proofs).search(request,raw_query=raw)
        child.assert_called_once()
        # Include Python's exponent notation and non-ASCII member bytes: JS must
        # verify the exact sealed bytes, never reserialize floating-point poses.
        q2=native_fixture.query(resultCount=2,prompt='café road')
        raw2=json.dumps(q2,ensure_ascii=False,separators=(',',':')).encode()
        second=self.packet();second['requestSha256']=digest(raw2)
        second['membership']=[self.proofs.proof(i) for i in range(2)]
        document=self.root/'interop.json';document.write_bytes(encoded([
            {'header':self.report['coordinatorBinding'],'rawQuery':raw2.decode(),'packet':second},
            {'header':report['coordinatorBinding'],'rawQuery':raw.decode(),'packet':packet}]))
        script="import{interop}from './deploy/cloudflare/src/sceneMembership.fixture.mjs';import{readFileSync}from'node:fs';const results=[];for(const d of JSON.parse(readFileSync(process.argv[1],'utf8')))results.push(await interop(d));console.log(JSON.stringify(results));"
        result=subprocess.run([node,'--disable-warning=ExperimentalWarning','--input-type=module','-e',script,str(document)],
            cwd=ROOT,capture_output=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        evidence=os.environ.get('VISION_TEST_EVIDENCE_DIR')
        if evidence:
            folder=Path(evidence);folder.mkdir(exist_ok=True)
            (folder/'interop.stdout.log').write_bytes(result.stdout)
            (folder/'interop.stderr.log').write_bytes(result.stderr)
        self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
        response=json.loads(result.stdout)
        self.assertEqual(response,[{'status':'SEALED_SCENE_MEMBERSHIP_INTEROP_PASSED','results':n,
            'catalogLookups':0,'onceOnlyDebits':1,'deletionFences':1,'synthetic':True,'liveReady':False} for n in (2,4)])

    def assembled_service(self):
        # A fictional pinned runtime substitutes only inference. The real seal,
        # wrapper, service guards, locks, supervisor, outbox and gateway execute.
        runtime_folder=self.root/'service-runtime';runtime_folder.mkdir()
        runtime=runtime_folder/'fictional-runtime.json'
        runtime.write_bytes(encoded({'contractVersion':2,'policyId':'synthetic-test-only'}))
        runtime_pin=digest(runtime.read_bytes())
        report=seal.build_membership(self.snapshot,self.snapshot_pin,self.root/'service-membership',
            environment='production',policy_id='synthetic-test-only',runtime_sha256=runtime_pin)
        state=self.root/'owner-state';state.mkdir()
        config={'version':1,'scope':service.SCOPE,'origin':'https://community.example.test',
            'environment':'production','state':str(state),'lanes':{'scene':{
                'policyId':'synthetic-test-only','runtime':str(runtime),'runtimeSha256':runtime_pin,
                'snapshot':str(self.snapshot),'snapshotSha256':self.snapshot_pin,
                'membership':str(self.root/'service-membership/membership.json'),
                'membershipSha256':report['membershipSha256']}}}
        path=self.root/'service.private.json';path.write_bytes(encoded(config));pin=digest(path.read_bytes())
        (state/service.ACTIVATION).write_bytes(encoded({'version':1,'scope':'explicit-owner-search-activation',
            'approved':True,'configSha256':pin,'origin':config['origin'],'environment':'production'}))
        raw=json.dumps(native_fixture.query(resultCount=2,prompt='café road'),ensure_ascii=False,separators=(',',':'))
        coordinator=LocalWorkerCoordinator(self.root,report['coordinatorBinding'],raw)
        engine=Mock()
        def search(request,*,raw_query):
            self.assertEqual(raw_query,raw.encode())
            packet=self.packet();packet.update(runtimeSha256=runtime_pin,requestSha256=digest(raw_query))
            self.assertEqual(request['requestSha256'],packet['requestSha256'])
            return packet
        engine.search.side_effect=search
        return path,pin,state,coordinator,engine

    def preserve_bridge_evidence(self, name, state):
        destination=os.environ.get('VISION_TEST_EVIDENCE_DIR')
        if destination:
            folder=Path(destination)/name;folder.mkdir(exist_ok=False)
            for path in self.root.glob('bridge-*'):shutil.copyfile(path,folder/path.name)
            for path in state.glob('*.json'):shutil.copyfile(path,folder/path.name)

    def test_actual_owner_service_proof_delivery_lost_ack_restart_and_paid_recovery_without_native_files(self):
        path,pin,state,coordinator,engine=self.assembled_service()
        coordinator.lose_reply=True
        with patch.object(service.HTTPSCoordinator,'from_os_credentials',return_value=coordinator), \
                patch.object(native,'NativeSceneEngine',return_value=engine) as constructor:
            first=service.run_service(path,pin,once=True)
            self.assertEqual(first['status'],'retry_wait')
            self.assertEqual(coordinator.step('stats')['document'],
                {'units':100,'debits':1,'paidReplies':1,'locations':0,'publications':0})
            saved=(state/'outbox.json').read_bytes()
            failure=(state/'supervisor.failure.json').read_bytes()
            self.assertIn(b'1e-07',saved)
            self.assertNotIn('café road'.encode(),saved)
            # Exact paid completion replay must precede all new root/native checks.
            shutil.rmtree(self.root/'service-membership');shutil.rmtree(self.snapshot)
            shutil.rmtree(self.root/'service-runtime');coordinator.invalid_root=True
            timer=state/'supervisor.json';value=json.loads(timer.read_bytes())
            value['nextAttemptAt']=0;timer.write_bytes(encoded(value))
            engine.search.side_effect=AssertionError('No recomputation after paid acknowledgement loss')
            second=service.run_service(path,pin,once=True)
            self.assertEqual(second['status'],'completed')
            constructor.assert_called_once();engine.search.assert_called_once()
        self.assertEqual([action for action,_ in coordinator.calls],['claim','complete','complete'])
        self.assertEqual(coordinator.calls[-1][1],coordinator.calls[-2][1])
        self.assertEqual(saved,encoded({'action':'complete','body':coordinator.calls[-1][1]}))
        self.assertFalse((state/'outbox.json').exists())
        self.assertEqual((state/'supervisor.failure.json').read_bytes(),failure)
        self.assertEqual(coordinator.step('stats')['document'],
            {'units':100,'debits':1,'paidReplies':1,'locations':0,'publications':0})

    def test_actual_owner_service_account_deletion_before_proof_delivery_prevents_payment(self):
        path,pin,state,coordinator,engine=self.assembled_service()
        coordinator.delete_before_complete=True
        with patch.object(service.HTTPSCoordinator,'from_os_credentials',return_value=coordinator), \
                patch.object(native,'NativeSceneEngine',return_value=engine):
            self.assertEqual(service.run_service(path,pin,once=True)['status'],'claim_lost')
        engine.search.assert_called_once()
        self.assertEqual([action for action,_ in coordinator.calls],['claim','complete'])
        self.assertFalse((state/'outbox.json').exists())
        self.assertEqual(coordinator.step('stats')['document'],
            {'units':0,'debits':0,'paidReplies':0,'locations':0,'publications':0})


if __name__=='__main__': unittest.main()
