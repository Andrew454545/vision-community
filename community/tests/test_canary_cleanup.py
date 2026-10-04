"""Synthetic filesystem fixtures; never native inference or production approval."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from calibration.synthetic_canary import create_sealed_inputs, MODELS
from community import pc_canary as canary
from community.desktop import DesktopApp, DesktopError
from community.vision_index import VisionIndexError


class CanaryCleanupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shared = tempfile.TemporaryDirectory()
        cls.shared_root = Path(cls.shared.name)
        cls.fixture = (canary.FIXTURE/'canary-112.tsv').read_bytes()
        cls.reference, cls.identity = canary.canary_reference()
        cls.models = [{'name':name, 'bytes':1, 'sha256':hashlib.sha256(name.encode()).hexdigest()} for name in MODELS]
        cls.rgb = cls.shared_root/'rgb'
        cls.generated = create_sealed_inputs(cls.rgb, cls.fixture, cls.models,
            expected_fixture_sha256=hashlib.sha256(cls.fixture).hexdigest())

    @classmethod
    def tearDownClass(cls): cls.shared.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root/'fixture.tsv').write_bytes(self.fixture)
        (self.root/'reference.i8').write_bytes(self.reference)
        self.document = {'version':3, 'policyId':'filesystem-unit-only-not-a-release',
            'runtimeProfileSha256':'a'*64, **{k:self.identity[k] for k in ('fixtureSha256','referenceSha256')},
            'fullCalibration':{'approved':True, 'locations':1024, 'repetitions':3, 'evidenceSha256':'d'*64},
            'thresholds':{'minimumViewCosine':.9999, 'maximumViewRelativeL2':.02},
            'dataset':{'fixture':{'path':'fixture.tsv','bytes':len(self.fixture),'sha256':self.identity['fixtureSha256']},
                       'reference':{'path':'reference.i8','bytes':len(self.reference),'sha256':self.identity['referenceSha256']},
                       'parentReferenceSha256':self.identity['parentReferenceSha256'],
                       'syntheticInputs':{'generatorVersion':1,'generatorSha256':canary.sha(canary.SYNTHETIC_GENERATOR),
                                          'manifestSha256':self.generated['manifestSha256']}}}
        path = self.root/'unit-policy.json'
        path.write_text(json.dumps(self.document))
        self.policy = canary.CanaryPolicy.load(path, canary.sha(path))
        self.work = self.root/'checks/this-attempt'
        self.work.mkdir(parents=True)
        self.report = {'status':'COMPLETE','complete':True,'qualified':True,
            'policyId':self.document['policyId'],'inputIdentity':'SEALED_SYNTHETIC_RGB_BYTES',
            'reference':'RELEASE_PINNED_SYNTHETIC_REFERENCE','syntheticInputs':self.document['dataset']['syntheticInputs'],
            'runtimeProfile':{'sha256':'a'*64},'identity':self.identity,
            'payloadSha256':hashlib.sha256(self.reference).hexdigest()}
        self.approval = {'qualified':True,'profileId':'a'*64,'expiresAt':time.time()+3600}
        self.save_report()

    def save_report(self):
        (self.work/'canary-report.json').write_text(json.dumps(self.report))

    def inventory(self, *, include_tensor_files=False):
        shutil.copytree(self.rgb, self.work/'synthetic-rgb')
        (self.work/'release-canary-112.tsv').write_bytes(self.fixture)
        (self.work/'checkpoint.json').write_text(json.dumps({'nextLocationIndex':112,'incompleteLocations':0}))
        index = self.work/'index'
        index.mkdir()
        (index/'manifest.json').write_text(json.dumps({'version':4,'indexedLocations':112,'viewsPerLocation':4,
                                                     'bytesPerLocation':3080,'shardLocations':50000}))
        (index/'shard-000000.mask').write_bytes(b'\x0f'*112)
        (index/'shard-000000.i8').write_bytes(self.reference)
        evidence = self.work/'synthetic-evidence'
        evidence.mkdir()
        manifest = json.loads((self.rgb/'manifest.json').read_text())
        shapes = {'pixel-values':[3,224,224], 'normalized':[768], 'pooler-output':[768]}
        data = {'pixel-values':bytes(602112), 'normalized':bytes(3072), 'pooler-output':bytes(3072)}
        tensors = []
        for ordinal in range(112):
            for view in range(4):
                for event, shape in shapes.items():
                    name = f'scene-{ordinal:04}-view-{view}-{event}.f32le'
                    raw = data[event]
                    if include_tensor_files: (evidence/name).write_bytes(raw)
                    tensors.append({'ordinal':ordinal,'view':view,'event':event,'shape':shape,
                        'dtype':'float32-little-endian','file':{'name':name,'bytes':len(raw),
                                                               'sha256':hashlib.sha256(raw).hexdigest()}})
        (evidence/'scene-evidence.json').write_text(json.dumps({'schemaVersion':1,
            'status':'NATIVE_SCENE_STUDY_COMPLETED_UNQUALIFIED','selectedImageGraph':'vision_model_fp32.onnx',
            **{k:manifest[k] for k in ('sourceTsv','modelFiles','frames')},'tensors':tensors}))

    def compact(self):
        return canary.compact_approved_canary(self.work, self.report, self.approval, self.policy)

    def test_full_cleanup_keeps_reports_indexes_logs_small_tensors_and_other_attempts(self):
        self.inventory(include_tensor_files=True)
        (self.work/'native.stderr.log').write_bytes(b'preserve native log')
        other = self.root/'checks/failed-attempt'
        other.mkdir()
        (other/'failed.rgb').write_bytes(b'preserve failed pixels')
        (self.root/'recovery-code.txt').write_bytes(b'private unit recovery')
        retained = {path:canary.sha(self.work/path) for path in ('canary-report.json','checkpoint.json',
            'index/shard-000000.i8','index/shard-000000.mask','native.stderr.log',
            'synthetic-rgb/manifest.json','synthetic-evidence/scene-evidence.json',
            'synthetic-evidence/scene-0000-view-0-normalized.f32le')}
        receipt = self.compact()
        self.assertEqual(receipt['status'],'COMPLETE')
        self.assertEqual(receipt['deletedFiles'],896)
        self.assertEqual(receipt['deletedBytes'],337182720)
        self.assertFalse(list((self.work/'synthetic-rgb').glob('*.rgb')))
        self.assertFalse(list((self.work/'synthetic-evidence').glob('*-pixel-values.f32le')))
        self.assertEqual(len(list((self.work/'synthetic-evidence').glob('*.f32le'))),896)
        self.assertEqual(retained,{path:canary.sha(self.work/path) for path in retained})
        self.assertEqual(json.loads((self.work/'cleanup-receipt.json').read_text()),receipt)
        self.assertEqual((other/'failed.rgb').read_bytes(),b'preserve failed pixels')
        self.assertEqual((self.root/'recovery-code.txt').read_bytes(),b'private unit recovery')
        with self.assertRaisesRegex(ValueError,'already_started'): self.compact()

    def test_missing_rejected_expired_wrong_profile_and_nonfinite_approval_never_delete(self):
        kept = self.work/'preserve.rgb'
        kept.write_bytes(b'private evidence')
        original = self.approval
        for value in (None, {}, {**original,'qualified':False}, {**original,'profileId':'b'*64},
                      {**original,'expiresAt':0}, {**original,'expiresAt':True},
                      {**original,'expiresAt':float('inf')}, {**original,'expiresAt':float('nan')}):
            with self.subTest(value=value):
                self.approval = value
                with self.assertRaisesRegex(ValueError,'approval_required'): self.compact()
                self.assertEqual(kept.read_bytes(),b'private evidence')
        self.assertFalse((self.work/'cleanup-receipt.json').exists())

    def test_failed_or_diagnostic_report_never_deletes(self):
        original = self.report
        for patch_report in ({'status':'FAILED'}, {'complete':False}, {'qualified':False},
                             {'inputIdentity':'SOURCE_PIXELS_NOT_FROZEN'}, {'policyId':'not-release'}):
            self.report = {**original, **patch_report}
            with self.subTest(patch_report=patch_report),self.assertRaisesRegex(ValueError,'approval_required'):
                self.compact()

    def test_legacy_attempt_is_not_scanned_or_cleaned(self):
        self.assertIsNone(canary.compact_approved_canary(self.work, {}, None, None))
        self.assertIsNone(canary.compact_approved_canary(self.work, {}, None, SimpleNamespace(document={'version':2})))

    def test_changed_saved_report_and_preexisting_cleanup_receipt_stop_before_deletion(self):
        (self.work/'canary-report.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'report_changed'): self.compact()
        self.save_report()
        (self.work/'cleanup-receipt.json').write_text('{"status":"PREPARED"}')
        with self.assertRaisesRegex(ValueError,'already_started'): self.compact()

    def test_incomplete_mask_does_not_clear_successful_looking_evidence(self):
        self.inventory()
        (self.work/'index/shard-000000.mask').write_bytes(b'\x0f'*111+b'\0')
        with self.assertRaisesRegex(VisionIndexError,'incomplete_view_mask'): self.compact()
        self.assertEqual(len(list((self.work/'synthetic-rgb').glob('*.rgb'))),448)

    def test_traversal_duplicate_and_wrong_tensor_geometry_stop_before_any_deletion(self):
        self.inventory()
        path = self.work/'synthetic-evidence/scene-evidence.json'
        body = json.loads(path.read_text())
        for mode in ('escape','shape','duplicate'):
            changed = copy.deepcopy(body)
            if mode == 'escape': changed['tensors'][0]['file']['name'] = '../../recovery-code.txt'
            if mode == 'shape': changed['tensors'][0]['shape'] = [602112]
            if mode == 'duplicate': changed['tensors'][-1] = copy.deepcopy(changed['tensors'][0])
            # Duplicate is seen after other transports: create the small/large test files once.
            if mode == 'duplicate':
                for tensor in body['tensors']:
                    target = path.parent/tensor['file']['name']
                    target.write_bytes(bytes(tensor['file']['bytes']))
            path.write_text(json.dumps(changed))
            with self.subTest(mode=mode),self.assertRaisesRegex(ValueError,'inventory'): self.compact()
            self.assertEqual(len(list((self.work/'synthetic-rgb').glob('*.rgb'))),448)
        self.assertFalse((self.work/'cleanup-receipt.json').exists())

    def test_last_preprocessing_checksum_failure_preserves_every_rgb_and_tensor(self):
        self.inventory(include_tensor_files=True)
        path = self.work/'synthetic-evidence/scene-0111-view-3-pixel-values.f32le'
        with path.open('r+b') as stream: stream.write(b'X')
        with self.assertRaisesRegex(ValueError,'file_changed'): self.compact()
        self.assertEqual(len(list((self.work/'synthetic-rgb').glob('*.rgb'))),448)
        self.assertEqual(len(list((self.work/'synthetic-evidence').glob('*.f32le'))),1344)
        self.assertFalse((self.work/'cleanup-receipt.json').exists())

    def test_parent_reparse_or_hardlinked_report_is_never_followed(self):
        original = Path.lstat
        def reparse(path, *args, **kwargs):
            info = original(path,*args,**kwargs)
            if path != self.work.parent: return info
            return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
        with patch.object(Path,'lstat',reparse),self.assertRaisesRegex(ValueError,'unsafe_pc_check_cleanup_path'):
            self.compact()
        linked = self.root/'linked-report.json'
        os.link(self.work/'canary-report.json', linked)
        with self.assertRaisesRegex(ValueError,'unsafe_pc_check_cleanup_path'): self.compact()
        self.assertEqual(linked.read_text(),(self.work/'canary-report.json').read_text())

    def test_delete_failure_has_partial_receipt_and_never_claims_complete(self):
        self.inventory(include_tensor_files=True)
        original = Path.unlink
        blocked = self.work/'synthetic-rgb/scene-0000-view-1.rgb'
        def unlink(path,*args,**kwargs):
            if path == blocked: raise PermissionError('unit fixture busy')
            return original(path,*args,**kwargs)
        with patch.object(Path,'unlink',unlink),self.assertRaises(PermissionError): self.compact()
        receipt = json.loads((self.work/'cleanup-receipt.json').read_text())
        self.assertEqual((receipt['status'],receipt['deletedFiles'],receipt['deletedBytes']),('INTERRUPTED',1,150528))
        self.assertTrue(blocked.is_file())
        self.assertEqual(len(receipt['plannedFiles']),896)
        self.assertEqual(receipt['errorType'],'PermissionError')


class GuidedCleanupTests(unittest.TestCase):
    def check(self, approval, cleanup_error=None):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        report = {'status':'COMPLETE','runtimeProfile':{'sha256':'a'*64},'submission':{}}
        app = DesktopApp(Path(temp.name), canary=lambda *a,**k:report, profile_matches=lambda *a,**k:True)
        calls = []
        def request(*args):
            calls.append('service')
            return 200, approval, None
        app.client = SimpleNamespace(request=request,profile_id=None)
        def cleanup(*args):
            calls.append('cleanup')
            self.assertTrue(app.snapshot()['qualified'])
            if cleanup_error: raise cleanup_error
        with patch.object(app,'capabilities'), patch.object(app,'release_pc_check',return_value='unit policy'), \
             patch('community.desktop.compact_approved_canary',side_effect=cleanup) as compact:
            if approval.get('qualified'):
                app.qualify()
                self.assertEqual(compact.call_args.args[1:], (report,approval,'unit policy'))
            else:
                with self.assertRaisesRegex(DesktopError,'scene_qualification_rejected'): app.qualify()
        return app, calls

    def test_cleanup_runs_only_after_independent_service_acceptance(self):
        app,calls = self.check({'qualified':True,'profileId':'a'*64,'expiresAt':time.time()+3600})
        self.assertEqual(calls,['service','cleanup'])
        self.assertTrue(app.snapshot()['qualified'])
        app,calls = self.check({'qualified':False})
        self.assertEqual(calls,['service'])
        self.assertFalse(app.snapshot()['qualified'])

    def test_cleanup_failure_preserves_approval_and_records_fixed_private_reason(self):
        app,calls = self.check({'qualified':True,'profileId':'a'*64,'expiresAt':time.time()+3600},
                              PermissionError('private account/request text must not appear'))
        self.assertEqual(calls,['service','cleanup'])
        self.assertTrue(app.snapshot()['qualified'])
        self.assertEqual(app.snapshot()['phase'],'ready')
        report = json.loads((app.root/'pc-check-cleanup-failure.json').read_text())
        self.assertEqual(report,{'status':'INCOMPLETE','errorType':'PermissionError',
                                 'code':'pc_check_temporary_cleanup_incomplete'})
        self.assertIn('cleanup report was kept',app.snapshot()['message'])


if __name__ == '__main__': unittest.main()
