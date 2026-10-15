"""Local packet ownership, durable index recovery and private UI contracts."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer

from community.local_scene_packets import (prepare_catalog, allocate_packet, load_packet, digest,
                                           canonical, validate_packet)
from community.local_scene_pilot import LocalScenePilot
from community.local_scene_ui import handler_for, PAGE, reopen_existing
from community import local_scene_setup
from community.tests.test_vision_index import fake_runner
from community.vision_index import index_locations_tsv


def catalog(root, count=33):
    path = root/'catalog.tsv'
    path.write_text(''.join(f'pilot\t{i}\t10\t20\t123.5\t-2\t1\tpano-{i:04d}\tFrance\tgen2\tunknown\n'
                            for i in range(count)), encoding='utf-8')
    return path


def packet(root, count=33):
    prepare_catalog(catalog(root, count), root/'issuer.sqlite')
    allocate_packet(root/'issuer.sqlite', 'tester-one', count, 'batch-one', root/'packet.json')
    return root/'packet.json'


class PacketsTest(unittest.TestCase):
    def test_parallel_allocations_and_idempotent_delivery_keep_distinct_work(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); registry=root/'issuer.sqlite'
            prepare_catalog(catalog(root, 40), registry)
            def assign(i):
                return allocate_packet(registry, f'user-{i}', 10, f'batch-{i}', root/f'{i}.json')
            with ThreadPoolExecutor(max_workers=4) as pool:
                packets=list(pool.map(assign, range(4)))
            self.assertEqual(len({r['line'].split('\t')[7] for p in packets for r in p['rows']}),40)
            self.assertEqual(assign(0),packets[0])
            with self.assertRaisesRegex(ValueError,'allocation_conflict'):
                allocate_packet(registry,'changed-user',10,'batch-0',root/'changed.json')

    def test_failed_export_retains_reservation_and_original_packet(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); registry=root/'issuer.sqlite'
            prepare_catalog(catalog(root, 2), registry)
            with patch('community.local_scene_packets.export_packet',side_effect=OSError('disk')):
                with self.assertRaises(OSError):
                    allocate_packet(registry,'one',1,'first',root/'first.json')
            second=allocate_packet(registry,'two',1,'second',root/'second.json')
            first=allocate_packet(registry,'one',1,'first',root/'first.json')
            self.assertNotEqual(first['rows'],second['rows'])

    def test_changed_catalog_cannot_reissue_a_panorama(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); registry=root/'issuer.sqlite'; path=catalog(root,3)
            prepare_catalog(path,registry)
            first=allocate_packet(registry,'one',1,'first',root/'one.json')
            path.write_text(path.read_text().replace('France','Spain'))
            prepare_catalog(path,registry)
            second=allocate_packet(registry,'two',1,'second',root/'two.json')
            self.assertNotEqual(first['rows'][0]['line'].split('\t')[7],second['rows'][0]['line'].split('\t')[7])
            self.assertEqual(allocate_packet(registry,'one',1,'first',root/'retry.json'),first)

    def test_metadata_pose_and_source_index_survive_and_edits_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); original=catalog(root,2).read_text().splitlines()
            p=load_packet(packet(root,2))
            self.assertEqual([r['line'] for r in p['rows']],original)
            self.assertEqual([r['sourceIndex'] for r in p['rows']],[0,1])
            p['rows'][0]['line']=p['rows'][0]['line'].replace('123.5','124')
            with self.assertRaisesRegex(ValueError,'invalid_packet_rows'):
                validate_packet(p)

    def test_duplicate_or_bad_pose_catalog_does_not_replace_active_catalog(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); path=catalog(root,2); registry=root/'issuer.sqlite'
            prepare_catalog(path,registry)
            for bad in (path.read_text().splitlines()[0]+'\n'+path.read_text().splitlines()[0],
                        path.read_text().replace('\t10\t','\tnan\t')):
                path.write_text(bad)
                with self.assertRaises(ValueError):prepare_catalog(path,registry)
            self.assertEqual(len(allocate_packet(registry,'one',2,'first',root/'one.json')['rows']),2)

    def test_checksums_do_not_allow_duplicate_source_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            p=load_packet(packet(Path(folder),2))
            p['rows'][1]=p['rows'][0]
            with self.assertRaisesRegex(ValueError,'invalid_packet_rows'):validate_packet(p)

    def test_non_scene_packet_and_path_links_are_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); p=load_packet(packet(root,2)); p['lane']='object'
            with self.assertRaises(ValueError):validate_packet(p)
            (root/'conflict.json').write_text('other')
            with self.assertRaisesRegex(ValueError,'packet_output_conflict'):
                allocate_packet(root/'issuer.sqlite','tester-one',2,'batch-one',root/'conflict.json')


PROFILE={'sha256':'a'*64,'profile':{'synthetic':True}}
def verifier(_root):return Path('synthetic-binary'),Path('synthetic-models'),PROFILE


class PilotTest(unittest.TestCase):
    def make(self,root,count=33,indexer=None):
        def synthetic(tsv,**kwargs):
            kwargs['runner']=fake_runner
            return index_locations_tsv(tsv,**kwargs)
        return LocalScenePilot(packet(root,count),root/'data',root/'runtime',
                               runtime_verifier=verifier,indexer=indexer or synthetic)

    def run_app(self,app):
        with patch('community.background.keep_awake',return_value=nullcontext()), \
             patch('community.contribute.CommunityClient',side_effect=AssertionError('no cloud client')):
            app.start(); app.thread.join(10)
            self.assertFalse(app.thread.is_alive())

    def test_full_local_core_output_is_sealed_without_account_or_credit(self):
        with tempfile.TemporaryDirectory() as folder:
            app=self.make(Path(folder));self.run_app(app)
            self.assertEqual(app.status()['phase'],'complete',app.status())
            report=json.loads((app.root/'result.json').read_text())
            self.assertEqual(report['locations'],33)
            self.assertEqual(len(report['parts']),3)
            self.assertFalse(report['uploaded']);self.assertEqual(report['creditsEarned'],0)
            self.assertEqual(report['qualityStatus'],'LOCAL_PROVISIONAL')

    def test_pause_keeps_first_group_and_resume_does_not_recompute_it(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); calls=[];holder={}
            def indexer(tsv,**kwargs):
                calls.append(tsv)
                kwargs['runner']=fake_runner
                result=index_locations_tsv(tsv,**kwargs)
                if len(calls)==1:holder['app'].pause()
                return result
            app=self.make(root,indexer=indexer);holder['app']=app
            self.run_app(app);self.assertEqual(app.completed,16);self.assertEqual(app.phase,'paused')
            self.run_app(app);self.assertEqual(app.phase,'complete');self.assertEqual(len(calls),3)
            before=len(calls);self.run_app(app);self.assertEqual(len(calls),before)

    def test_changed_saved_record_is_not_adopted_on_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);app=self.make(root,2);self.run_app(app)
            shard=next(app.root.glob('part-*/attempt-*/index/*.i8'));shard.write_bytes(b'changed')
            app2=LocalScenePilot(root/'packet.json',root/'data',root/'runtime',runtime_verifier=verifier)
            self.run_app(app2);self.assertEqual(app2.phase,'error')
            self.assertEqual(shard.read_bytes(),b'changed')

    def test_incomplete_views_never_create_completion_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            def incomplete(tsv,**kwargs):
                kwargs['runner']=fake_runner;result=index_locations_tsv(tsv,**kwargs)
                (kwargs['index_dir']/'shard-000000.mask').write_bytes(b'\x01'*2)
                return result
            app=self.make(Path(folder),2,incomplete);self.run_app(app)
            self.assertEqual(app.phase,'error');self.assertFalse((app.root/'result.json').exists())
            self.assertEqual(len(list(app.root.glob('part-*/complete.json'))),0)

    def test_uncheckpointed_orphan_is_retained_instead_of_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            app=self.make(Path(folder),2)
            orphan=app.root/'part-0000/attempt-0001/index';orphan.mkdir(parents=True)
            (orphan/'orphan.bin').write_bytes(b'kept')
            self.run_app(app);self.assertEqual(app.phase,'complete',app.status())
            self.assertEqual((orphan/'orphan.bin').read_bytes(),b'kept')
            self.assertTrue((app.root/'part-0000/attempt-0002/index').is_dir())

    def test_runtime_change_during_processing_preserves_outputs_but_stops(self):
        with tempfile.TemporaryDirectory() as folder:
            app=self.make(Path(folder),2)
            values=iter([(Path('binary'),Path('models'),PROFILE),
                         (Path('binary'),Path('models'),{'sha256':'b'*64})])
            app.runtime_verifier=lambda _root:next(values)
            self.run_app(app);self.assertEqual(app.phase,'error');self.assertFalse((app.root/'result.json').exists())


class UITest(unittest.TestCase):
    def test_reopen_only_never_starts_another_server_when_window_is_unavailable(self):
        from community.local_scene_ui import main
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=packet(root,2)
            with patch('sys.argv',['pilot','--packet',str(source),'--data-dir',str(root/'data'),'--reopen-only']), \
                 patch('community.local_scene_ui.reopen_existing',return_value=False), \
                 patch('community.local_scene_ui.ThreadingHTTPServer',side_effect=AssertionError('no replacement server')):
                with self.assertRaisesRegex(RuntimeError,'local_pilot_window_unavailable'):main()
    def test_packet_check_exits_before_setup_server_browser_or_processing(self):
        from community.local_scene_ui import main
        import io
        from contextlib import redirect_stdout
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=packet(root,2);output=io.StringIO()
            with patch('sys.argv',['pilot','--packet',str(source),'--check-only']), \
                 patch('community.local_scene_ui.LocalScenePilot',side_effect=AssertionError('no worker')), \
                 patch('community.local_scene_ui.ThreadingHTTPServer',side_effect=AssertionError('no server')), \
                 patch('community.local_scene_ui.webbrowser.open',side_effect=AssertionError('no browser')),redirect_stdout(output):
                main()
            self.assertEqual(json.loads(output.getvalue()),{'ok':True,'locations':2,'localOnly':True})
    def test_actual_loopback_http_requires_secret_host_origin_and_empty_action(self):
        class App:
            calls=[]
            def status(self):return {'phase':'ready'}
            def start(self):self.calls.append('start')
            def pause(self):self.calls.append('pause')
        app=App();server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(app,'secret'))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        origin=f'http://127.0.0.1:{server.server_port}'
        bodies=[]
        def request(method,path,headers=None,body=None):
            conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
            conn.request(method,path,body=body,headers=headers or {})
            response=conn.getresponse();status=response.status;bodies.append(response.read());conn.close();return status
        try:
            self.assertEqual(request('GET','/'),200)
            self.assertNotIn(b'nonce="secret"',bodies[-1])
            self.assertEqual(request('GET','/api/status'),403)
            good={'Authorization':'Bearer secret','Origin':origin}
            self.assertEqual(request('GET','/api/status',good),200)
            self.assertEqual(request('POST','/api/start',{'Authorization':'Bearer secret'}),403)
            self.assertEqual(request('POST','/api/start',{**good,'Origin':'https://example.com'}),403)
            self.assertEqual(request('POST','/api/start',{**good,'Host':'attacker.test'}),403)
            self.assertEqual(request('POST','/api/start',good,'bad'),403)
            self.assertEqual(request('POST','/api/start',good),200)
            self.assertEqual(app.calls,['start'])
            self.assertNotIn('https://',PAGE)
        finally:server.shutdown();server.server_close();thread.join(3)

    def test_reopen_uses_saved_loopback_window_without_starting_another_worker(self):
        class App:
            packet={'packetId':'a'*64}
            def status(self):return {'packetId':self.packet['packetId']}
        with tempfile.TemporaryDirectory() as folder:
            app=App();app.root=Path(folder);token='b'*64
            server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(app,token))
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            url=f'http://127.0.0.1:{server.server_port}/#{token}'
            path=app.root/'window.json';path.write_text(json.dumps({'url':url,'packetId':app.packet['packetId']}))
            try:
                with patch('community.local_scene_ui.webbrowser.open') as opened:
                    self.assertTrue(reopen_existing(app));opened.assert_called_once_with(url)
                path.write_text(json.dumps({'url':'https://example.com/#'+token,'packetId':app.packet['packetId']}))
                with patch('community.local_scene_ui.urllib.request.build_opener',side_effect=AssertionError('no remote URL')):
                    self.assertFalse(reopen_existing(app))
            finally:server.shutdown();server.server_close();thread.join(3)


class SetupTest(unittest.TestCase):
    def manifest(self):
        import hashlib
        return {'files':[{'asset':'mma-vision-test.exe','path':'bin/mma-vision.exe','bytes':6,
             'sha256':hashlib.sha256(b'native').hexdigest(),'executable':True},
             {'asset':'siglip-test.onnx','path':'models/siglip-b16-224-canonical/vision_model_fp32.onnx',
              'bytes':5,'sha256':hashlib.sha256(b'model').hexdigest()}]}

    def test_setup_downloads_only_pinned_scene_models_and_reuses_cached_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);kit=root/'kit/bin';kit.mkdir(parents=True)
            (kit/'mma-vision.exe').write_bytes(b'native'); manifest=root/'manifest.json'
            manifest.write_text(json.dumps(self.manifest()));calls=[]
            def download(url,path,entry):calls.append(url);path.write_bytes(b'model')
            with patch.object(local_scene_setup,'MANIFEST',manifest), \
                 patch.object(local_scene_setup,'runtime_platform',return_value='windows-x86_64'), \
                 patch.object(local_scene_setup,'verify_runtime',return_value=(None,None,PROFILE)):
                local_scene_setup.setup_runtime(root/'kit',root/'dest',download_models=True,downloader=download)
                local_scene_setup.setup_runtime(root/'kit',root/'dest',downloader=lambda *_:self.fail('no repeated download'))
            self.assertEqual(len(calls),1);self.assertIn('/siglip-test.onnx',calls[0])
            self.assertNotIn('object',calls[0])

    def test_wrong_native_kit_stops_before_any_download_or_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);kit=root/'kit/bin';kit.mkdir(parents=True)
            (kit/'mma-vision.exe').write_bytes(b'wrong');manifest=root/'manifest.json'
            manifest.write_text(json.dumps(self.manifest()))
            with patch.object(local_scene_setup,'MANIFEST',manifest), \
                 patch.object(local_scene_setup,'runtime_platform',return_value='windows-x86_64'):
                with self.assertRaisesRegex(ValueError,'pilot_kit_runtime_mismatch'):
                    local_scene_setup.setup_runtime(root/'kit',root/'dest',download_models=True,
                        downloader=lambda *_:self.fail('no download on invalid native'))
            self.assertFalse((root/'dest').exists())

    def test_new_public_sources_are_in_private_snapshot_inventory(self):
        from community.mac_starter import source_inventory
        repo=Path(__file__).resolve().parents[2]
        names=source_inventory(repo)
        for name in ('local_scene_packets.py','local_scene_pilot.py','local_scene_ui.py','local_scene_setup.py',
                     'local_scene_runtime.json'):
            self.assertIn('community/'+name,names)


if __name__=='__main__':unittest.main()
