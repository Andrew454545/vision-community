"""Explicit private loopback adapter for owned saved samples; inactive by default.

No CLI, startup task, public listener, native execution or artifact upload route.
Only a dedicated authenticated private bridge may ask the pinned store for
evidence. This factory alone does not activate a service or grant transfer consent.
"""
from __future__ import annotations

import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import re
import threading

from .native_scene_search import discard_small_body, strict_json
from .object_qualification import require
from .object_qualification_store import OwnedObjectQualificationStore
from .search_snapshot import encoded

ROUTE = '/object-qualifications/evidence'
MAX_REQUEST = 4096
MAX_RESPONSE = 65536


def make_server(store, secret, *, port=0):
    require(isinstance(store, OwnedObjectQualificationStore), 'object_sample_owned_store_required')
    require(isinstance(secret, str) and re.fullmatch(r'[\x21-\x7e]{32,256}', secret), 'object_sample_private_secret_required')
    require(type(port) is int and 0 <= port <= 65535, 'object_sample_private_port_required')

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.0'

        def log_message(self, *_):
            pass  # No account, paths, scores, request JSON or credentials in logs.

        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def reply(self, status, value):
            raw = encoded(value)
            if len(raw) > MAX_RESPONSE:
                status, raw = 503, encoded({'error': 'object_sample_host_unavailable'})
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            discard_small_body(self)
            self.reply(404, {'error': 'not_found'})

        def do_POST(self):
            auth = self.headers.get_all('Authorization', [])
            if len(auth) != 1 or not hmac.compare_digest(auth[0].encode(), ('Bearer ' + secret).encode()):
                discard_small_body(self)
                self.reply(401, {'error': 'unauthorized'})
                return
            if self.path != ROUTE:
                discard_small_body(self)
                self.reply(404, {'error': 'not_found'})
                return
            lengths, media = self.headers.get_all('Content-Length', []), self.headers.get_all('Content-Type', [])
            if (len(lengths) != 1 or not re.fullmatch(r'[0-9]{1,4}', lengths[0]) or not 0 < int(lengths[0]) <= MAX_REQUEST
                    or len(media) != 1 or media[0].split(';')[0].strip().lower() != 'application/json'
                    or self.headers.get_all('Transfer-Encoding') or self.headers.get_all('Content-Encoding')):
                discard_small_body(self)
                self.reply(400, {'error': 'invalid_object_sample_request'})
                return
            try:
                raw = self.rfile.read(int(lengths[0]))
                require(len(raw) == int(lengths[0]), 'invalid_object_sample_request')
                body = strict_json(raw)
            except (ValueError, OSError, UnicodeError):
                self.reply(400, {'error': 'invalid_object_sample_request'})
                return
            if not self.server.comparison.acquire(blocking=False):
                self.reply(503, {'error': 'object_sample_host_busy'})
                return
            try:
                self.reply(200, store.evidence(body))
            except Exception:
                self.reply(503, {'error': 'object_sample_host_unavailable'})
            finally:
                self.server.comparison.release()

    class Server(ThreadingHTTPServer):
        daemon_threads = True
        request_queue_size = 4

        def __init__(self, *args):
            self.slots, self.comparison = threading.BoundedSemaphore(4), threading.BoundedSemaphore(1)
            super().__init__(*args)

        def process_request(self, request, address):
            if not self.slots.acquire(blocking=False):
                self.shutdown_request(request)
                return
            try:
                super().process_request(request, address)
            except Exception:
                self.slots.release()
                raise

        def process_request_thread(self, request, address):
            try:
                super().process_request_thread(request, address)
            finally:
                self.slots.release()

        def handle_error(self, request, address):
            pass  # Disconnects must not print private handler tracebacks.

    return Server(('127.0.0.1', port), Handler)
