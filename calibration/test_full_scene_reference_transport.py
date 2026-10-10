"""Small transport fixtures only: no model/native execution or runtime approval."""
import copy
import hashlib
import json
from pathlib import Path
import stat
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from calibration import verify_full_scene_reference as verifier
from calibration.synthetic_canary import create_sealed_inputs, MODELS
from community.pc_canary import canary_reference, FIXTURE


class FullReferenceTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def archive(self, entries):
        path = self.root/'unit-reference.zip'
        with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            for name,raw in entries: archive.writestr(name,raw)
        return path, verifier.pin(path)

    def case(self):
        self.source = self.root/'locations.tsv'
        fixture = b'\n'.join((FIXTURE/'canary-112.tsv').read_bytes().splitlines()[:2])+b'\n'
        self.source.write_bytes(fixture)
        self.models = [{'name':name,'bytes':1,'sha256':hashlib.sha256(name.encode()).hexdigest()} for name in MODELS]
        self.rgb = self.root/'rgb'
        create_sealed_inputs(self.rgb,fixture,self.models,expected_fixture_sha256=hashlib.sha256(fixture).hexdigest())
        self.manifest = json.loads((self.rgb/'manifest.json').read_text())
        self.folder = self.root/'case'
        self.folder.mkdir()
        self.label = 'repeat-1'
        self.queries = [{'name':'unit','query':'a unit reference','mode':'textOnly'}]
        evidence = {'schemaVersion':1,'status':'NATIVE_SCENE_STUDY_COMPLETED_UNQUALIFIED','productionQualified':False,
            'selectedImageGraph':'vision_model_fp32.onnx',
            **{k:self.manifest[k] for k in ('modelFiles','sourceTsv','frames')},'tensors':[]}
        for ordinal in range(2):
            for view in range(4):
                for event,shape in verifier.SHAPES.items():
                    name = f'scene-{ordinal:04}-view-{view}-{event}.f32le'
                    raw = struct.pack('<768f',1.0,*([0.0]*767))
                    entry = {'name':name,'bytes':len(raw) if event!='pixel-values' else 602112,
                             'sha256':hashlib.sha256(raw).hexdigest()}
                    if event!='pixel-values': (self.folder/name).write_bytes(raw)
                    evidence['tensors'].append({'ordinal':ordinal,'view':view,'event':event,'shape':shape,
                        'dtype':'float32-little-endian','file':entry})
        self.evidence_path = self.folder/'scene-evidence.json'
        self.evidence_path.write_text(json.dumps(evidence))
        blob,_ = canary_reference()
        (self.folder/'shard-000000.i8').write_bytes(blob[:2*3080])
        (self.folder/'shard-000000.mask').write_bytes(b'\x0f'*2)
        for suffix in ('results','checkpoint'):
            (self.folder/(self.label+'-'+suffix+'.json')).write_text(json.dumps({'completed':True,'totalLocations':2,
                'nextLocationIndex':2,'fetchErrors':0,'inferenceErrors':0,'incompleteLocations':0}))
        self.search_path = self.folder/(self.label+'-search-results.json')
        self.search_path.write_text(json.dumps({'queries':[{**self.queries[0],'hits':[
            {'locationIndex':0,'viewOffset':0,'similarity':.5},{'locationIndex':1,'viewOffset':3,'similarity':.25}]}]}))

    def verify_case(self):
        return verifier.verify_reduced_case(self.folder,self.label,2,self.queries,self.models,manifest=self.manifest)

    def test_complete_reduced_case_verifies_transports_and_marks_preprocessing_hash_only(self):
        self.case()
        summary,hashes,queries = self.verify_case()
        self.assertEqual((summary['frames'],summary['tensorEvents'],summary['normalizedAndPoolerTransportsVerified']), (8,24,16))
        self.assertEqual(summary['preprocessedHashesOnly'],8)
        self.assertEqual(len(hashes),24)
        self.assertEqual(len(queries[0][3]),2)
        self.assertFalse(list(self.folder.glob('*pixel-values.f32le')))

    def test_exact_rgb_pose_inventory_rejects_modified_or_missing_inputs(self):
        self.case()
        verifier.verify_rgb(self.rgb,self.source,self.models,count=2)
        target = self.rgb/'scene-0001-view-3.rgb'
        target.write_bytes(b'X'*150528)
        with self.assertRaisesRegex(verifier.ReferenceError,'transport_or_pose'): verifier.verify_rgb(self.rgb,self.source,self.models,count=2)
        target.unlink()
        with self.assertRaises(FileNotFoundError): verifier.verify_rgb(self.rgb,self.source,self.models,count=2)

    def test_tensor_escape_duplicate_wrong_shape_and_wrong_native_graph_are_rejected(self):
        self.case()
        body = json.loads(self.evidence_path.read_text())
        for mode in ('escape','duplicate','shape','graph','bool-frame','bool-tensor','source','models'):
            changed = copy.deepcopy(body)
            if mode=='escape': changed['tensors'][0]['file']['name']='../../account.json'
            if mode=='duplicate': changed['tensors'][-1]=copy.deepcopy(changed['tensors'][0])
            if mode=='shape': changed['tensors'][0]['shape']=[602112]
            if mode=='graph': changed['selectedImageGraph']='vision_model.onnx'
            if mode=='bool-frame': changed['frames'][0]['ordinal']=False
            if mode=='bool-tensor': changed['tensors'][0]['ordinal']=False
            if mode=='source': changed['sourceTsv']['sha256']='0'*64
            if mode=='models': changed['modelFiles']=[]
            self.evidence_path.write_text(json.dumps(changed))
            with self.subTest(mode=mode),self.assertRaises(verifier.ReferenceError): self.verify_case()

    def test_changed_nonfinite_zero_or_unnormalized_vector_cannot_pass_transport_checks(self):
        self.case()
        body = json.loads(self.evidence_path.read_text())
        tensor = next(t for t in body['tensors'] if t['event']=='normalized')
        path = self.folder/tensor['file']['name']
        path.write_bytes(b'X'*3072)
        with self.assertRaisesRegex(verifier.ReferenceError,'tensor_transport'): self.verify_case()
        for value in (float('nan'),0.0,2.0):
            raw = struct.pack('<768f',value,*([0.0]*767))
            path.write_bytes(raw)
            tensor['file']['sha256']=hashlib.sha256(raw).hexdigest()
            self.evidence_path.write_text(json.dumps(body))
            with self.subTest(value=value),self.assertRaisesRegex(verifier.ReferenceError,'float_vector'): self.verify_case()

    def test_incomplete_mask_or_native_checkpoint_is_rejected(self):
        self.case()
        mask = self.folder/'shard-000000.mask'
        mask.write_bytes(b'\x0f\0')
        with self.assertRaisesRegex(verifier.ReferenceError,'index_incomplete'): self.verify_case()
        mask.write_bytes(b'\x0f\x0f')
        checkpoint = self.folder/(self.label+'-checkpoint.json')
        checkpoint.write_text('{}')
        with self.assertRaisesRegex(verifier.ReferenceError,'native_case_incomplete'): self.verify_case()

    def test_duplicate_missing_unsorted_nonfinite_or_wrong_view_search_hit_is_rejected(self):
        self.case()
        body = json.loads(self.search_path.read_text())
        for mode in ('duplicate','missing','unsorted','nonfinite','view','identity'):
            changed = copy.deepcopy(body)
            hits = changed['queries'][0]['hits']
            if mode=='duplicate': hits[1]['locationIndex']=0
            if mode=='missing': hits.pop()
            if mode=='unsorted': hits.reverse()
            if mode=='nonfinite': hits[0]['similarity']=float('nan')
            if mode=='view': hits[0]['viewOffset']=4
            if mode=='identity': changed['queries'][0]['mode']='contrastive50'
            self.search_path.write_text(json.dumps(changed))
            with self.subTest(mode=mode),self.assertRaisesRegex(verifier.ReferenceError,'query_geometry'): self.verify_case()

    def test_raw_preprocessing_or_unknown_extra_case_file_is_not_silently_ignored(self):
        self.case()
        for name in ('scene-0000-view-0-pixel-values.f32le','unexpected.py'):
            path = self.folder/name
            path.write_bytes(b'not part of the reduced transport')
            with self.subTest(name=name),self.assertRaisesRegex(verifier.ReferenceError,'inventory'): self.verify_case()
            path.unlink()

    def test_archive_pin_and_windows_unsafe_paths_links_and_case_collision_reject_before_extracting(self):
        bad = ('../account.json','/locations.tsv','frozen-rgb/../account.json','frozen-rgb\\escape.rgb',
               'C:/account.json','aux','native-logs/unknown-command.log','repeat-1/scene-0000-view-0-pixel-values.f32le')
        for index,name in enumerate(bad):
            archive,expected = self.archive([(name,b'private unit fixture')])
            with self.subTest(name=name),self.assertRaisesRegex(verifier.ReferenceError,'archive_entry'):
                verifier.extract_pinned(archive,expected,self.root/f'out-{index}')
            self.assertFalse((self.root/f'out-{index}').exists())
        link = zipfile.ZipInfo('locations.tsv')
        link.create_system=3
        link.external_attr=(stat.S_IFLNK|0o777)<<16
        archive,expected = self.archive([(link,b'../account.json')])
        with self.assertRaisesRegex(verifier.ReferenceError,'archive_entry'):
            verifier.extract_pinned(archive,expected,self.root/'link')
        archive,expected = self.archive([('locations.tsv',b'unit'),('LOCATIONS.tsv',b'unit')])
        with self.assertRaisesRegex(verifier.ReferenceError,'archive_entry'):
            verifier.extract_pinned(archive,expected,self.root/'collision')
        with self.assertRaisesRegex(verifier.ReferenceError,'archive_pin'):
            verifier.extract_pinned(archive,{**expected,'sha256':'0'*64},self.root/'wrong-pin')

    def test_archive_entry_count_json_size_and_total_inflation_are_bounded(self):
        archive,expected = self.archive([('locations.tsv',b'unit')])
        with patch.object(verifier,'MAX_ENTRIES',0),self.assertRaisesRegex(verifier.ReferenceError,'archive_size'):
            verifier.extract_pinned(archive,expected,self.root/'entries')
        with patch.object(verifier,'MAX_JSON',3),self.assertRaisesRegex(verifier.ReferenceError,'archive_entry'):
            verifier.extract_pinned(archive,expected,self.root/'file-size')
        archive,expected = self.archive([('locations.tsv',b'X'*2048)])
        self.assertLess(expected['bytes'],1024)
        with patch.object(verifier,'MAX_ARCHIVE_BYTES',1024),self.assertRaisesRegex(verifier.ReferenceError,'archive_size'):
            verifier.extract_pinned(archive,expected,self.root/'inflation')

    def test_failed_transport_preserves_fixed_report_and_never_qualifies_or_runs_native(self):
        archive,expected = self.archive([('locations.tsv',b'unit')])
        out = self.root/'verification'
        report = verifier.verify_archive(archive,{**expected,'sha256':'0'*64},out)
        self.assertEqual(report['status'],'FAILED')
        self.assertEqual(report['code'],'reference_archive_pin_mismatch')
        self.assertEqual((report['nativeCommands'],report['accountsCreated'],report['creditsChanged']),(0,0,0))
        self.assertFalse(report['productionQualified'])
        self.assertEqual(json.loads((out/'verification-receipt.json').read_text()),report)
        with self.assertRaises(FileExistsError): verifier.verify_archive(archive,expected,out)

    def test_low_disk_cannot_begin_archive_extraction(self):
        archive,expected = self.archive([('locations.tsv',b'unit')])
        target = self.root/'low-disk'
        with patch.object(verifier.shutil,'disk_usage',return_value=SimpleNamespace(free=0)), \
             self.assertRaisesRegex(verifier.ReferenceError,'extraction_storage_required'):
            verifier.extract_pinned(archive,expected,target)
        self.assertFalse(target.exists())

    def test_partial_mac_receipt_cannot_be_reported_as_a_completed_full_reference(self):
        (self.root/'full-reference-evidence.json').write_text(json.dumps({'status':'FAILED','phase':'capture'}))
        with self.assertRaisesRegex(verifier.ReferenceError,'not_complete'): verifier.verify_full_reference(self.root)


if __name__=='__main__': unittest.main()
