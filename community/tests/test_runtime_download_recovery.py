"""Interrupted setup must resume without trusting incomplete model/runtime bytes."""
import hashlib
from http.client import IncompleteRead
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from community import bootstrap


class Response(io.BytesIO):
    def __init__(self, body, status=200, headers=None):
        super().__init__(body)
        self.status = status
        self.headers = headers or {}

    def read1(self, size):
        return self.read(size)


class InterruptedResponse(Response):
    def read(self, size):
        if self.tell():
            raise OSError('connection interrupted')
        return super().read(min(4, size))


class RuntimeDownloadRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.partial = self.root/'model.partial'
        self.payload = b'immutable-model-data'
        self.entry = {'bytes': len(self.payload), 'sha256': hashlib.sha256(self.payload).hexdigest()}

    def download(self, response):
        with mock.patch.object(bootstrap.urllib.request, 'urlopen', return_value=response) as request:
            bootstrap.download_file('https://example.test/model', self.partial, self.entry)
        return request

    def test_disconnect_keeps_prefix_and_new_attempt_resumes_verified_complete_file(self):
        with self.assertRaisesRegex(bootstrap.BootstrapError, 'runtime_download_failed'):
            self.download(InterruptedResponse(self.payload))
        self.assertEqual(self.partial.read_bytes(), self.payload[:4])
        request = self.download(Response(self.payload[4:], 206,
            {'Content-Range': f'bytes 4-{len(self.payload)-1}/{len(self.payload)}'}))
        self.assertEqual(request.call_args.args[0].get_header('Range'), 'bytes=4-')
        self.assertEqual(self.partial.read_bytes(), self.payload)
        self.assertEqual(bootstrap.file_sha256(self.partial), self.entry['sha256'])

    def test_server_ignoring_range_replaces_prefix_without_duplicate_data(self):
        self.partial.write_bytes(self.payload[:4])
        request = self.download(Response(self.payload))
        self.assertEqual(request.call_args.args[0].get_header('Range'), 'bytes=4-')
        self.assertEqual(self.partial.read_bytes(), self.payload)

    def test_trickling_body_keeps_prefix_then_new_attempt_resumes_with_fresh_budget(self):
        elapsed = [0]
        class Trickle(Response):
            def read1(self, size):
                elapsed[0] += 1
                return io.BytesIO.read(self, min(4, size))
            def read(self, _size):
                raise AssertionError('Large buffered read could hide trickling progress')
        with mock.patch.object(bootstrap, 'DOWNLOAD_BODY_SECONDS', 2), \
                mock.patch.object(bootstrap.time, 'monotonic', side_effect=lambda: elapsed[0]):
            with self.assertRaisesRegex(bootstrap.BootstrapError, 'runtime_download_failed'):
                self.download(Trickle(self.payload))
            self.assertEqual(self.partial.read_bytes(), self.payload[:8])
            elapsed[0] = 10_000
            request = self.download(Response(self.payload[8:], 206,
                {'Content-Range': f'bytes 8-{len(self.payload)-1}/{len(self.payload)}'}))
        self.assertEqual(request.call_args.args[0].get_header('Range'), 'bytes=8-')
        self.assertEqual(self.partial.read_bytes(), self.payload)

    def test_body_deadline_after_complete_bytes_requires_checksum_before_reuse(self):
        elapsed = [0]
        class SlowLastFragment(Response):
            def read1(self, size):
                elapsed[0] += 2
                return io.BytesIO.read(self, size)
        with mock.patch.object(bootstrap, 'DOWNLOAD_BODY_SECONDS', 2), \
                mock.patch.object(bootstrap.time, 'monotonic', side_effect=lambda: elapsed[0]):
            with self.assertRaisesRegex(bootstrap.BootstrapError, 'runtime_download_failed'):
                self.download(SlowLastFragment(self.payload))
        self.assertEqual(self.partial.read_bytes(), self.payload)
        with mock.patch.object(bootstrap.urllib.request, 'urlopen') as network:
            bootstrap.download_file('https://example.test/model', self.partial, self.entry)
        network.assert_not_called()
        self.assertEqual(bootstrap.file_sha256(self.partial), self.entry['sha256'])

    def test_wall_clock_changes_do_not_affect_download_body_budget(self):
        with mock.patch.object(bootstrap.time, 'time', side_effect=AssertionError('Use elapsed time')):
            self.download(Response(self.payload))
        self.assertEqual(self.partial.read_bytes(), self.payload)

    def test_actual_http_fragments_hit_budget_and_resume_without_reinstalling_prefix(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import threading
        calls=[]; payload=self.payload
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):pass
            def do_GET(self):
                saved=self.headers.get('Range'); calls.append(saved)
                offset=int(saved.removeprefix('bytes=').removesuffix('-')) if saved else 0
                self.send_response(206 if saved else 200)
                if saved:self.send_header('Content-Range', f'bytes {offset}-{len(payload)-1}/{len(payload)}')
                self.send_header('Content-Length',str(len(payload)-offset));self.end_headers()
                self.wfile.write(payload[offset:])
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(thread.join,3);self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        url=f'http://127.0.0.1:{server.server_port}/model';real_open=bootstrap.urllib.request.urlopen
        elapsed=[0]
        class FragmentedHttpResponse:
            def __init__(self,response):self.response=response;self.status=response.status;self.headers=response.headers
            def __enter__(self):return self
            def __exit__(self,*_args):self.response.close()
            def read(self,_size):raise AssertionError('Do not fill a large buffer before checking elapsed time')
            def read1(self,size):
                elapsed[0]+=1
                return self.response.read1(min(4,size))
        def fragmented(request,**kwargs):return FragmentedHttpResponse(real_open(request,**kwargs))
        with mock.patch.object(bootstrap.urllib.request,'urlopen',side_effect=fragmented), \
                mock.patch.object(bootstrap,'DOWNLOAD_BODY_SECONDS',2), \
                mock.patch.object(bootstrap.time,'monotonic',side_effect=lambda:elapsed[0]):
            with self.assertRaisesRegex(bootstrap.BootstrapError,'runtime_download_failed'):
                bootstrap.download_file(url,self.partial,self.entry)
        self.assertEqual(self.partial.read_bytes(),payload[:8])
        bootstrap.download_file(url,self.partial,self.entry)
        self.assertEqual(calls,[None,'bytes=8-'])
        self.assertEqual(self.partial.read_bytes(),payload)

    def test_incomplete_chunked_transfer_keeps_prefix_for_a_retry(self):
        class ChunkedDisconnect(InterruptedResponse):
            def read(self, size):
                if self.tell():
                    raise IncompleteRead(b'', 4)
                return super().read(size)
        with self.assertRaisesRegex(bootstrap.BootstrapError, 'runtime_download_failed'):
            self.download(ChunkedDisconnect(self.payload))
        self.assertEqual(self.partial.read_bytes(), self.payload[:4])

    def test_short_success_response_is_retryable_and_not_installed(self):
        manifest = {'files': [{**self.entry, 'asset': 'mma-vision', 'path': 'bin/mma-vision', 'executable': True}]}
        with mock.patch.object(bootstrap.urllib.request, 'urlopen', return_value=Response(self.payload[:4])):
            with self.assertRaisesRegex(bootstrap.BootstrapError, 'runtime_download_failed'):
                bootstrap.install_runtime(manifest, self.root, platform_name='darwin-arm64', lane='scene')
        self.assertFalse((self.root/'bin/mma-vision').exists())
        self.assertEqual((self.root/'bin/mma-vision.partial').read_bytes(), self.payload[:4])

    def test_complete_checked_partial_needs_no_network(self):
        self.partial.write_bytes(self.payload)
        with mock.patch.object(bootstrap.urllib.request, 'urlopen') as network:
            bootstrap.download_file('https://example.test/model', self.partial, self.entry)
        network.assert_not_called()
        self.assertEqual(self.partial.read_bytes(), self.payload)

    def test_wrong_range_start_total_bounds_or_missing_header_preserves_prefix(self):
        for received_range in ('', 'bytes 0-18/19', 'bytes 4-18/99', 'bytes 4-99/19', 'bytes 5-18/19', 'bytes 4-2/19'):
            self.partial.write_bytes(self.payload[:4])
            with self.subTest(range=received_range), self.assertRaisesRegex(bootstrap.BootstrapError, 'runtime_download_failed'):
                self.download(Response(self.payload[4:], 206, {'Content-Range': received_range}))
            self.assertEqual(self.partial.read_bytes(), self.payload[:4])

    def test_server_range_fragment_is_kept_for_the_next_request(self):
        self.partial.write_bytes(self.payload[:4])
        with self.assertRaisesRegex(bootstrap.BootstrapError, 'runtime_download_failed'):
            self.download(Response(self.payload[4:8], 206,
                {'Content-Range': f'bytes 4-7/{len(self.payload)}'}))
        self.assertEqual(self.partial.read_bytes(), self.payload[:8])
        request = self.download(Response(self.payload[8:], 206,
            {'Content-Range': f'bytes 8-{len(self.payload)-1}/{len(self.payload)}'}))
        self.assertEqual(request.call_args.args[0].get_header('Range'), 'bytes=8-')
        self.assertEqual(self.partial.read_bytes(), self.payload)

    def test_oversized_response_is_rejected_before_excess_bytes_are_written(self):
        with self.assertRaisesRegex(bootstrap.BootstrapError, 'runtime_mismatch'):
            self.download(Response(self.payload+b'not part of model'))
        self.assertFalse(self.partial.exists())

    def test_range_body_exceeding_declared_end_is_rejected(self):
        self.partial.write_bytes(self.payload[:4])
        with self.assertRaisesRegex(bootstrap.BootstrapError, 'runtime_mismatch'):
            self.download(Response(self.payload[4:], 206,
                {'Content-Range': f'bytes 4-7/{len(self.payload)}'}))
        self.assertFalse(self.partial.exists())

    def test_corrupt_prefix_cannot_pass_full_model_checksum(self):
        self.partial.write_bytes(b'xxxx')
        with self.assertRaisesRegex(bootstrap.BootstrapError, 'runtime_mismatch'):
            self.download(Response(self.payload[4:], 206,
                {'Content-Range': f'bytes 4-{len(self.payload)-1}/{len(self.payload)}'}))
        self.assertFalse(self.partial.exists())

    def test_wrong_complete_or_oversized_partial_rejects_before_network(self):
        for body in (b'x'*len(self.payload), self.payload+b'x'):
            self.partial.write_bytes(body)
            with mock.patch.object(bootstrap.urllib.request, 'urlopen') as network:
                with self.assertRaisesRegex(bootstrap.BootstrapError, 'runtime_mismatch'):
                    bootstrap.download_file('https://example.test/model', self.partial, self.entry)
            network.assert_not_called()
            self.assertFalse(self.partial.exists())

    def test_encoded_or_unsuccessful_response_cannot_replace_existing_prefix(self):
        for status, headers in ((200, {'Content-Encoding': 'gzip'}), (204, {}), (503, {})):
            self.partial.write_bytes(self.payload[:4])
            with self.subTest(status=status), self.assertRaisesRegex(bootstrap.BootstrapError, 'runtime_download_failed'):
                self.download(Response(self.payload, status, headers))
            self.assertEqual(self.partial.read_bytes(), self.payload[:4])

    def test_invalid_pin_rejects_before_network_or_file_creation(self):
        for key, bad in (('bytes', True), ('bytes', 0), ('bytes', 512*1024**2+1), ('sha256', 'untrusted')):
            entry = {**self.entry, key: bad}
            with mock.patch.object(bootstrap.urllib.request, 'urlopen') as network:
                with self.subTest(key=key, bad=bad), self.assertRaisesRegex(bootstrap.BootstrapError, 'invalid_runtime_manifest'):
                    bootstrap.download_file('https://example.test/model', self.partial, entry)
            network.assert_not_called()
            self.assertFalse(self.partial.exists())

    def test_directory_is_not_opened_or_deleted_as_a_partial_download(self):
        self.partial.mkdir()
        (self.partial/'keep').write_bytes(b'original evidence')
        with self.assertRaisesRegex(bootstrap.BootstrapError, 'unsafe_runtime_path'):
            self.download(Response(self.payload))
        self.assertEqual((self.partial/'keep').read_bytes(), b'original evidence')

    def test_standard_setup_never_spawns_pip_or_other_global_installers(self):
        for lane in ('scene', 'object', 'all'):
            with self.subTest(lane=lane), mock.patch('sys.argv', ['bootstrap', '--lane', lane]), \
                    mock.patch.object(bootstrap, 'load_manifest', return_value={}), \
                    mock.patch.object(bootstrap, 'install_runtime', return_value=[]), \
                    mock.patch.object(subprocess, 'run') as installer:
                self.assertEqual(bootstrap.main(), 0)
            installer.assert_not_called()


if __name__ == '__main__': unittest.main()
