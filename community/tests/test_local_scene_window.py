"""One focused native-view trust/fallback/loopback flow; no GUI or inference."""
import hashlib
import http.client
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from community.local_scene_window import NativeWindow,provision
from community.local_scene_pilot import atomic_json
from community.mac_starter import pin
from community.local_scene_ui import handler_for,reopen_existing


class NativeWindowTests(unittest.TestCase):
    def test_verified_provision_authentication_reopen_and_nonexecuting_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source';native=source/'native-window';native.mkdir(parents=True)
            program=native/'VISION Desktop Window';program.write_bytes(b'synthetic-unexecuted-view')
            manifest={'version':1,'platform':'darwin-arm64','executable':program.name,'files':{program.name:pin(program)}}
            atomic_json(native/'manifest.json',manifest)
            atomic_json(source/'release-inventory.json',{'files':{'native-window/manifest.json':pin(native/'manifest.json')}})
            private=root/'private';private.mkdir();installed=provision(source,private)
            self.assertEqual(installed.name,hashlib.sha256((native/'manifest.json').read_bytes()).hexdigest())
            app=SimpleNamespace(root=private,packet={'packetId':'b'*64},pause=Mock(),status=lambda:{'packetId':'b'*64})
            server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(app,'a'*64))
            url=f'http://127.0.0.1:{server.server_port}/#'+('a'*64)
            view=NativeWindow(installed,app,server,url);app.native_window=view;view.active=True
            atomic_json(app.root/'window.json',{'url':url,'packetId':'b'*64})
            worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
            client=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
            headers={'Authorization':'Bearer '+'a'*64,'Origin':f'http://127.0.0.1:{server.server_port}'}
            try:
                client.request('GET','/api/window');response=client.getresponse();self.assertEqual(response.status,403);response.read()
                client.request('POST','/api/window/show',headers={**headers,'Origin':'https://untrusted.example'})
                response=client.getresponse();self.assertEqual(response.status,403);response.read();self.assertEqual(view.counter,0)
                with patch('community.local_scene_ui.webbrowser.open') as browser:
                    self.assertTrue(reopen_existing(app));browser.assert_not_called()
                self.assertEqual(view.counter,1)
                client.request('GET','/api/window',headers=headers)
                response=client.getresponse();self.assertEqual(json.loads(response.read())['showCounter'],1)
                with patch('community.local_scene_window.sys.platform','darwin'),\
                     patch('community.local_scene_window.run_owned',return_value=SimpleNamespace(returncode=23)) as run,\
                     patch('community.local_scene_window.webbrowser.open') as browser:
                    view._run();run.assert_called_once();browser.assert_called_once_with(url)
                self.assertFalse(list((private/'native-window-diagnostics').glob('*.connection.json')))
                (installed/program.name).write_bytes(b'changed')
                with patch('community.local_scene_window.run_owned') as run,patch('community.local_scene_window.webbrowser.open') as browser:
                    view._run();run.assert_not_called();browser.assert_called_once_with(url)
                self.assertEqual(json.loads((private/'native-window-failure.json').read_text())['code'],'native_window_file_changed')
                app.pause.assert_not_called()
            finally:
                client.close();server.shutdown();server.server_close();worker.join(5);view.close()


if __name__=='__main__':unittest.main()
