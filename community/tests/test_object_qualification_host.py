"""Owned delivery/lookup and finite loopback HTTP, with synthetic saved data."""
import copy
import http.client
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from community import object_qualification_host as host
from community import object_qualification_store as store
from community.object_qualification import ObjectQualificationError
from community.search_snapshot import digest, encoded
from community.tests import test_object_qualification_evidence as fixtures

NOW = fixtures.NOW


class OwnedSampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.SavedObjectQualificationEvidenceTests.setUpClass()
        cls.addClassCleanup(fixtures.SavedObjectQualificationEvidenceTests.doClassCleanups)
        cls.fixture = case = fixtures.SavedObjectQualificationEvidenceTests()
        case.setUp()
        case.adapter()
        cls.engine, cls.request = case.engine, copy.deepcopy(case.request)
        cls.original = __import__('json').loads(case.manifest_path.read_bytes())

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).absolute()
        self.source, self.destination = self.root / 'incoming', self.root / 'owned'
        self.source.mkdir(); self.destination.mkdir()
        artifacts = copy.deepcopy(self.original)
        for field in ('scoreRequest', 'executionReceipt', 'indexManifest'):
            path = self.source / artifacts[field]['path']
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((self.fixture.root / artifacts[field]['path']).read_bytes())
        original_index = self.fixture.candidate.parent
        for path in original_index.glob('*.bin'):
            (self.source / self.original['indexManifest']['path']).parent.joinpath(path.name).write_bytes(path.read_bytes())
        raw = encoded(artifacts)
        (self.source / 'artifacts.json').write_bytes(raw)
        self.request = {**self.request, 'artifactSetSha256': digest(raw)}
        def pin(path):
            raw = path.read_bytes()
            return {'path': path.relative_to(self.source).as_posix(), 'bytes': len(raw), 'sha256': digest(raw)}
        self.package_doc = {'version': 1, 'scope': 'sealed-owned-object-sample-delivery-v1',
            **{k: self.request[k] for k in ('accountId','requestId','profileId','artifactSetSha256','policySha256')},
            'artifacts': pin(self.source / 'artifacts.json'),
            'files': [pin(p) for p in sorted(self.source.rglob('*')) if p.is_file()]}
        self.package = self.source / 'package.json'
        self.approval = self.root / 'transfer-approval.private.json'
        self.permit = {'version': 1, 'scope': 'operator-approved-private-object-sample-delivery-v1',
            **{k: self.request[k] for k in ('accountId','requestId','profileId','artifactSetSha256','policySha256')},
            'packageSha256': '', 'sourceRootSha256': store.path_identity(self.source),
            'destinationRootSha256': store.path_identity(self.destination), 'validFrom': NOW - 1, 'validUntil': NOW + 3600}
        self.save()

    def save(self):
        self.package.write_bytes(encoded(self.package_doc))
        self.package_sha = digest(self.package.read_bytes())
        self.permit['packageSha256'] = self.package_sha
        self.approval.write_bytes(encoded(self.permit))
        self.approval_sha = digest(self.approval.read_bytes())

    def deliver(self):
        return store.deliver_owned_sample(self.package, self.package_sha, self.approval, self.approval_sha, self.destination, now=NOW)

    def owned_store(self):
        entry = self.deliver()
        self.catalog = self.root / 'jobs.private.json'
        self.catalog_doc = {'version': 1, 'scope': 'trusted-owned-object-sample-jobs-v1',
            'rootSha256': store.path_identity(self.destination), 'policySha256': self.engine.policy_sha256,
            'resource': self.engine.scores.policy['resource'], 'jobs': [entry]}
        self.catalog.write_bytes(encoded(self.catalog_doc))
        return store.OwnedObjectQualificationStore(self.engine,self.destination,self.catalog,digest(self.catalog.read_bytes()))

    def fast_report(self):
        return {'profileId':self.request['profileId'],'expiresAt':NOW+3600,'qualified':False}

    def test_owned_delivery_and_lookup_reach_real_full_sample_comparator(self):
        owned = self.owned_store()
        value = owned.evidence(self.request, now=NOW)
        self.assertTrue(value['report']['sampleCompatible'])
        self.assertEqual(value['report']['locations'],100)
        self.assertFalse(value['report']['qualified'])
        self.assertEqual(value['report']['acceptedContributions'],0)
        self.assertNotIn(str(self.root),encoded(value).decode())
        self.assertEqual(len(list(self.destination.iterdir())),2)  # Owned job and writer lock only.

    def test_destination_owner_policy_expiry_and_exact_package_consent_are_required(self):
        for changes in ({'accountId':'9'*32},{'requestId':'9'*32},{'profileId':'9'*64}, {'artifactSetSha256':'9'*64},
                        {'policySha256':'9'*64},{'sourceRootSha256':'9'*64},{'destinationRootSha256':'9'*64},
                        {'validUntil':NOW},{'validUntil':NOW+31*86400},{'version':True},{'approved':True}):
            original = copy.deepcopy(self.permit)
            self.permit.update(changes);self.save()
            with self.assertRaises(ObjectQualificationError):self.deliver()
            self.permit = original
        self.save();self.package.write_bytes(b'{}')
        with self.assertRaises(ObjectQualificationError):self.deliver()
        self.assertEqual([p.name for p in self.destination.iterdir()],['service.lock'])

    def test_no_unrelated_files_are_copied_or_automatically_catalogued(self):
        (self.source/'private-unrelated.txt').write_text('private')
        entry = self.deliver()
        target = self.destination/entry['jobId']
        self.assertFalse((target/'private-unrelated.txt').exists())
        self.assertFalse((self.destination/'jobs.private.json').exists())
        receipt = __import__('json').loads((target/'delivery.json').read_bytes())
        self.assertNotIn('detector',receipt)
        self.assertNotIn('qualified',receipt)
        with self.assertRaisesRegex(ObjectQualificationError,'delivery_exists'):self.deliver()

    def test_unlisted_or_changed_index_files_never_create_visible_job(self):
        name = self.original['indexManifest']['path'].split('/')[0] + '/semantic-pq128.bin'
        (self.source/name).write_bytes(b'changed')
        with self.assertRaises(ObjectQualificationError):self.deliver()
        self.assertFalse((self.destination/store.job_identity(self.request)).exists())

    def test_missing_and_unrelated_sealed_inventory_are_rejected(self):
        original = copy.deepcopy(self.package_doc)
        self.package_doc['files'] = [e for e in self.package_doc['files'] if e['path']!='adapter-execution.json']
        self.save()
        with self.assertRaises(ObjectQualificationError):self.deliver()
        self.package_doc=original
        extra=self.source/'unrelated.json';extra.write_bytes(b'{}')
        self.package_doc['files'].append({'path':extra.name,'bytes':2,'sha256':digest(b'{}')});self.save()
        with self.assertRaisesRegex(ObjectQualificationError,'unrelated'):self.deliver()

    def test_cross_platform_unsafe_duplicate_and_oversized_inventory_is_rejected(self):
        original = copy.deepcopy(self.package_doc)
        for changes in ({'path':'../private'},{'path':'/private'},{'path':'C:/private'},{'path':'x:private'},
                        {'path':'CON.txt'},{'path':'folder/NUL'},{'path':'folder/..'},{'bytes':store.MAX_BYTES+1},{'bytes':True}):
            self.package_doc=copy.deepcopy(original);self.package_doc['files'][0].update(changes);self.save()
            with self.assertRaises(ObjectQualificationError):self.deliver()
        self.package_doc=copy.deepcopy(original)
        self.package_doc['files'].append(dict(self.package_doc['files'][0]));self.save()
        with self.assertRaises(ObjectQualificationError):self.deliver()

    def test_paused_root_and_store_capacity_block_delivery_without_deleting_evidence(self):
        pause=self.destination/'PAUSE';pause.write_text('held')
        with self.assertRaisesRegex(ObjectQualificationError,'paused'):self.deliver()
        pause.unlink()  # Synthetic fixture only; no actual pause marker is accessed.
        for i in range(store.MAX_JOBS):(self.destination/('retained-'+str(i))).mkdir()
        with self.assertRaisesRegex(ObjectQualificationError,'store_full'):self.deliver()
        self.assertTrue((self.destination/'retained-0').exists())

    def test_partial_failed_copy_is_preserved_and_blocks_automatic_retry(self):
        original=store.pinned_read
        def fail_copy(path,*args):
            if '.partial-' in str(path):raise OSError('private path must stay private')
            return original(path,*args)
        with patch.object(store,'pinned_read',side_effect=fail_copy):
            with self.assertRaisesRegex(ObjectQualificationError,'delivery_unavailable'):self.deliver()
        partial=self.destination/('.partial-'+store.job_identity(self.request))
        self.assertTrue(partial.is_dir());self.assertTrue((partial/'package.json').exists())
        with self.assertRaisesRegex(ObjectQualificationError,'delivery_exists'):self.deliver()
        self.assertFalse((self.destination/store.job_identity(self.request)).exists())

    def test_dedicated_writer_lock_prevents_concurrent_import(self):
        with store._exclusive(self.destination,name='service.lock'):
            with self.assertRaisesRegex(ObjectQualificationError,'delivery_unavailable'):self.deliver()
        self.assertFalse((self.destination/store.job_identity(self.request)).exists())

    def test_request_cannot_select_another_job_path_policy_or_profile(self):
        owned=self.owned_store()
        with patch.object(self.engine,'qualify',side_effect=AssertionError('must not compare unowned data')):
            for changes in ({'accountId':'9'*32},{'requestId':'9'*32},{'profileId':'9'*64},
                            {'artifactSetSha256':'9'*64},{'policySha256':'9'*64},{'path':'private'}, {'approved':True}):
                with self.assertRaises(ObjectQualificationError):owned.evidence({**self.request,**changes},now=NOW)

    def test_pause_catalog_and_retained_file_changes_fence_late_evidence(self):
        owned=self.owned_store()
        raw=self.catalog.read_bytes()
        def change_catalog(*args,**kwargs):
            self.catalog.write_bytes(b'{}');return self.fast_report()
        with patch.object(self.engine,'qualify',side_effect=change_catalog):
            with self.assertRaises(ObjectQualificationError):owned.evidence(self.request,now=NOW)
        self.catalog.write_bytes(raw)
        def pause(*args,**kwargs):
            (self.destination/'PAUSE').write_text('held');return self.fast_report()
        with patch.object(self.engine,'qualify',side_effect=pause):
            with self.assertRaisesRegex(ObjectQualificationError,'paused'):owned.evidence(self.request,now=NOW)

    def test_missing_or_expired_receipt_and_policy_are_service_failure(self):
        owned=self.owned_store()
        with self.assertRaises(ObjectQualificationError):owned.evidence(self.request,now=NOW+3600)
        (self.destination/store.job_identity(self.request)/'delivery.json').write_bytes(b'{}')
        with self.assertRaises(ObjectQualificationError):owned.evidence(self.request,now=NOW)

    def test_restart_uses_exact_operator_catalog_pin_not_cached_admission(self):
        owned=self.owned_store()
        with patch.object(self.engine,'qualify',return_value=self.fast_report()):
            self.assertEqual(owned.evidence(self.request,now=NOW)['requestId'],self.request['requestId'])
        self.catalog_doc['jobs']=[];self.catalog.write_bytes(encoded(self.catalog_doc))
        with self.assertRaises(ObjectQualificationError):owned.evidence(self.request,now=NOW)
        restarted=store.OwnedObjectQualificationStore(self.engine,self.destination,self.catalog,digest(self.catalog.read_bytes()))
        with self.assertRaisesRegex(ObjectQualificationError,'job_unavailable'):restarted.evidence(self.request,now=NOW)

    def test_catalog_cannot_change_resources_repeat_jobs_or_select_arbitrary_paths(self):
        owned=self.owned_store()
        original=copy.deepcopy(self.catalog_doc)
        for change in ('resource','duplicate','path','size','root','policy'):
            doc=copy.deepcopy(original)
            if change=='resource':doc['resource']['bucket']='unrelated-resource'
            if change=='duplicate':doc['jobs']*=2
            if change=='path':doc['jobs'][0]['receipt']['path']='../private.json'
            if change=='size':doc['jobs'][0]['receipt']['bytes']=True
            if change=='root':doc['rootSha256']='9'*64
            if change=='policy':doc['policySha256']='9'*64
            self.catalog.write_bytes(encoded(doc))
            with self.assertRaises(ObjectQualificationError):
                store.OwnedObjectQualificationStore(self.engine,self.destination,self.catalog,digest(self.catalog.read_bytes()))

    def test_changed_binary_after_comparison_is_not_delivered_as_evidence(self):
        owned=self.owned_store()
        def change_binary(*args,**kwargs):
            folder=self.destination/store.job_identity(self.request)/'adapter-candidate'
            next(folder.glob('*.bin')).write_bytes(b'changed')
            return self.fast_report()
        with patch.object(self.engine,'qualify',side_effect=change_binary):
            with self.assertRaises(ObjectQualificationError):owned.evidence(self.request,now=NOW)

    def test_http_oversized_private_proof_cannot_escape_response_bound(self):
        owned,server=self.server()
        with patch.object(owned,'evidence',return_value={'private':'x'*(host.MAX_RESPONSE+1)}):
            status,raw,_=self.call(server)
        self.assertEqual(status,503)
        self.assertEqual(__import__('json').loads(raw),{'error':'object_sample_host_unavailable'})

    def server(self):
        owned=self.owned_store()
        server=host.make_server(owned,'s'*40)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(thread.join,2);self.addCleanup(server.shutdown)
        self.assertEqual(server.server_address[0],'127.0.0.1')
        return owned,server

    def call(self,server,raw=None,*,path=host.ROUTE,method='POST',headers=None):
        connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
        try:
            connection.request(method,path,body=encoded(self.request) if raw is None else raw,
                headers={'Authorization':'Bearer '+'s'*40,'Content-Type':'application/json',**(headers or {})})
            response=connection.getresponse()
            return response.status,response.read(),dict(response.getheaders())
        finally:connection.close()

    def test_loopback_auth_and_exact_route_never_compare_unauthorized_input(self):
        owned,server=self.server()
        with patch.object(owned,'evidence',side_effect=AssertionError('must not read artifacts')):
            for changes in ({'headers':{'Authorization':'Bearer wrong'}},{'path':'/object-audits'},
                            {'path':host.ROUTE+'?path=private'},{'method':'GET'}):
                status,raw,_=self.call(server,**changes)
                self.assertIn(status,(401,404));self.assertNotIn(b'private',raw)

    def test_framing_duplicate_json_and_size_limits_never_compare(self):
        owned,server=self.server()
        with patch.object(owned,'evidence',side_effect=AssertionError('invalid body compared')):
            for raw,headers in ((b'{"accountId":1,"accountId":2}',{}),(b'{"x":NaN}',{}),(b'x'*4097,{}),
                                (b'{}',{'Content-Type':'text/plain'}),(b'{}',{'Content-Encoding':'gzip'})):
                self.assertEqual(self.call(server,raw,headers=headers)[0],400)

    def test_comparison_busy_and_private_exceptions_are_bounded_sanitized(self):
        owned,server=self.server()
        with patch.object(owned,'evidence',side_effect=OSError(str(self.root))):
            status,raw,headers=self.call(server)
            self.assertEqual(status,503);self.assertNotIn(str(self.root).encode(),raw)
            self.assertEqual(headers['Cache-Control'],'no-store')
        with server.comparison:
            with patch.object(owned,'evidence',side_effect=AssertionError('must not compare busy')):
                self.assertEqual(self.call(server)[0],503)
        self.assertTrue(server.comparison.acquire(blocking=False));server.comparison.release()

    def test_http_response_retains_false_numerical_authority_and_no_private_headers(self):
        owned,server=self.server()
        with patch.object(self.engine,'qualify',return_value=self.fast_report()):
            evidence=owned.evidence(self.request,now=NOW)
        with patch.object(owned,'evidence',return_value=evidence):
            status,raw,headers=self.call(server)
        self.assertEqual(status,200)
        self.assertIn(b'"qualified":false',raw)
        self.assertEqual(int(headers['Content-Length']),len(raw))
        self.assertEqual(headers['Connection'],'close')
        self.assertNotIn(str(self.root).encode(),raw)

    def test_host_requires_dedicated_secret_and_owned_store(self):
        owned=self.owned_store()
        for secret in ('short','s'*257,'s'*40+'\n'):
            with self.assertRaises(ObjectQualificationError):host.make_server(owned,secret)
        with self.assertRaises(ObjectQualificationError):host.make_server(object(),'s'*40)


if __name__ == '__main__':
    unittest.main()
