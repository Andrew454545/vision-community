"""Offline inventory authority, bounded UI settings and readiness recovery."""
import copy
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer

from community.local_scene_exclusions import reconcile
from community.local_scene_packets import canonical
from community.local_scene_ui import handler_for


def snapshot(ids, catalog):
    return {'success': True, 'result': [{'success': True, 'meta': {'rows_written': 0},
        'results': [{'inventory': json.dumps({'panoramaIds': ids, 'catalog': catalog})}]}]}


class ExclusionTests(unittest.TestCase):
    def test_only_unused_owner_filtered_shards_gain_scoped_authority(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); history = root/'old.txt'; history.write_text('old-pano\n')
            pool = {'contract': 'vision-community-pose-catalog-v1', 'sourceSha256': 's'*64,
                'allocation': {'excludedLocalRows': 25_000_000, 'excludedReservedRows': 5_000_000,
                               'duplicateSourceRows': 0},
                'shards': [{'sha256':'a'*64,'key':'one','rows':100}, {'sha256':'b'*64,'key':'two','rows':100}]}
            catalog = [{'sha256':'a'*64,'key':'one','rowCount':100,'nextRow':8},
                       {'sha256':'b'*64,'key':'two','rowCount':100,'nextRow':0}]
            prod=snapshot(['pending-pano','failed-pano'],catalog)
            stage=snapshot(['staging-pano','pending-pano'],[])
            result = reconcile(pool,prod,stage,history,['b'*64],'2026-10-15T00:00:00Z',root/'out')
            self.assertEqual(result['rows'],4);self.assertEqual(result['quarantinedAdvancedShards'],1)
            self.assertTrue(result['onlineAllocatorMustRemainPaused'])
            for selected in (['a'*64],['c'*64]):
                with self.assertRaisesRegex(ValueError,'unused_source'):
                    reconcile(pool,prod,stage,history,selected,'2026-10-15T00:00:00Z',root/'bad')
            changed=copy.deepcopy(prod);changed['result'][0]['meta']['rows_written']=1
            with self.assertRaisesRegex(ValueError,'metadata_response'):
                reconcile(pool,changed,stage,history,['b'*64],'2026-10-15T00:00:00Z',root/'bad')
            with self.assertRaisesRegex(ValueError,'inventory_incomplete'):
                reconcile(pool,snapshot([],catalog[:1]),stage,history,['b'*64],'2026-10-15T00:00:00Z',root/'bad')


class WindowSettingsTests(unittest.TestCase):
    def test_settings_need_exact_origin_token_and_bounded_named_fields(self):
        from community.tests.test_local_scene_campaign import UnattendedTests
        with tempfile.TemporaryDirectory() as folder:
            app=UnattendedTests().make(Path(folder))
            server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(app,'secret'))
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            origin=f'http://127.0.0.1:{server.server_port}'
            def request(path,body,headers=None):
                conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
                try:
                    conn.request('POST',path,body=body,headers=headers or {})
                    response=conn.getresponse();response.read();return response.status
                finally:conn.close()
            value={'dayPace':'slow','nightPace':'max','dayStart':'07:00','nightStart':'23:00','pauseOnBattery':True}
            headers={'Authorization':'Bearer secret','Origin':origin,'Content-Type':'application/json'}
            try:
                self.assertEqual(request('/api/settings',canonical(value)),403)
                self.assertEqual(request('/api/settings',canonical(value),{**headers,'Origin':'https://other.test'}),403)
                self.assertEqual(request('/api/settings',canonical({**value,'dayStart':'99:99'}),headers),409)
                self.assertEqual(app.settings['dayStart'],'06:00')
                self.assertEqual(request('/api/settings',canonical({**value,'upload':True}),headers),409)
                self.assertEqual(request('/api/settings',canonical(value),headers),200)
                self.assertEqual(json.loads(app.settings_path.read_text())['dayStart'],'07:00')
                with patch('community.local_scene_startup.configure_startup') as startup:
                    self.assertEqual(request('/api/startup',canonical({'enabled':True}),headers),200)
                    startup.assert_called_once_with(app,True)
                    self.assertEqual(request('/api/startup',b'x'*2049,headers),409)
            finally:server.shutdown();server.server_close();thread.join(3)


class ReadinessRecoveryTests(unittest.TestCase):
    def test_reopened_check_keeps_reports_and_exports_without_private_paths(self):
        from community.local_scene_readiness import LocalSceneReadiness
        from community.local_scene_packets import digest
        import zipfile
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); path=root/'check.json';path.write_text('{}')
            setup={'contract':'vision-local-scene-readiness-v1','policies':[{'path':'policy.json','sha256':'a'*64,'threads':1}]}
            with patch('community.local_scene_readiness.load_readiness',return_value=setup):
                app=LocalSceneReadiness(path,root/'data',root/'runtime')
                attempt=app.root/('attempt-'+'a'*24);attempt.mkdir()
                report=attempt/'canary-report.json'
                report.write_bytes(canonical({'status':'FAILED','qualified':False,'error':'/Users/private/path'}))
                app.reports=[{'path':report,'threads':1,'policySha256':'a'*64}];app._save_progress()
                reopened=LocalSceneReadiness(path,root/'data',root/'runtime')
                self.assertTrue(reopened.status()['exportAvailable'])
                result=reopened.export_results()
                with zipfile.ZipFile(result['path']) as archive:
                    self.assertNotIn(b'/Users/private',archive.read('threads-1/canary-report.json'))
                    self.assertEqual(json.loads(archive.read('installation.json'))['installationId'],app.installation_id)

    def test_runtime_cache_rechecks_changed_files_before_reusing_approval(self):
        from community.local_scene_pilot import CheckedRuntime
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);asset=root/'model.onnx';asset.write_bytes(b'original')
            cache=CheckedRuntime()
            with patch('community.local_scene_pilot.files_for_platform',return_value=[{'path':'model.onnx'}]), \
                 patch('community.local_scene_pilot.verify_runtime',return_value=('binary','models',{'checked':True})) as verify:
                self.assertEqual(cache(root),cache(root));self.assertEqual(verify.call_count,1)
                asset.write_bytes(b'changed bytes')
                verify.side_effect=ValueError('pilot_runtime_mismatch')
                with self.assertRaisesRegex(ValueError,'runtime_mismatch'):cache(root)
                self.assertEqual(verify.call_count,2)

    def test_watchdog_owns_and_reaps_its_actual_short_lived_child(self):
        from community.local_scene_supervisor import owned_window
        import subprocess,sys
        result=owned_window([sys.executable,'-I','-c','raise SystemExit(0)'],
                            stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,creationflags=0)
        self.assertEqual(result.returncode,0)


if __name__=='__main__':unittest.main()
