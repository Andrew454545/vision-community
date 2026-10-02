"""Exercise the fixed entrypoint with synthetic startup faults, never models."""
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch


SOURCE = Path(__file__).resolve().parents[2] / 'deploy/cloudflare/native-container-host/bootstrap.js'
PROGRAM = re.search(r'export const BOOTSTRAP = String.raw`(.*?)`;', SOURCE.read_text(), re.S).group(1)
SECRET = 's' * 64
OPERATOR = 'o' * 64


class BootstrapTests(unittest.TestCase):
    def run_program(self, *, host_error=None, credential_error=None, state_error=None, bad_manifest=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'runtime-package.json').write_text('broken' if bad_manifest else json.dumps({'runtimeSha256': 'a' * 64}))
            real_path = Path
            state = root / 'state'
            def mapped_path(value):
                if value == '/opt/vision':
                    return root
                if value == '/state':
                    return types.SimpleNamespace(mkdir=Mock(side_effect=state_error)) if state_error else state
                return real_path(value)
            native = types.ModuleType('server')
            native.native = types.SimpleNamespace(strict_json=json.loads)
            native.Host = Mock(side_effect=host_error)
            front = Mock()
            native.make_server = Mock(return_value=front, side_effect=credential_error)
            diagnostics, timers = [], []
            class SyntheticServer:
                def __init__(self, address, handler):
                    self.address, self.handler = address, handler
                    self.closed = False
                    diagnostics.append(self)
                def serve_forever(self):
                    pass
                def shutdown(self):
                    pass
                def server_close(self):
                    self.closed = True
            def synthetic_timer(seconds, callback):
                timer = Mock()
                timer.seconds, timer.callback = seconds, callback
                timers.append(timer)
                return timer
            with patch.dict(sys.modules, {'server': native}), patch.object(sys, 'path', sys.path.copy()), \
                    patch('pathlib.Path', side_effect=mapped_path), \
                    patch('http.server.ThreadingHTTPServer', SyntheticServer), \
                    patch('threading.Timer', side_effect=synthetic_timer), \
                    patch.dict(os.environ, {'VISION_HOST_SECRET': SECRET, 'VISION_HOST_OPERATOR_SECRET': OPERATOR}):
                namespace = {}
                if any((host_error, credential_error, state_error, bad_manifest)):
                    with self.assertRaises(SystemExit) as stopped:
                        exec(compile(PROGRAM, str(SOURCE), 'exec'), namespace)
                    self.assertEqual(stopped.exception.code, 1)
                else:
                    exec(compile(PROGRAM, str(SOURCE), 'exec'), namespace)
            if diagnostics:
                self.assertTrue(diagnostics[0].closed)
                self.assertEqual(timers[0].seconds, 45)
                timers[0].start.assert_called_once()
                timers[0].cancel.assert_called_once()
            return namespace, native, front, diagnostics

    def request(self, diagnostic, authorization=None, path='/health'):
        handler = object.__new__(diagnostic.handler)
        handler.path, handler.wfile = path, io.BytesIO()
        headers = [] if authorization is None else authorization
        handler.headers = types.SimpleNamespace(get_all=lambda *_: headers)
        statuses = []
        handler.send_response = statuses.append
        handler.send_header = lambda *_: None
        handler.end_headers = lambda: None
        handler.do_GET()
        return statuses[0], json.loads(handler.wfile.getvalue())

    def test_success_uses_the_pinned_host_and_existing_front_door(self):
        _, module, front, diagnostic = self.run_program()
        self.assertFalse(diagnostic)
        self.assertEqual(module.Host.call_args.args[1], 'a' * 64)
        self.assertEqual(module.make_server.call_args.args[1:], (SECRET, OPERATOR))
        front.serve_forever.assert_called_once()
        front.server_close.assert_called_once()

    def test_runtime_fault_is_classified_without_raw_exception_text(self):
        _, _, _, diagnostic = self.run_program(host_error=RuntimeError('private-token /sensitive/path'))
        status, result = self.request(diagnostic[0], ['Bearer ' + SECRET])
        self.assertEqual(status, 200)
        self.assertEqual(result, {'status': 'native_boot_unavailable', 'phase': 'runtime_identity', 'code': 'native_boot_failed', 'errno': None})
        self.assertNotIn('private-token', json.dumps(result))
        self.assertNotIn('/sensitive', json.dumps(result))

    def test_known_runtime_failure_preserves_only_its_fixed_code(self):
        _, _, _, diagnostic = self.run_program(host_error=ValueError('runtime_file_changed'))
        self.assertEqual(self.request(diagnostic[0], ['Bearer ' + SECRET])[1]['code'], 'runtime_file_changed')

    def test_state_permissions_preserve_numeric_errno_without_path(self):
        _, _, _, diagnostic = self.run_program(state_error=PermissionError(13, 'private/path'))
        result = self.request(diagnostic[0], ['Bearer ' + SECRET])[1]
        self.assertEqual(result['phase'], 'state_directory')
        self.assertEqual(result['errno'], 13)
        self.assertNotIn('private/path', json.dumps(result))

    def test_invalid_manifest_never_reaches_the_native_runtime(self):
        _, module, _, diagnostic = self.run_program(bad_manifest=True)
        module.Host.assert_not_called()
        self.assertEqual(self.request(diagnostic[0], ['Bearer ' + SECRET])[1]['phase'], 'runtime_manifest')

    def test_credential_fault_reports_no_secret_values(self):
        _, _, _, diagnostic = self.run_program(credential_error=ValueError('private_host_secret_required'))
        result = self.request(diagnostic[0], ['Bearer ' + SECRET])[1]
        self.assertEqual(result['phase'], 'server_credentials')
        self.assertEqual(result['code'], 'private_host_secret_required')
        self.assertNotIn(SECRET, json.dumps(result))
        self.assertNotIn(OPERATOR, json.dumps(result))

    def test_boot_diagnostics_require_the_service_credential_and_exact_route(self):
        _, _, _, diagnostic = self.run_program(host_error=RuntimeError('synthetic failure'))
        for headers, path in [(None, '/health'), (['Bearer ' + OPERATOR], '/health'),
                              (['Bearer ' + SECRET] * 2, '/health'), (['Bearer ' + SECRET], '/private')]:
            self.assertEqual(self.request(diagnostic[0], headers, path), (404, {'error': 'unavailable'}))


if __name__ == '__main__':
    unittest.main()
