"""Real loopback service boundaries; no public calls or real credentials."""
from http.client import HTTPException
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from community import contribute as transport
from community.contribute import CommunityClient, ContributeError, read_service_json
from community.desktop import DesktopClient


class FragmentedReply(io.BytesIO):
    def __init__(self, raw, declared=None, fragment=3):
        super().__init__(raw)
        self.headers = {} if declared is None else {'Content-Length': str(declared)}
        self.fragment = fragment
        self.read_sizes = []

    def read1(self, size=-1):
        self.read_sizes.append(size)
        return super().read(min(size, self.fragment))


class ServiceTransportTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.destination_calls = []
        self.response = (200, b'{"accepted":1,"unitsEarned":1}', 'length')
        self.redirect = None
        owner = self

        class Destination(BaseHTTPRequestHandler):
            def log_message(self, *_args): pass
            def do_GET(self):
                owner.destination_calls.append((self.command, dict(self.headers)))
                self.send_response(200)
                self.send_header('Content-Length', '2')
                self.end_headers()
                self.wfile.write(b'{}')
            do_POST = do_GET

        self.destination = self.server(Destination)

        class Origin(BaseHTTPRequestHandler):
            def log_message(self, *_args): pass
            def do_GET(self):
                body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
                owner.calls.append((self.command, self.path, dict(self.headers), body))
                if owner.redirect:
                    status, target = owner.redirect
                    self.send_response(status)
                    self.send_header('Location', target)
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                    return
                status, raw, mode = owner.response
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                if mode == 'length': self.send_header('Content-Length', str(len(raw)))
                elif mode == 'short': self.send_header('Content-Length', str(len(raw) + 100))
                elif mode == 'chunked': self.send_header('Transfer-Encoding', 'chunked')
                self.send_header('Connection', 'close')
                self.end_headers()
                try:
                    if mode == 'chunked':
                        self.wfile.write(format(len(raw), 'x').encode() + b'\r\n' + raw + b'\r\n0\r\n\r\n')
                    else: self.wfile.write(raw)
                    self.wfile.flush()
                except (ConnectionError, OSError): pass
                self.close_connection = True
            do_POST = do_GET

        self.origin = self.server(Origin)
        self.url = f'http://127.0.0.1:{self.origin.server_port}'
        self.client = CommunityClient(self.url, token='fixture-private-token')

    def server(self, handler):
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def close():
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        self.addCleanup(close)
        return server

    def test_all_service_redirects_refused_for_json_and_binary_credentials(self):
        actions = [lambda: self.client.request('POST', '/api/submissions', {'saved':'fixture'}),
                   lambda: self.client.request('GET', '/api/me'),
                   lambda: self.client.scene_index_file('saved-search', 'saved-key'),
                   lambda: self.client.object_index_file('saved-search', 'saved-key'),
                   lambda: self.client.index_shard(search_id='saved-search', key='saved-key')]
        for status in (301, 302, 303, 307, 308):
            for action in actions:
                with self.subTest(status=status, action=actions.index(action)):
                    before = len(self.calls)
                    self.redirect = (status, f'http://127.0.0.1:{self.destination.server_port}/redirect-target')
                    with self.assertRaises(ContributeError) as caught:
                        action()
                    self.assertEqual((caught.exception.code, caught.exception.status), ('service_redirect_refused',503))
                    self.assertNotIn('fixture-private-token', str(caught.exception))
                    self.assertEqual(len(self.calls), before + 1)
                    self.assertEqual(self.destination_calls, [])
        self.assertTrue(all(c[2]['Authorization'] == 'Bearer fixture-private-token' for c in self.calls))

    def test_same_origin_redirect_cannot_change_mutating_post_to_get(self):
        self.redirect = (303, self.url + '/other-api')
        with self.assertRaisesRegex(ContributeError, 'service_redirect_refused'):
            self.client.request('POST', '/api/submissions', {'saved':'fixture'})
        self.assertEqual([(c[0], c[1]) for c in self.calls], [('POST','/api/submissions')])

    def test_normal_reply_and_separate_clients_keep_private_tokens(self):
        other = CommunityClient(self.url, token='other-fixture-token')
        self.assertEqual(self.client.request('POST','/api/submissions',{}), (200,{'accepted':1,'unitsEarned':1},None))
        other.request('GET','/api/me')
        self.assertEqual([c[2]['Authorization'] for c in self.calls],
                         ['Bearer fixture-private-token','Bearer other-fixture-token'])

    def test_fragment_reader_accepts_exact_limit_without_trusting_length(self):
        for declared in (None, 8):
            reply = FragmentedReply(b'12345678', declared)
            with patch.object(transport, 'MAX_SERVICE_JSON_BYTES', 8):
                self.assertEqual(read_service_json(reply), b'12345678')
            self.assertLessEqual(max(reply.read_sizes), 9)

    def test_fragment_reader_rejects_declared_or_actual_overflow(self):
        for declared, raw in ((9,b''), (-1,b''), (None,b'123456789'), (8,b'123456789')):
            with self.subTest(declared=declared), patch.object(transport, 'MAX_SERVICE_JSON_BYTES', 8):
                reply = FragmentedReply(raw, declared)
                with self.assertRaisesRegex(ContributeError, 'service_response_limit'):
                    read_service_json(reply)
                self.assertLessEqual(reply.tell(), 9)

    def test_fragment_reader_rejects_incomplete_declared_body(self):
        with self.assertRaises(HTTPException):
            read_service_json(FragmentedReply(b'{}', 5))

    def test_available_trickling_fragments_stop_at_elapsed_body_budget(self):
        reply = FragmentedReply(b'12345678', fragment=1)
        with patch.object(transport.time, 'monotonic', side_effect=(100,100,219,220)):
            with self.assertRaisesRegex(ContributeError, 'service_response_limit'):
                read_service_json(reply)
        self.assertEqual(reply.tell(), 2)

    def test_oversized_actual_http_body_is_bounded_with_or_without_length(self):
        for mode in ('length','close','chunked'):
            self.response = (200,b' ' * 65,mode)
            with self.subTest(mode=mode), patch.object(transport,'MAX_SERVICE_JSON_BYTES',64):
                with self.assertRaises(ContributeError) as caught:
                    self.client.request('GET','/api/me')
                self.assertEqual((caught.exception.code,caught.exception.status),('service_response_limit',503))
        self.assertEqual(len(self.calls),3)

    def test_oversized_error_body_cannot_hide_revocation_http_status(self):
        self.response = (401,b'{"error":"private-unsafe-message"}' + b' '*65,'length')
        with patch.object(transport,'MAX_SERVICE_JSON_BYTES',64):
            with self.assertRaises(ContributeError) as caught:
                self.client.request('POST','/api/recovery',{'recoveryCode':'fixture-code'})
        self.assertEqual((caught.exception.code,caught.exception.status),('http_error',401))
        self.assertNotIn('private-unsafe-message',str(caught.exception))
        self.assertEqual(len(self.calls),1)

    def test_unexpected_http_error_values_never_become_private_exception_text(self):
        private = 'fixture-private-token account-code-and-local-name'
        for status in (401, 409, 503):
            for value in (private, {'token': private}, [private], 7, None):
                with self.subTest(status=status, value_type=type(value).__name__):
                    self.response = (status, json.dumps({'error': value}).encode(), 'length')
                    with patch.object(transport.time, 'sleep'), self.assertRaises(ContributeError) as caught:
                        self.client.request('POST', '/api/recovery', {'recoveryCode': private})
                    self.assertEqual((caught.exception.code, caught.exception.status), ('http_error', status))
                    self.assertNotIn(private, str(caught.exception))

    def test_recognized_error_codes_keep_queue_terminal_and_retry_decisions(self):
        for status, code in ((401, 'unauthorized'), (409, 'expired_lease'),
                             (404, 'unknown_lease'), (422, 'scene_submission_rejected'),
                             (503, 'scene_verifier_unavailable'), (429, 'rate_limited')):
            with self.subTest(code=code):
                self.response = (status, json.dumps({'error': code}).encode(), 'length')
                with patch.object(transport.time, 'sleep'), self.assertRaises(ContributeError) as caught:
                    self.client.request('POST', '/api/submissions', {})
                self.assertEqual((caught.exception.code, caught.exception.status), (code, status))

    def test_truncated_actual_success_reply_is_retried_without_false_acknowledgement(self):
        self.response = (200,b'{"accepted":1,"unitsEarned":1}','short')
        with patch.object(transport.time,'sleep'):
            with self.assertRaisesRegex(ContributeError,'network_error'):
                self.client.request('POST','/api/submissions',{'saved':'fixture'})
        self.assertEqual(len(self.calls),3)

    def test_saved_delivery_survives_redirect_and_oversized_success_then_recovers(self):
        with tempfile.TemporaryDirectory() as temp:
            client = DesktopClient(self.url)
            client.enable_outbox(Path(temp),'b'*32)
            lease, outputs = 'a'*32,[{'locationId':1,'embedding':'fixture-saved'}]
            self.redirect = (307,f'http://127.0.0.1:{self.destination.server_port}/other')
            with self.assertRaisesRegex(ContributeError,'service_redirect_refused'):
                client.submit(lease,outputs)
            saved = client.outbox.pending()
            self.redirect = None
            self.response = (200,b' ' *65,'close')
            with patch.object(transport,'MAX_SERVICE_JSON_BYTES',64):
                with self.assertRaisesRegex(ContributeError,'service_response_limit'):
                    client.submit(lease,outputs)
            self.assertEqual(client.outbox.pending(),saved)
            self.assertEqual(json.loads(saved[0]['payload_json']),outputs)
            self.assertEqual(self.destination_calls,[])
            self.response = (200,b'{"accepted":1,"unitsEarned":1}','length')
            self.assertEqual(client.resume_submissions(),{'accepted':1,'unitsEarned':1})
            self.assertEqual(client.outbox.pending(),[])


if __name__ == '__main__': unittest.main()
