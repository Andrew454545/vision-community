"""One offline loopback use of the unified window; never starts inference."""
import functools
import http.client
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from community.local_scene_app import LocalSceneApp
from community.local_scene_library_ui import LibrarySession
from community.local_scene_personal import create_queue,queue_zip
from community.local_scene_pilot import atomic_json
from community.local_scene_ui import handler_for,reopen_existing
from community.local_scene_unattended import LocalSceneCampaign
from community.tests.test_local_scene_personal import receipt,document
from community.tests.test_local_scene_campaign import DEVICE,profile


class LocalAppTests(unittest.TestCase):
    def test_open_restore_lock_controls_alias_and_queue_switch_without_start(self):
        with tempfile.TemporaryDirectory() as folder:
            data=Path(folder);runtime=data/'runtime';runtime.mkdir()
            first=create_queue(document('pano-one'),data,[receipt()])
            second=create_queue(document('pano-two'),data,[receipt()])
            queue_zip(Path(first['path']).parent)
            atomic_json(data/'installation-id.json',{'id':DEVICE})
            factory=functools.partial(LocalSceneCampaign,
                runtime_verifier=lambda *_a,**_k:(Path('unused'),Path('models'),profile()),
                battery=lambda:False,disk=lambda _:SimpleNamespace(free=10*1024**3))
            app=LocalSceneApp(data,runtime,engine_factory=factory)
            session=LibrarySession(app,data);app.library_session=session
            atomic_json(session.personal_library.root/'last-queue.json',{'queueId':first['queueId']})
            session.close()
            session=LibrarySession(app,data);app.library_session=session
            self.assertTrue(session.status()['personalQueueAvailable'])
            self.assertTrue(session.status()['canOpenPersonalQueue'])
            stable=app.packet['packetId'];self.assertTrue(app.status()['libraryOnly'])
            server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(app,'a'*64))
            app.window_url=f'http://127.0.0.1:{server.server_port}/'+('#'+'a'*64)
            worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
            headers={'Authorization':'Bearer '+'a'*64,'Origin':f'http://127.0.0.1:{server.server_port}'}
            client=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
            other=LocalSceneApp(data,runtime,engine_factory=factory)
            try:
                client.request('POST','/api/library/open-personal-queue','{}',headers={**headers,'Origin':'https://untrusted.example'})
                response=client.getresponse();self.assertEqual(response.status,403);response.read()
                self.assertIsNone(app.engine)
                client.request('GET','/api/library/queues',headers=headers)
                response=client.getresponse();self.assertEqual(response.status,200)
                self.assertEqual({q['queueId'] for q in json.loads(response.read())},{first['queueId'],second['queueId']})
                client.request('POST','/api/library/open-personal-queue','{}',headers=headers)
                response=client.getresponse();self.assertEqual(response.status,202);response.read()
                session.thread.join(5);self.assertFalse(session.thread.is_alive())
                self.assertTrue(session.status()['personalQueueOpened'])
                self.assertEqual(app.status()['queueName'],'My map')
                self.assertEqual(app.status()['packetId'],stable)
                self.assertFalse(app.engine.settings['enabled']);self.assertIsNone(app.thread)
                self.assertTrue(reopen_existing(app.engine,open_browser=False))
                with self.assertRaisesRegex(ValueError,'queue_open_elsewhere'):
                    other.open_personal_queue(first['path'],data_dir=data)
                with patch.object(app.engine,'start') as start:
                    client.request('POST','/api/start',headers=headers)
                    response=client.getresponse();self.assertEqual(response.status,200);response.read();start.assert_called_once()
                with patch('community.local_scene_startup.configure_startup') as startup:
                    client.request('POST','/api/startup',json.dumps({'enabled':False}),headers=headers)
                    response=client.getresponse();self.assertEqual(response.status,200);response.read()
                    startup.assert_called_once_with(app.engine,False)
                old=app.engine.root
                client.request('POST','/api/library/open-personal-queue',json.dumps({'queueId':second['queueId']}),headers=headers)
                response=client.getresponse();self.assertEqual(response.status,202);response.read()
                session.thread.join(5);self.assertTrue(session.status()['personalQueueOpened'])
                self.assertFalse((old/'window.json').exists())
                self.assertEqual(app.engine.manifest['sha256'],json.loads(Path(second['path']).read_text())['sha256'])
                self.assertFalse(app.engine.settings['enabled'])
                # Switching released the old queue while retaining the new lock.
                other.open_personal_queue(first['path'],data_dir=data)
                self.assertFalse(other.engine.settings['enabled'])
            finally:
                client.close();server.shutdown();server.server_close();worker.join(5)
                session.close();app.close();other.close()


if __name__=='__main__':unittest.main()
