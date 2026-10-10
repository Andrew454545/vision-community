import json
import unittest
from unittest.mock import patch

from community import community_scene_source as source
from community.search_snapshot import digest, encoded
from community.tests import test_scene_publication_snapshot as fixtures


class CommunitySceneSourceTests(unittest.TestCase):
    def setUp(self):
        self.h=fixtures.PublicationSnapshotTests();self.h.setUp();self.addCleanup(self.h.doCleanups)
        self.tsv=self.h.root/'original.tsv'
        self.line=b'original-map\toriginal-location\t1\t2\t90\t0\t0\tsynthetic-pano\tItaly\tgen4\tno road name\r\n'
        self.tsv.write_bytes(self.line)

    def export(self,name='export',pin=None):
        args=[]
        for name_part in ('inventory','control','authority'):
            path=self.h.root/(name_part+'.json');raw=encoded(getattr(self.h,name_part));path.write_bytes(raw)
            args.extend([path,digest(raw)])
        return source.export_community_scene_source(*args,self.h.cache,self.tsv,
            pin or digest(self.tsv.read_bytes()),self.h.root/name,environment='staging')

    def test_audited_earned_publication_exports_original_native_row_bytes_and_explicit_non_mma_authority(self):
        report=self.export();catalog=json.loads((self.h.root/'export/community-scene-catalog.private.json').read_bytes())
        self.assertEqual((self.h.root/'export/scene-source.tsv').read_bytes(),self.line)
        self.assertEqual(catalog['mapping'],[{'sourceId':'original-map','sourceLocationId':'original-location',
            'originalSourceRow':0,'communityLocationId':1,'outputSha256':digest(self.h.blob)}])
        self.assertEqual(report['catalogSha256'],digest((self.h.root/'export/community-scene-catalog.private.json').read_bytes()))
        self.assertFalse(report['ownerMmaMembershipAsserted']);self.assertFalse(report['objectImportApproved'])
        self.assertFalse(catalog['officialCoverageVerified']);self.assertFalse(catalog['protectedAuthorityVerified'])
        self.assertFalse(catalog['objectQualityVerified']);self.assertEqual(report['newCreditGranted'],0)
        for file in ('receipt.json','community-scene-catalog.private.json'):
            self.assertNotIn(self.h.owner,(self.h.root/'export'/file).read_text())

    def test_unprocessed_original_rows_are_not_exported(self):
        extra=self.line.replace(b'original-location',b'unprocessed').replace(b'synthetic-pano',b'unprocessed-pano')
        self.tsv.write_bytes(extra+self.line);self.export()
        self.assertEqual((self.h.root/'export/scene-source.tsv').read_bytes(),self.line)
        catalog=json.loads((self.h.root/'export/community-scene-catalog.private.json').read_bytes())
        self.assertEqual(catalog['mapping'][0]['originalSourceRow'],1)

    def test_authentic_community_road_dialect_is_preserved_and_explicit_not_silently_rewritten(self):
        original=self.line.replace(b'no road name',b'no-road');self.tsv.write_bytes(original)
        report=self.export()
        self.assertEqual((self.h.root/'export/scene-source.tsv').read_bytes(),original)
        self.assertEqual(report['sourceDialect'],'community-hyphen-road-labels-v1')
        self.assertFalse(report['objectImportApproved'])

    def test_mixed_road_dialects_are_not_reinterpreted_as_one_native_source(self):
        extra=self.line.replace(b'original-location',b'unprocessed').replace(b'synthetic-pano',b'unprocessed-pano')
        self.tsv.write_bytes(extra+self.line.replace(b'no road name',b'no-road'))
        with self.assertRaises(source.CommunitySceneSourceError):self.export()

    def test_changed_exact_pose_pano_country_generation_and_signed_zero_cannot_claim_scene_completion(self):
        for i,(old,new) in enumerate([(b'\t1\t2\t',b'\t1.0000000000000002\t2\t'),
                (b'\t90\t0\t0\t',b'\t90\t-0\t0\t'),(b'synthetic-pano',b'other-pano'),
                (b'Italy',b'France'),(b'gen4',b'gen3')]):
            self.tsv.write_bytes(self.line.replace(old,new))
            with self.subTest(change=i),self.assertRaises(source.CommunitySceneSourceError):self.export(str(i))

    def test_ambiguous_original_row_cannot_be_picked_arbitrarily(self):
        self.tsv.write_bytes(self.line+self.line.replace(b'original-location',b'another-location'))
        with self.assertRaises(source.CommunitySceneSourceError):self.export()

    def test_duplicate_native_identity_and_malformed_native_row_are_refused(self):
        for i,raw in enumerate([self.line+self.line.replace(b'synthetic-pano',b'another-pano'),
                self.line[:-2],self.line.replace(b'\r\n',b'\r\r\n'),self.line.replace(b'\t1\t2\t',b'\tnan\t2\t'),
                self.line.replace(b'no road name',b'unknown'),self.line.replace(b'\t1\t2\t',b'\t1\x00\t2\t')]):
            self.tsv.write_bytes(raw)
            with self.subTest(change=i),self.assertRaises(ValueError):self.export(str(i))

    def test_client_checksum_without_real_earned_credit_cannot_supply_scene_authority(self):
        self.h.control['ledger'][0]['reason']='fixture_funding'
        with self.assertRaises(ValueError):self.export()
        failure=json.loads((self.h.root/'export/failure-report.json').read_bytes())
        self.assertFalse(failure['objectImportApproved'])
        self.assertFalse((self.h.root/'export/community-scene-catalog.private.json').exists())

    def test_wrong_pin_preserves_redacted_failure_and_original_source(self):
        with self.assertRaises(ValueError):self.export(pin='0'*64)
        self.assertEqual(self.tsv.read_bytes(),self.line)
        self.assertFalse((self.h.root/'export/receipt.json').exists())
        self.assertNotIn(self.h.owner,(self.h.root/'export/failure-report.json').read_text())

    def test_source_changed_during_publication_seal_cannot_be_exported(self):
        original=source.seal_publications
        def changed(*args,**kwargs):
            result=original(*args,**kwargs);self.tsv.write_bytes(self.line+b'changed');return result
        with patch.object(source,'seal_publications',side_effect=changed),self.assertRaises(ValueError):self.export()
        self.assertFalse((self.h.root/'export/receipt.json').exists())
        self.assertFalse((self.h.root/'export/community-scene-catalog.private.json').exists())

    def test_existing_output_and_its_original_evidence_cannot_be_overwritten(self):
        self.export();original=(self.h.root/'export/receipt.json').read_bytes()
        with self.assertRaises(FileExistsError):self.export()
        self.assertEqual((self.h.root/'export/receipt.json').read_bytes(),original)
