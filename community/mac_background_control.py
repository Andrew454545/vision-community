"""Private local schedule window. Closing it leaves launchd processing alone."""
import argparse
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import sys
import threading
import webbrowser

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from community.mac_background import MacBackground

WEB = Path(__file__).resolve().parent / 'background_web'
MESSAGES = {
    'finish_current_batch_then_retry':'The current batch is still finishing. Wait, close the guided setup window, then try again.',
    'background_controls_busy':'Another change is still finishing. Please wait.',
    'contribution_consent_required':'Tick the contribution permission box before enabling.',
    'paste_saved_recovery_code':'Paste the recovery code from your Community account.',
    'saved_account_needs_review':'The saved account needs review. Your existing files were kept.',
    'saved_failure_or_stop_needs_review':'A saved failure or stop request needs review. Your work was kept.',
    'enable_background_first':'Save and enable automatic processing first.',
    'invalid_mac_background_settings':'Choose different day and night times and valid processing settings.',
}


class Controls:
    def __init__(self, manager):
        self.manager = manager
        self.token = secrets.token_hex(32)
        self.busy = threading.Lock()
        self.server = None

    def act(self, name, value):
        if not self.busy.acquire(blocking=False):
            raise ValueError('background_controls_busy')
        try:
            if name == 'enable':
                self.manager.enable(value.get('settings'), accept=value.get('accept'), code=value.get('code',''))
            elif name == 'pause':
                self.manager.pause(True)
            elif name == 'resume':
                self.manager.pause(False)
            elif name == 'remove':
                self.manager.remove()
            elif name == 'quit':
                return {'message':'Controls closed. Enabled automatic processing continues.'}
            else:
                raise ValueError('invalid_control_action')
            return self.manager.status()
        except Exception as error:
            self.manager.preserve_failure(error)
            raise
        finally:
            self.busy.release()


def handler_for(controls):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, *_args):
            pass  # No URLs, account codes or authorization headers in logs.

        def allowed(self, token=False):
            origin = 'http://127.0.0.1:' + str(self.server.server_port)
            return (self.headers.get('Host') == origin[7:]
                and self.headers.get('Origin') in {None, origin}
                and (not token or hmac.compare_digest(self.headers.get('X-Vision-Token',''), controls.token)))

        def send(self, status, body, kind='application/json'):
            if isinstance(body, dict):
                body = json.dumps(body).encode()
            self.send_response(status)
            for key, value in {'Content-Type':kind, 'Content-Length':str(len(body)), 'Cache-Control':'no-store',
                'X-Content-Type-Options':'nosniff', 'Referrer-Policy':'no-referrer',
                'Content-Security-Policy':"default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"}.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def failure(self, error):
            self.send(400, {'error':MESSAGES.get(str(error),
                'The change could not be completed. Saved work and a private failure report were kept.')})

        def do_GET(self):
            if not self.allowed(token=self.path == '/api/status'):
                return self.send(403, {'error':'This private window could not be verified.'})
            if self.path == '/api/status':
                try:
                    return self.send(200, controls.manager.status())
                except Exception as error:
                    controls.manager.preserve_failure(error)
                    return self.failure(error)
            assets = {'/':('index.html','text/html; charset=utf-8'), '/app.js':('app.js','text/javascript'),
                '/style.css':('style.css','text/css')}
            if self.path not in assets:
                return self.send(404, {'error':'Not found.'})
            file, kind = assets[self.path]
            self.send(200, (WEB / file).read_bytes(), kind)

        def do_POST(self):
            if not self.allowed(token=True):
                return self.send(403, {'error':'This private window could not be verified.'})
            if self.path not in {'/api/enable','/api/pause','/api/resume','/api/remove','/api/quit'}:
                return self.send(404, {'error':'Not found.'})
            try:
                sizes = self.headers.get_all('Content-Length') or []
                if (self.headers.get('Transfer-Encoding') is not None or len(sizes) != 1
                        or self.headers.get('Content-Type') != 'application/json'):
                    raise ValueError('invalid_request')
                length = int(sizes[0])
                if not 0 < length <= 4096:
                    raise ValueError('invalid_request')
                value = json.loads(self.rfile.read(length))
                if not isinstance(value, dict):
                    raise ValueError('invalid_request')
                self.send(200, controls.act(self.path[5:], value))
                if self.path == '/api/quit':
                    # The process owns the server's main thread. Shutdown before
                    # flushing can exit it while this daemon request is still
                    # sending the acknowledgement, cutting off a valid reply.
                    self.wfile.flush()
                    self.close_connection = True
                    controls.server.shutdown()
            except Exception as error:
                self.failure(error)
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--check-label', help=argparse.SUPPRESS)
    parser.add_argument('--check-home', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if bool(args.check_label) != bool(args.check_home) or (args.check_label and
            not args.check_label.startswith('org.visioncommunity.check.')):
        parser.error('Finite checks require their own temporary label and home.')
    from community.mac_launch_agent import LABEL
    manager = MacBackground(args.root, Path(__file__).resolve().parents[1],
        home=args.check_home, label=args.check_label or LABEL)
    controls = Controls(manager)
    server = ThreadingHTTPServer(('127.0.0.1',0), handler_for(controls))
    server.daemon_threads = True
    controls.server = server
    url = 'http://127.0.0.1:' + str(server.server_port) + '/#' + controls.token
    if args.no_browser:
        # Finite diagnostic only. This file is private and never an artifact.
        from community.mac_starter import regular
        path = regular(args.root / 'mac-controls-test-url', missing=True)
        with path.open('x', encoding='utf-8') as output:
            output.write(url)
    else:
        webbrowser.open(url)
    print('VISION schedule controls are open. Closing them leaves automatic processing enabled.')
    try:
        server.serve_forever()
    finally:
        server.server_close()
        if args.no_browser:
            regular(args.root / 'mac-controls-test-url').unlink()


if __name__ == '__main__':
    main()
