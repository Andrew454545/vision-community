"""Two focused delivery checks; no models, providers or cloud."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from community.local_scene_campaign import allocate_campaign, export_campaign_zip
from community.local_scene_intake import read_check_zip
from community.local_scene_packets import prepare_catalog, canonical, connection
from community.tests.test_local_scene_campaign import approval, excluded
from community.tests.test_local_scene_pilot import catalog


class IntakeTests(unittest.TestCase):
    def test_provider_refusal_stops_one_native_attempt_and_the_whole_campaign(self):
        from types import SimpleNamespace
        import threading
        from community.local_scene_pilot import LocalScenePilot
        from community.vision_index import VisionIndexError
        from community.tests.test_local_scene_campaign import UnattendedTests
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            def denied(_argv,**options):
                options['stderr'].write(b'[vision] candidate fetch failed index=0 pano=test-pano view=0: HTTP 403 Forbidden\n')
                return SimpleNamespace(returncode=101)
            with patch('community.local_scene_pilot.run_owned',side_effect=denied) as native:
                with self.assertRaises(VisionIndexError) as error:
                    LocalScenePilot._runner(SimpleNamespace(pace='medium'),['native','index-four-view'],{},root)
                self.assertEqual(error.exception.code,'imagery_access_denied')
                self.assertEqual(native.call_count,1)
            calls=[]
            class Pilot:
                def __init__(self,*args,**kwargs):calls.append('one attempt')
                def start(self):self.thread=threading.Thread(target=lambda:None);self.thread.start()
                def close(self):self.thread.join()
                def pause(self):pass
                def status(self):return {'phase':'error','errorCode':'imagery_access_denied'}
            app=UnattendedTests().make(root,count=129,pilot_factory=Pilot)
            app.start();app.thread.join(3)
            self.assertFalse(app.thread.is_alive())
            self.assertEqual(app.phase,'imagery_unavailable');self.assertFalse(app.settings['enabled'])
            self.assertEqual(calls,['one attempt']);self.assertEqual(app.status()['completed'],0)

    def test_untrusted_check_zip_cannot_extract_unrelated_or_duplicate_members(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for i, extra in enumerate(('../outside','unrelated-account.json','installation.json')):
                archive=root/f'{i}.zip'
                with zipfile.ZipFile(archive,'w') as output:
                    output.writestr('installation.json',canonical({'installationId':'d'*64,'scope':'OWNER_REVIEW_REQUIRED'}))
                    output.writestr('threads-1/canary-report.json',b'{}')
                    output.writestr(extra,b'no extraction')
                with self.assertRaisesRegex(ValueError,'invalid_check_archive'):
                    read_check_zip(archive)
            self.assertFalse((root.parent/'outside').exists())

    def test_one_zip_reexports_retained_reservations_and_refuses_changed_packets(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);registry=root/'issuer.sqlite'
            prepare_catalog(catalog(root,130),registry);excluded(root,registry)
            manifest=allocate_campaign(registry,'one',129,'one',[approval()])
            first=export_campaign_zip(registry,'one',root/'personal-queue.zip')
            self.assertEqual(export_campaign_zip(registry,'one',root/'personal-queue.zip'),first)
            with zipfile.ZipFile(first['path']) as archive:
                self.assertEqual(json.loads(archive.read('campaign.json')),manifest)
                for entry in manifest['packets']:
                    self.assertEqual(hashlib.sha256(archive.read(entry['path'])).hexdigest(),entry['sha256'])
            with connection(registry) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM assigned').fetchone()[0],129)
                db.execute("UPDATE packets SET body=replace(body,'France','Spain') WHERE allocation='one:0'")
            with self.assertRaisesRegex(ValueError,'packet_changed'):
                export_campaign_zip(registry,'one',root/'refused.zip')
            self.assertFalse((root/'refused.zip').exists())
            self.assertTrue((root/'personal-queue.zip').exists())


if __name__=='__main__':unittest.main()
