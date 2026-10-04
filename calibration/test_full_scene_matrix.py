"""Finite matrix failure and transport guards; no inference or model downloads."""
import hashlib
import json
import os
from pathlib import Path
import shutil
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from calibration import run_full_scene_matrix as matrix
from calibration import test_full_scene_reference_transport as fixtures

class FullSceneMatrixTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.FullReferenceTransportTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root=self.fixture.root

    def args(self):
        return SimpleNamespace(out=self.root/'matrix',archive=self.root/'unused.zip',
            binary=self.root/'unused.exe',models=self.root/'models',bytes=1,sha256='1'*64,
            runtime_profile_sha256='2'*64,sample_working_set=False)

    def native_case(self):
        self.fixture.case()
        reduced=self.fixture.folder
        case=self.root/'native'
        case.mkdir()
        evidence=case/'repeat-evidence'
        evidence.mkdir()
        index=case/'repeat-index'
        index.mkdir()
        body=json.loads(self.fixture.evidence_path.read_text())
        for tensor in body['tensors']:
            name=tensor['file']['name']
            if tensor['event']=='pixel-values':
                raw=b'\0'*602112
                (evidence/name).write_bytes(raw)
                tensor['file']['sha256']=hashlib.sha256(raw).hexdigest()
            else: shutil.copyfile(reduced/name,evidence/name)
        (evidence/'scene-evidence.json').write_text(json.dumps(body))
        for name in ('shard-000000.i8','shard-000000.mask'): shutil.copyfile(reduced/name,index/name)
        (index/'manifest.json').write_text(json.dumps({'version':4,'viewsPerLocation':4,
            'bytesPerLocation':3080,'embeddingDimension':768,'shardLocations':2,'totalLocations':2,
            'indexedLocations':2,'completed':True}))
        for suffix in ('results','checkpoint','search-results'):
            shutil.copyfile(reduced/('repeat-1-'+suffix+'.json'),case/('repeat-'+suffix+'.json'))
        return case

    def verify_native(self,case):
        return matrix.verify_native_case(case,self.fixture.manifest,self.fixture.queries,self.fixture.models,count=2)

    def test_rotated_order_has_three_fresh_cases_per_thread_count(self):
        self.assertEqual(list(matrix.rotated_cases()),[(1,1),(1,2),(1,4),(2,2),(2,4),(2,1),(3,4),(3,1),(3,2)])

    def test_child_environment_keeps_no_saved_tokens_or_ambient_provider_tuning(self):
        with patch.dict(os.environ,{'GH_TOKEN':'do-not-forward','AWS_SECRET_ACCESS_KEY':'do-not-forward',
            'VISION_GPU_MODE':'unexpected','VISION_ORT_THREADS':'100'}):
            env=matrix.thread_environment(self.root/'env',4)
        for name in ('GH_TOKEN','AWS_SECRET_ACCESS_KEY','VISION_GPU_MODE'): self.assertNotIn(name,env)
        for name in ('VISION_ORT_THREADS','RAYON_NUM_THREADS','OMP_NUM_THREADS','ORT_NUM_THREADS'):
            self.assertEqual(env[name],'4')
        self.assertEqual(env['MKL_NUM_THREADS'],'1')
        for threads in (True,0,8,'4'):
            with self.subTest(threads=threads),self.assertRaises(matrix.MatrixError):
                matrix.thread_environment(self.root/'invalid-env',threads)
        self.assertFalse((self.root/'invalid-env').exists())

    def test_runtime_pin_rejection_precedes_profile_execution(self):
        with patch.object(matrix,'pin',return_value={'bytes':1,'sha256':'0'*64}),patch.object(matrix,'runtime_profile') as profile:
            with self.assertRaisesRegex(matrix.MatrixError,'runtime_or_model'): matrix.checked_runtime(self.root/'binary',self.root,'1'*64)
            profile.assert_not_called()
        with patch.object(matrix,'pin') as read:
            with self.assertRaisesRegex(matrix.MatrixError,'independent_windows_profile'): matrix.checked_runtime(self.root/'binary',self.root,'not-a-pin')
            read.assert_not_called()

    def test_wrong_platform_saves_failure_without_archive_or_native_execution(self):
        args=self.args()
        with patch.object(matrix,'windows_platform',return_value=False),patch.object(matrix,'verify_archive') as archive,patch.object(matrix,'native_commands') as native:
            report=matrix.run_matrix(args)
        self.assertEqual(report['code'],'full_matrix_requires_windows')
        self.assertFalse(report['productionQualified'])
        self.assertEqual(report['commands'],[])
        archive.assert_not_called();native.assert_not_called()
        self.assertEqual(json.loads((args.out/'full-windows-matrix-evidence.json').read_text()),report)

    def test_low_disk_never_reads_reference_or_launches_native(self):
        with patch.object(matrix,'windows_platform',return_value=True),patch.object(matrix.shutil,'disk_usage',return_value=SimpleNamespace(free=0)),patch.object(matrix,'verify_archive') as archive:
            report=matrix.run_matrix(self.args())
        self.assertEqual(report['code'],'full_matrix_requires_32_gib_free')
        archive.assert_not_called()

    def test_incomplete_reference_preserves_rejection_without_native_calls(self):
        with patch.object(matrix,'windows_platform',return_value=True),patch.object(matrix.shutil,'disk_usage',return_value=SimpleNamespace(free=matrix.DISK_FLOOR)),patch.object(matrix,'checked_runtime',return_value={}),patch.object(matrix,'verify_archive',return_value={'status':'FAILED','code':'partial_gold'}),patch.object(matrix,'native_commands') as native:
            report=matrix.run_matrix(self.args())
        self.assertEqual(report['code'],'completed_independently_pinned_full_mac_reference_required')
        self.assertEqual(report['referenceVerification']['code'],'partial_gold')
        self.assertEqual(report['commands'],[])
        native.assert_not_called()

    def test_private_output_cannot_overwrite_existing_failure_or_use_public_checkout(self):
        args=self.args()
        args.out.mkdir()
        sentinel=args.out/'existing-failure.json'
        sentinel.write_text('preserve me')
        with self.assertRaises(FileExistsError): matrix.run_matrix(args)
        self.assertEqual(sentinel.read_text(),'preserve me')
        args.out=matrix.ROOT/'never-create-unit-matrix'
        with self.assertRaisesRegex(matrix.MatrixError,'outside_checkout'): matrix.run_matrix(args)
        self.assertFalse(args.out.exists())

    def command(self,run,limit=100,deadline=50):
        entry={}
        with patch.object(matrix.time,'monotonic',return_value=1):
            matrix.finite_command(run,['literal-command'],case=self.root,label='index',threads=2,
                environment={},deadline=deadline,limit=limit,entry=entry,checkpoint=lambda:None,sample_working_set=False)
        return entry

    def test_command_observes_shared_pool_bounded_deadline_and_owned_cleanup(self):
        def run(_argv,**kwargs):
            self.assertEqual(kwargs['timeout'],49)
            self.assertEqual(kwargs['creationflags'],0x08000000)
            self.assertFalse(kwargs['sample_working_set'])
            kwargs['receipt']['completeAfterOwnedCleanup']=True
            kwargs['stderr'].write(b'[vision] ONNX Runtime global threads: 2, spinning disabled\n')
            return SimpleNamespace(returncode=0)
        entry=self.command(run)
        self.assertEqual(entry['status'],'COMPLETE')
        self.assertTrue(entry['sharedPoolObserved'])

    def test_expired_deadline_never_runs_command(self):
        with patch.object(matrix.time,'monotonic',return_value=100),self.assertRaisesRegex(matrix.MatrixError,'overall_time_limit'):
            matrix.finite_command(lambda *_a,**_k:self.fail('must not run'),[],case=self.root,label='index',threads=1,
                environment={},deadline=50,limit=10,entry={},checkpoint=lambda:None,sample_working_set=False)
        self.assertFalse((self.root/'index.stdout.log').exists())

    def test_failed_cleanup_cannot_be_called_completed(self):
        def run(_argv,**kwargs):
            kwargs['receipt']['completeAfterOwnedCleanup']=False
            return SimpleNamespace(returncode=0)
        with self.assertRaisesRegex(matrix.MatrixError,'exit_or_cleanup'): self.command(run)
        self.assertTrue((self.root/'index.stdout.log').is_file())

    def test_missing_or_wrong_pool_cannot_be_called_completed(self):
        def run(_argv,**kwargs):
            kwargs['receipt']['completeAfterOwnedCleanup']=True
            kwargs['stderr'].write(b'[vision] ONNX Runtime global threads: 4, spinning disabled\n')
            return SimpleNamespace(returncode=0)
        with self.assertRaisesRegex(matrix.MatrixError,'shared_pool'): self.command(run)

    def test_exact_native_transport_checks_all_bytes_and_retains_raw_preprocessing(self):
        case=self.native_case()
        checked,hashes,semantic=self.verify_native(case)
        self.assertEqual(checked['pcTensorByteFilesVerified'],24)
        self.assertEqual(checked['pcPreprocessingTransport'],'BYTES_VERIFIED_AND_RETAINED')
        self.assertEqual(len(hashes),24)
        self.assertEqual(len(semantic[0][3]),2)
        self.assertEqual(len(list((case/'repeat-evidence').glob('*pixel-values.f32le'))),8)
        self.assertFalse(list((case/'verified-reduced').glob('*pixel-values.f32le')))

    def test_changed_raw_preprocessing_fails_before_reduced_copy(self):
        case=self.native_case()
        (case/'repeat-evidence/scene-0000-view-0-pixel-values.f32le').write_bytes(b'X'*602112)
        with self.assertRaisesRegex(matrix.MatrixError,'tensor_transport'): self.verify_native(case)
        self.assertFalse((case/'verified-reduced').exists())

    def test_bad_index_manifest_or_input_identity_cannot_pass(self):
        case=self.native_case()
        manifest=case/'repeat-index/manifest.json'
        manifest.write_text('{}')
        with self.assertRaisesRegex(matrix.MatrixError,'manifest_incomplete'): self.verify_native(case)
        self.assertFalse((case/'verified-reduced').exists())
        body=json.loads((case/'repeat-evidence/scene-evidence.json').read_text())
        body['sourceTsv']['sha256']='0'*64
        (case/'repeat-evidence/scene-evidence.json').write_text(json.dumps(body))
        with self.assertRaisesRegex(matrix.MatrixError,'inputs_changed'): self.verify_native(case)

    def test_query_comparison_distinguishes_scores_views_and_rank_inversions(self):
        gold=[('unit','a unit','textOnly',[(0,0,.8),(1,1,.7),(2,2,.6)])]
        actual=[('unit','a unit','textOnly',[(1,3,.8),(0,0,.7),(2,2,.6)])]
        row=matrix.query_comparison(actual,gold)[0]
        self.assertEqual(row['rankInversions'],1)
        self.assertEqual(row['maximumRankDisplacement'],1)
        self.assertEqual(row['selectedViewDifferences'],1)
        self.assertTrue(row['top10SetMatch'])
        self.assertFalse(row['scoreValuesMatch'])
        self.assertAlmostEqual(row['largestReversedAdjacentReferenceScoreGap'],.1)
        self.assertFalse(row['orderedLocationsAndSelectedViewsMatch'])
        with self.assertRaisesRegex(matrix.MatrixError,'query_identity'): matrix.query_comparison(actual,[])
        for order in ([0,0],[False,1],[0.0,1.0],[-1,1]):
            with self.subTest(order=order),self.assertRaises(matrix.MatrixError): matrix.inversion_count(order)

if __name__=='__main__': unittest.main()
