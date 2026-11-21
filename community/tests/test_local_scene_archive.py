"""Local-only backup of synthetic completed native-shaped Scene artifacts."""
from contextlib import nullcontext
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from community.local_scene_archive import export_saved_results, ARTIFACTS
from community.local_scene_packets import canonical
from community.local_scene_pilot import LocalScenePilot
from community.tests.test_local_scene_pilot import packet
from community.tests.test_vision_index import fake_runner
from community.vision_index import index_locations_tsv


PROFILE_BODY = {'synthetic': True, 'threads': 1, 'sceneFp32': True}
PROFILE = {'sha256': hashlib.sha256(canonical(PROFILE_BODY)).hexdigest(), 'profile': PROFILE_BODY}


class ArchiveTest(unittest.TestCase):
    def make(self, root, count=17, pause=False):
        holder = {}
        def indexer(tsv, **kwargs):
            kwargs['runner'] = fake_runner
            result = index_locations_tsv(tsv, **kwargs)
            if pause:
                holder['app'].pause()
            return result
        app = LocalScenePilot(packet(root, count), root/'data', root/'runtime', indexer=indexer,
            runtime_verifier=lambda _root: (Path('synthetic-binary'), Path('synthetic-models'), PROFILE))
        holder['app'] = app
        with patch('community.background.keep_awake', return_value=nullcontext()):
            app.start(); app.thread.join(10)
        self.assertFalse(app.thread.is_alive())
        self.assertEqual(app.phase, 'paused' if pause and count > 16 else 'complete', app.status())
        return app

    def snapshot(self, root):
        return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}

    def test_full_archive_preserves_exact_bytes_and_manifest_without_result_claims(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); app=self.make(root)
            (app.root/'failure-private.json').write_text('private diagnostic')
            (app.root/'secret.txt').write_text('not included')
            before=self.snapshot(app.root)
            with patch('community.local_scene_pilot.verify_runtime', side_effect=AssertionError('no runtime')):
                result=export_saved_results(app.root,root/'backup.zip')
            self.assertEqual((result['locations'],result['total'],result['complete']),(17,17,True))
            body=(root/'backup.zip').read_bytes()
            self.assertEqual(result['bytes'],len(body))
            self.assertEqual(result['sha256'],hashlib.sha256(body).hexdigest())
            with zipfile.ZipFile(root/'backup.zip') as archive:
                manifest=json.loads(archive.read('export-manifest.json'))
                self.assertEqual(set(archive.namelist()),set(manifest['files'])|{'export-manifest.json'})
                self.assertEqual(manifest['qualityStatus'],'LOCAL_PROVISIONAL')
                self.assertFalse(manifest['uploaded']); self.assertEqual(manifest['creditsEarned'],0)
                self.assertTrue(manifest['complete']); self.assertEqual(manifest['locations'],17)
                self.assertEqual(len(archive.namelist()),2+2*(len(ARTIFACTS)+1)+1)
                for name,pin in manifest['files'].items():
                    saved=archive.read(name)
                    self.assertEqual(saved,before[name])
                    self.assertEqual(pin,{'bytes':len(saved),'sha256':hashlib.sha256(saved).hexdigest()})
                self.assertNotIn('result.json',archive.namelist())
                self.assertNotIn('failure-private.json',archive.namelist())
            self.assertEqual(before,self.snapshot(app.root))

    def test_partial_archive_keeps_packet_but_excludes_unfinished_attempts(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); app=self.make(root,pause=True)
            unfinished=app.root/'part-0001/attempt-0001';unfinished.mkdir(parents=True)
            (unfinished/'orphan.i8').write_bytes(b'partial')
            result=export_saved_results(app.root,root/'partial.zip')
            self.assertEqual((result['locations'],result['total'],result['complete']),(16,17,False))
            with zipfile.ZipFile(root/'partial.zip') as archive:
                manifest=json.loads(archive.read('export-manifest.json'))
                self.assertEqual(manifest['parts'],['part-0000'])
                self.assertFalse(manifest['complete'])
                self.assertFalse(any(name.startswith('part-0001/') for name in archive.namelist()))
                self.assertEqual(len(json.loads(archive.read('packet.json'))['rows']),17)
            self.assertEqual((unfinished/'orphan.i8').read_bytes(),b'partial')

    def test_portable_export_rewrites_only_native_paths_and_keeps_vector_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);app=self.make(root,2)
            part=app.root/'part-0000';attempt=part/'attempt-0001'
            receipt=json.loads((part/'complete.json').read_text())
            for name in ('checkpoint.json','index/manifest.json'):
                path=attempt/name;document=json.loads(path.read_text())
                document['sourceTsv']='/Users/private-person/private-map.tsv'
                if name.startswith('index/'):document['modelDir']='C:\\Users\\private-person\\models'
                path.write_bytes(canonical(document))
                body=path.read_bytes();receipt['files'][name]={'bytes':len(body),'sha256':hashlib.sha256(body).hexdigest()}
            (part/'complete.json').write_bytes(canonical(receipt))
            before=self.snapshot(app.root)
            result=export_saved_results(app.root,root/'portable.zip',portable=True)
            with zipfile.ZipFile(result['path']) as archive:
                manifest=json.loads(archive.read('export-manifest.json'))
                self.assertEqual(manifest['contract'],'vision-local-scene-archive-v2')
                self.assertTrue(manifest['resumeFromOriginalsOnly'])
                self.assertEqual(manifest['originalFiles']['part-0000/complete.json']['sha256'],
                                 hashlib.sha256(before['part-0000/complete.json']).hexdigest())
                for name in archive.namelist():
                    self.assertNotIn(b'private-person',archive.read(name))
                for name in ('index/shard-000000.i8','index/shard-000000.mask','locations.tsv'):
                    key='part-0000/attempt-0001/'+name
                    self.assertEqual(archive.read(key),before[key])
            self.assertEqual(before,self.snapshot(app.root))

    def test_identical_saved_work_produces_identical_archive_and_conflicts_refuse(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); app=self.make(root,2)
            first=export_saved_results(app.root,root/'one.zip')
            second=export_saved_results(app.root,root/'two.zip')
            self.assertEqual(first['sha256'],second['sha256'])
            original=(root/'one.zip').read_bytes()
            self.assertEqual(export_saved_results(app.root,root/'one.zip'),first)
            self.assertEqual((root/'one.zip').read_bytes(),original)
            (root/'conflict.zip').write_bytes(b'partial or unrelated archive')
            with self.assertRaisesRegex(ValueError,'archive_destination_exists'):
                export_saved_results(app.root,root/'conflict.zip')
            self.assertEqual((root/'conflict.zip').read_bytes(),b'partial or unrelated archive')
            with self.assertRaisesRegex(ValueError,'archive_destination_inside_work'):
                export_saved_results(app.root,app.root/'backup.zip')

    def test_changed_profile_receipt_artifact_and_missing_file_refuse_without_output(self):
        for target,change in (
                ('runtime-profile.json',lambda body:body.replace(b'"sceneFp32":true',b'"sceneFp32":false')),
                ('part-0000/complete.json',lambda body:body.replace(b'"uploaded":false',b'"uploaded":true')),
                ('part-0000/attempt-0001/index/shard-000000.i8',lambda body:b'changed'),
                ('part-0000/attempt-0001/input.json',lambda body:None)):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as folder:
                root=Path(folder); app=self.make(root,2); path=app.root/target
                changed=change(path.read_bytes())
                if changed is None:path.unlink()
                else:path.write_bytes(changed)
                with self.assertRaises((ValueError,FileNotFoundError)):
                    export_saved_results(app.root,root/'refused.zip')
                self.assertFalse((root/'refused.zip').exists())

    def test_rehashed_incomplete_mask_and_wrong_tsv_still_refuse(self):
        for name,body in (('index/shard-000000.mask',b'\x01\x01'),('locations.tsv',b'wrong\n')):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder:
                root=Path(folder);app=self.make(root,2)
                receipt_path=app.root/'part-0000/complete.json'; receipt=json.loads(receipt_path.read_text())
                (app.root/'part-0000/attempt-0001'/name).write_bytes(body)
                receipt['files'][name]={'bytes':len(body),'sha256':hashlib.sha256(body).hexdigest()}
                receipt_path.write_bytes(canonical(receipt))
                with self.assertRaises(Exception):export_saved_results(app.root,root/'refused.zip')
                self.assertFalse((root/'refused.zip').exists())

    def test_no_completed_work_refuses(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); app=LocalScenePilot(packet(root,2),root/'data',root/'runtime')
            (app.root/'runtime-profile.json').write_bytes(canonical(PROFILE))
            with self.assertRaisesRegex(ValueError,'no_completed_scene_work'):
                export_saved_results(app.root,root/'empty.zip')
            self.assertFalse((root/'empty.zip').exists())

    def test_source_changed_during_archive_is_detected_and_no_destination_is_published(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);app=self.make(root,2)
            original=zipfile.ZipFile.writestr; changed=False
            def write(archive,*args,**kwargs):
                nonlocal changed
                result=original(archive,*args,**kwargs)
                if not changed:
                    changed=True
                    (app.root/'part-0000/complete.json').write_bytes(b'{}')
                return result
            with patch.object(zipfile.ZipFile,'writestr',write):
                with self.assertRaisesRegex(ValueError,'saved_work_changed'):
                    export_saved_results(app.root,root/'refused.zip')
            self.assertFalse((root/'refused.zip').exists())
            self.assertEqual((app.root/'part-0000/complete.json').read_bytes(),b'{}')

    def test_reparse_source_parent_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);app=self.make(root,2)
            original=Path.lstat
            class Linked:
                st_mode=0o040755
                st_file_attributes=0x400
            def lstat(path,*args,**kwargs):
                if path==app.root/'part-0000':return Linked()
                return original(path,*args,**kwargs)
            with patch.object(Path,'lstat',lstat):
                with self.assertRaisesRegex(ValueError,'linked_private_path'):
                    export_saved_results(app.root,root/'refused.zip')
            self.assertFalse((root/'refused.zip').exists())


if __name__=='__main__': unittest.main()
