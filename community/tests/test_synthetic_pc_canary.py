"""Immutable readiness inputs cannot silently fall back to live retrieval."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from calibration import synthetic_canary as generator
from community import pc_canary as canary


class SyntheticPcCanaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shared=tempfile.TemporaryDirectory()
        cls.shared_root=Path(cls.shared.name)
        cls.fixture=(canary.FIXTURE/'canary-112.tsv').read_bytes()
        cls.reference,_=canary.canary_reference()
        cls.models=cls.shared_root/'models'
        cls.models.mkdir()
        cls.model_pins=[]
        assets={}
        for name in generator.MODELS:
            raw=('synthetic unit model '+name).encode()
            (cls.models/name).write_bytes(raw)
            checksum=hashlib.sha256(raw).hexdigest()
            cls.model_pins.append({'name':name,'bytes':len(raw),'sha256':checksum})
            assets['models/'+name]=checksum
        cls.profile={'sha256':'a'*64,'profile':{'assets':assets,'syntheticUnitTest':True}}
        cls.cached_rgb=cls.shared_root/'rgb'
        cls.generated=generator.create_sealed_inputs(cls.cached_rgb,cls.fixture,cls.model_pins,
            expected_fixture_sha256=hashlib.sha256(cls.fixture).hexdigest())

    @classmethod
    def tearDownClass(cls): cls.shared.cleanup()

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        (self.root/'fixture.tsv').write_bytes(self.fixture)
        (self.root/'reference.i8').write_bytes(self.reference)
        self.document={'version':3,'policyId':'synthetic-unit-only-not-a-release',
            'runtimeProfileSha256':'a'*64,'fixtureSha256':hashlib.sha256(self.fixture).hexdigest(),
            'referenceSha256':hashlib.sha256(self.reference).hexdigest(),
            'fullCalibration':{'approved':True,'locations':1024,'repetitions':3,'evidenceSha256':'d'*64},
            'thresholds':{'minimumViewCosine':.9999,'maximumViewRelativeL2':.02},
            'dataset':{'fixture':{'path':'fixture.tsv','bytes':len(self.fixture),'sha256':hashlib.sha256(self.fixture).hexdigest()},
                'reference':{'path':'reference.i8','bytes':len(self.reference),'sha256':hashlib.sha256(self.reference).hexdigest()},
                'parentReferenceSha256':'f'*64,'syntheticInputs':{'generatorVersion':1,
                    'generatorSha256':canary.sha(canary.SYNTHETIC_GENERATOR),'manifestSha256':self.generated['manifestSha256']}}}

    def load(self):
        path=self.root/'policy.json'
        path.write_text(json.dumps(self.document))
        return canary.CanaryPolicy.load(path,canary.sha(path))

    def check(self,change=None,prepare=None):
        calls=[]
        def cached_create(root,fixture,pins,**kwargs):
            self.assertEqual(fixture,self.fixture)
            self.assertEqual(pins,self.model_pins)
            shutil.copytree(self.cached_rgb,root)
            return dict(self.generated)
        def indexer(source,**kwargs):
            calls.append(kwargs)
            self.assertEqual(source.read_bytes(),self.fixture)
            self.assertEqual(kwargs['sealed_sha256'],self.generated['manifestSha256'])
            self.assertEqual(kwargs['sealed_rgb'],self.root/'attempt/synthetic-rgb')
            kwargs['index_dir'].mkdir()
            (kwargs['index_dir']/'shard-000000.i8').write_bytes(self.reference)
            if change: change(source,kwargs['sealed_rgb'])
        with patch.object(canary,'runtime_profile',return_value=self.profile),patch.object(canary,'require_complete_index'), \
             patch.object(generator,'create_sealed_inputs',side_effect=prepare or cached_create):
            report=canary.run_canary(self.root/'attempt',binary=Path('unit-test'),model_dir=self.models,
                policy=self.load(),indexer=indexer)
        return report,calls

    def test_complete_fixed_check_has_explicit_pixels_and_no_server_authority(self):
        report,calls=self.check()
        self.assertEqual(report['status'],'COMPLETE')
        self.assertTrue(report['qualified'])
        self.assertFalse(report['serverAuthorization'])
        self.assertEqual(report['inputIdentity'],'SEALED_SYNTHETIC_RGB_BYTES')
        self.assertEqual(report['reference'],'RELEASE_PINNED_SYNTHETIC_REFERENCE')
        self.assertEqual(len(calls),1)
        self.assertEqual(len(report['submission']['canary']['records']),112)

    def test_changed_rgb_during_processing_cannot_leave_packet_or_approval(self):
        def change(source,rgb):
            path=rgb/'scene-0000-view-0.rgb'
            data=path.read_bytes()
            path.write_bytes(bytes([data[0]^1])+data[1:])
        report,_=self.check(change)
        self.assertEqual(report['status'],'FAILED')
        self.assertFalse(report['complete'])
        self.assertFalse(report['qualified'])
        self.assertNotIn('submission',report)
        self.assertEqual(report['error'],'synthetic_canary_rgb_changed_during_check')

    def test_changed_manifest_or_extra_input_is_not_hidden(self):
        report,_=self.check(lambda source,rgb:(rgb/'unexpected.rgb').write_bytes(b'not accepted'))
        self.assertEqual(report['status'],'FAILED')
        self.assertNotIn('submission',report)
        self.assertEqual(report['error'],'invalid_synthetic_canary_inventory')

    def test_wrong_generated_manifest_stops_before_native_work(self):
        report,calls=self.check(prepare=lambda *a,**k:{**self.generated,'manifestSha256':'0'*64})
        self.assertEqual(report['status'],'FAILED')
        self.assertEqual(calls,[])
        self.assertEqual(report['error'],'synthetic_canary_manifest_not_pinned')

    def test_changed_generator_and_invalid_generation_metadata_are_rejected(self):
        self.document['dataset']['syntheticInputs']['generatorSha256']='0'*64
        with self.assertRaisesRegex(ValueError,'generator_not_pinned'): self.load().pinned_inputs()
        for key,value in (('generatorVersion',True),('generatorVersion',2),('generatorSha256','not-a-pin'),('manifestSha256','not-a-pin')):
            doc=copy.deepcopy(self.document)
            doc['dataset']['syntheticInputs'][key]=value
            with self.subTest(key=key,value=value),self.assertRaisesRegex(ValueError,'invalid_synthetic_canary_policy'):
                canary.CanaryPolicy(doc)

    def test_full_runtime_qualification_cannot_be_replaced_by_synthetic_success(self):
        self.document['fullCalibration']['approved']=False
        with self.assertRaisesRegex(ValueError,'full_runtime_qualification_required'): self.load()

    def test_actual_native_command_is_fixed_bounded_and_uses_owned_runner(self):
        work=self.root/'native'
        work.mkdir()
        output=work/'output.json'
        output.write_text(json.dumps({'completed':True,'nextLocationIndex':112,'totalLocations':112,
                                     'fetchErrors':0,'inferenceErrors':0,'incompleteLocations':0}))
        self.native_witness(work)
        events=[]
        with patch.object(canary,'default_runner',return_value=(0,'','[vision] ONNX Runtime global threads: 2, spinning disabled')) as run:
            canary.index_synthetic_canary(self.root/'fixture.tsv',index_dir=work/'index',checkpoint=work/'checkpoint.json',
                output=output,binary=Path('binary'),model_dir=self.models,inference_threads=2,run_id='unit-test',
                sealed_rgb=self.cached_rgb,sealed_sha256=self.generated['manifestSha256'],progress_callback=events.append)
        argv,env,cwd=run.call_args.args
        self.assertEqual(argv[1],'study-four-views')
        self.assertIn('--sealed-rgb',argv)
        self.assertNotIn('--capture-rgb',argv)
        self.assertEqual(argv[argv.index('--evidence-budget-mib')+1],'384')
        self.assertEqual(env['VISION_ORT_THREADS'],'2')
        self.assertEqual(cwd,work)
        self.assertEqual((events[0]['completedLocations'],events[-1]['completedLocations']),(0,112))

    def test_native_error_or_incomplete_result_is_never_called_a_complete_check(self):
        work=self.root/'native'
        work.mkdir()
        output=work/'output.json'
        output.write_text(json.dumps({'completed':True,'nextLocationIndex':112,'totalLocations':112,
                                     'fetchErrors':0,'inferenceErrors':1,'incompleteLocations':0}))
        self.native_witness(work)
        args=dict(index_dir=work/'index',checkpoint=work/'checkpoint.json',output=output,binary=Path('binary'),
                  model_dir=self.models,inference_threads=1,run_id='unit-test',sealed_rgb=self.cached_rgb,sealed_sha256='a'*64)
        for code,error in ((1,'native_failed'),(0,'incomplete')):
            with patch.object(canary,'default_runner',return_value=(code,'','[vision] ONNX Runtime global threads: 1, spinning disabled')):
                with self.assertRaisesRegex(ValueError,error): canary.index_synthetic_canary(self.root/'fixture.tsv',**args)

    def native_witness(self,work):
        path=work/'synthetic-evidence'
        path.mkdir()
        shapes={'pixel-values':[3,224,224],'pooler-output':[768],'normalized':[768]}
        frames=json.loads((self.cached_rgb/'manifest.json').read_text())['frames']
        body={'schemaVersion':1,'status':'NATIVE_SCENE_STUDY_COMPLETED_UNQUALIFIED','selectedImageGraph':'vision_model_fp32.onnx',
            'modelFiles':self.model_pins,'sourceTsv':{'name':'locations.tsv','bytes':len(self.fixture),'sha256':hashlib.sha256(self.fixture).hexdigest()},
            'frames':frames,'tensors':[{'ordinal':i,'view':v,'event':event,'shape':shape,'dtype':'float32-little-endian'}
                                      for i in range(112) for v in range(4) for event,shape in shapes.items()]}
        (path/'scene-evidence.json').write_text(json.dumps(body))

    def test_native_witness_rejects_wrong_pool_graph_models_and_missing_view(self):
        work=self.root/'native'
        work.mkdir()
        self.native_witness(work)
        path=work/'synthetic-evidence/scene-evidence.json'
        body=json.loads(path.read_text())
        variants=[('graph',{**body,'selectedImageGraph':'vision_model.onnx'},1),
                  ('models',{**body,'modelFiles':[]},1),('frames',{**body,'frames':body['frames'][:-1]},1),
                  ('duplicate',{**body,'tensors':body['tensors'][:-1]+[body['tensors'][0]]},1),('pool',body,4)]
        args=dict(index_dir=work/'index',checkpoint=work/'checkpoint.json',output=work/'output.json',binary=Path('binary'),
                  model_dir=self.models,inference_threads=1,run_id='unit-test',sealed_rgb=self.cached_rgb,sealed_sha256='a'*64)
        for name,changed,pool in variants:
            path.write_text(json.dumps(changed))
            with self.subTest(name=name),patch.object(canary,'default_runner',return_value=(0,'',f'[vision] ONNX Runtime global threads: {pool}, spinning disabled')):
                with self.assertRaisesRegex(ValueError,'native_witness_invalid'):
                    canary.index_synthetic_canary(self.root/'fixture.tsv',**args)

    def test_fixed_check_cli_needs_no_consent_for_live_imagery_it_does_not_fetch(self):
        self.load()
        policy_path=self.root/'policy.json'
        argv=['pc-check','--root',str(self.root/'attempt'),'--binary','unit-test','--model-dir',str(self.models),
              '--policy',str(policy_path),'--policy-sha256',canary.sha(policy_path)]
        with patch.object(sys,'argv',argv),patch.object(canary,'run_canary',return_value={'status':'COMPLETE','qualified':False}) as run:
            self.assertEqual(canary.main(),0)
        self.assertEqual(run.call_args.kwargs['policy'].document['version'],3)


if __name__=='__main__': unittest.main()
