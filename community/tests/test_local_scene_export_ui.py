"""A participant can save verified local groups through the private pilot window."""
import http.client
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile
from http.server import ThreadingHTTPServer

from community.local_scene_ui import handler_for
from community.tests import test_local_scene_pilot as fixtures
from community.tests import test_local_scene_archive as archives


class ExportWindowTest(unittest.TestCase):
    def test_actual_loopback_downloads_archive_without_starting_or_uploading(self):
        with tempfile.TemporaryDirectory() as folder:
            app=archives.ArchiveTest().make(Path(folder),2)
            server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(app,'secret'))
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            origin=f'http://127.0.0.1:{server.server_port}'
            def request(headers):
                conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=10)
                try:
                    conn.request('POST','/api/export',headers=headers)
                    response=conn.getresponse()
                    return response.status,dict(response.getheaders()),response.read()
                finally:conn.close()
            try:
                with patch.object(app,'start',side_effect=AssertionError('no indexing')), \
                     patch('community.contribute.CommunityClient',side_effect=AssertionError('no cloud')):
                    for headers in ({},{'Authorization':'Bearer secret'},
                                    {'Authorization':'Bearer secret','Origin':'https://other.test'}):
                        self.assertEqual(request(headers)[0],403)
                    self.assertFalse((app.root.parent/'exports').exists())
                    status,headers,body=request({'Authorization':'Bearer secret','Origin':origin})
                self.assertEqual(status,200)
                self.assertEqual(headers['Content-Type'],'application/zip')
                self.assertIn('attachment;',headers['Content-Disposition'])
                with zipfile.ZipFile(io.BytesIO(body)) as archive:
                    self.assertIn('packet.json',archive.namelist())
                    self.assertEqual(json.loads(archive.read('packet.json'))['packetId'],app.packet['packetId'])
                    self.assertEqual(len([n for n in archive.namelist() if n.endswith('.i8')]),1)
                    self.assertNotIn('window.json',archive.namelist())
                self.assertTrue((app.root/'result.json').is_file())
                self.assertEqual(app.status()['creditsEarned'],0)
            finally:server.shutdown();server.server_close();thread.join(3)

    def test_export_requires_processing_to_stop_and_does_not_cancel_it(self):
        with tempfile.TemporaryDirectory() as folder:
            app=fixtures.PilotTest().make(Path(folder),2)
            release=threading.Event();app.thread=threading.Thread(target=release.wait);app.thread.start()
            try:
                self.assertFalse(app.status()['exportAvailable'])
                with patch('community.local_scene_archive.export_saved_results',side_effect=AssertionError('no concurrent export')):
                    with self.assertRaisesRegex(ValueError,'pause_before_export'):app.export_results()
                self.assertFalse(app.stop.is_set())
            finally:release.set();app.thread.join(3)

    def test_corrupt_completed_output_refuses_download_and_preserves_original(self):
        with tempfile.TemporaryDirectory() as folder:
            app=archives.ArchiveTest().make(Path(folder),2)
            shard=next(app.root.glob('part-*/attempt-*/index/*.i8'))
            shard.write_bytes(b'preserved-corrupt-fixture')
            with self.assertRaises(ValueError):app.export_results()
            self.assertEqual(shard.read_bytes(),b'preserved-corrupt-fixture')
            self.assertFalse(list(app.root.parent.glob('exports/*.zip')))


if __name__=='__main__':unittest.main()
