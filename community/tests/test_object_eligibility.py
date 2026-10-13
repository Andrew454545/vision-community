"""Private live-origin protection adapter; original files are synthetic only."""
import time
import unittest
from unittest.mock import patch

from community.object_audit_jobs import ObjectAuditJobs
from community.object_eligibility import LiveObjectProtection,ObjectEligibilityError
from community.search_snapshot import digest,encoded
from community.tests import test_protected_origin as origin_fixture


class ObjectEligibilityTests(unittest.TestCase):
    def setUp(self):
        self.source=origin_fixture.ProtectedOriginTests();self.source.setUp();self.addCleanup(self.source.doCleanups)
        f=self.source.fixture;self.root=f.root;now=int(time.time())
        self.registry=self.root/'assignment/eligibility-registry.json'
        pin=lambda p:{'path':str(p),'bytes':p.stat().st_size,'sha256':digest(p.read_bytes())}
        self.registry.write_bytes(encoded({'version':1,'scope':'private-object-audit-registry',
            'policyId':f.policy['policyId'],'resource':f.policy['resource'],'assignments':[{
                'leaseId':f.trusted['leaseId'],'profileId':f.trusted['profileId'],
                'assignment':pin(f.assignment),'source':pin(f.source_path)}]}))
        self.jobs=ObjectAuditJobs(f.verifier,self.registry,digest(self.registry.read_bytes()),self.root/'eligibility-spool')
        self.addCleanup(self.jobs.close)
        self.context=self.root/'policy/eligibility.json'
        self.policy={'version':1,'scope':'qualified-object-eligibility-v1','policyId':f.policy['policyId'],
            'qualificationPolicySha256':'1'*64,'protectedPolicySha256':f.verifier.policy_sha256,
            'qualityImplementationIdentity':f.policy['qualityImplementationIdentity'],
            'protectedAuthoritySha256':f.policy['protectedAuthority']['sha256'],
            'protectedOriginHandoffSha256':f.policy['protectedOriginHandoffSha256'],
            'sceneInputModel':'synthetic-scene-input','resource':f.policy['resource'],'validFrom':now-10,'validUntil':now+7200}
        self.guards=0
        def guard():self.guards+=1
        self.guard=guard
        self.adapter=self.make_adapter()
        self.request={'version':1,'accountId':'b'*32,'leaseId':f.trusted['leaseId'],'profileId':f.trusted['profileId'],
            'qualificationId':'9'*32,'challenge':'8'*32,'assignmentSha256':digest(f.assignment.read_bytes()),
            'sourceSha256':digest(f.source),'snapshotSha256':'4'*64,'policyId':f.policy['policyId'],
            'policySha256':digest(self.context.read_bytes()),'qualificationPolicySha256':'1'*64}

    def make_adapter(self):
        self.context.write_bytes(encoded(self.policy))
        return LiveObjectProtection(self.jobs,self.context,digest(self.context.read_bytes()),guard=self.guard)

    def test_current_original_protection_and_owned_assignment_produce_fresh_scoped_evidence_without_inference(self):
        f=self.source.fixture
        with patch.object(f.verifier,'run',side_effect=AssertionError('must not run a native command')):
            value=self.adapter.evidence(self.request)
        self.assertEqual(value['scope'],'trusted-live-object-protection-v1')
        self.assertTrue(value['protectedEligible']);self.assertTrue(value['verifiedOnOriginalSourceMachine'])
        self.assertLessEqual(value['expiresAt']-value['issuedAt'],30);self.assertEqual(self.guards,2)
        for key in ('sceneMembershipVerified','coverageVerified','qualificationVerified','serverAuthorization','productionQualified'):
            self.assertFalse(value[key])
        self.assertEqual(value['records'],[{'locationId':r['locationId'],'coverageEvidenceSha256':r['coverageEvidenceSha256']} for r in f.trusted['records']])
        self.assertNotIn(str(self.root),encoded(value).decode());self.assertEqual(f.calls,[])
        with self.jobs.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0],0)

    def test_request_cannot_choose_paths_profile_assignment_policy_or_qualification_context(self):
        for changes in ({'path':'private'},{'approved':True},{'version':True},{'accountId':'bad'},{'leaseId':'0'*32},
                        {'profileId':'0'*64},{'assignmentSha256':'0'*64},{'sourceSha256':'0'*64},
                        {'policySha256':'0'*64},{'qualificationPolicySha256':'0'*64}):
            with self.assertRaises(ObjectEligibilityError):self.adapter.evidence({**self.request,**changes})

    def test_pause_stop_or_independent_activation_guard_refuses_evidence(self):
        self.jobs.stop.set()
        with self.assertRaises(ObjectEligibilityError):self.adapter.evidence(self.request)
        self.jobs.stop.clear()
        for marker in ('PAUSE','STOP'):
            path=self.jobs.work/marker;path.write_text('synthetic pause')
            with self.assertRaises(ObjectEligibilityError):self.adapter.evidence(self.request)
            path.unlink()  # Only this test's temporary marker.
        with patch.object(self.adapter,'guard',side_effect=OSError(str(self.root))):
            with self.assertRaisesRegex(ObjectEligibilityError,'^object_protection_unavailable$'):self.adapter.evidence(self.request)

    def test_revoked_owned_assignment_blocks_even_without_a_native_job(self):
        self.jobs.erase_assignment(self.request['leaseId'])
        with self.assertRaises(ObjectEligibilityError):self.adapter.evidence(self.request)

    def test_changed_original_arrow_database_exporter_or_registry_is_not_relabelled_current(self):
        for path in (self.source.arrow/'0.arrow',self.source.fixture.database,self.source.exporter,self.registry):
            raw=path.read_bytes();path.write_bytes(b'changed')
            with self.assertRaises(ObjectEligibilityError):self.adapter.evidence(self.request)
            path.write_bytes(raw)
            # Restoring bytes cannot restore the original file identity. Each
            # subsequent request must still fail; do not refresh a saved pin.
            with self.assertRaises(ObjectEligibilityError):self.adapter.evidence(self.request)

    def test_origin_expiry_cannot_be_renewed_by_a_fresh_service_challenge(self):
        with patch('community.protected_origin.time.time',return_value=time.time()+3601):
            with self.assertRaises(ObjectEligibilityError):self.adapter.evidence(self.request)

    def test_policy_requires_original_source_authority_and_exact_separate_context(self):
        for changes in ({'scope':'object-batch-parity-v1'},{'protectedPolicySha256':'0'*64},
                        {'protectedAuthoritySha256':'0'*64},{'protectedOriginHandoffSha256':'0'*64},
                        {'qualityImplementationIdentity':'0'*64},{'resource':{}},{'version':True}):
            original=dict(self.policy);self.policy.update(changes)
            with self.assertRaises(Exception):self.make_adapter()
            self.policy=original

    def test_change_during_final_guard_invalidates_protection_before_reply(self):
        def guard():
            self.guards+=1
            if self.guards==2:(self.source.arrow/'0.arrow').write_bytes(b'changed-during-read')
        with patch.object(self.adapter,'guard',side_effect=guard):
            with self.assertRaises(ObjectEligibilityError):self.adapter.evidence(self.request)


if __name__=='__main__':unittest.main()
