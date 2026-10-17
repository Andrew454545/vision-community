"""Compile and exercise the fixed offline launch diagnostic; no models/network."""
import builtins
import contextlib
import io
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

SOURCE = Path(__file__).resolve().parents[2] / 'deploy/cloudflare/native-container-host/launch-check.js'
PROGRAM = re.search(r'export const LAUNCH_CHECK = String.raw`(.*?)`;', SOURCE.read_text(), re.S).group(1)


class NativeLaunchCheckTests(unittest.TestCase):
    def run_program(self, *, failure=None, import_failure=False, server_failure=None, http_failure=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'runtime-package.json').write_text(json.dumps({'runtimeSha256': 'a' * 64}))
            native = types.ModuleType('server')
            native.native = types.SimpleNamespace(strict_json=json.loads)
            native.Host = Mock(side_effect=failure)
            fronts = []
            def make_server(host, service, operator, *, bind, port):
                self.assertEqual((bind, port), ('127.0.0.1', 0))
                self.assertNotEqual(service, operator)
                class Handler(BaseHTTPRequestHandler):
                    def log_message(self, *_):
                        pass
                    def reply(self, code, value):
                        raw = json.dumps(value).encode()
                        self.send_response(code)
                        self.send_header('Cache-Control', 'no-store')
                        self.send_header('Content-Length', str(len(raw)))
                        self.end_headers()
                        self.wfile.write(raw)
                    def do_GET(self):
                        if self.headers.get('Authorization') != 'Bearer ' + service:
                            self.reply(401, {'error': 'unauthorized'})
                        else:
                            self.reply(200, {'status': 'native_host_available',
                                'runtimeSha256': ('b' if http_failure else 'a') * 64,
                                'identityOnly': True, 'auditReady': False,
                                'searchReady': False, 'activeNativeProcessesMaximum': 1})
                    def do_POST(self):
                        self.rfile.read(int(self.headers.get('Content-Length', '0')))
                        allowed = self.headers.get('Authorization') == 'Bearer ' + operator
                        self.reply(400 if allowed else 401,
                                   {'error': 'invalid_request' if allowed else 'unauthorized'})
                front = ThreadingHTTPServer((bind, port), Handler)
                front.daemon_threads = True
                fronts.append(front)
                return front
            native.make_server = Mock(side_effect=server_failure or make_server)
            real_path, real_import = Path, builtins.__import__
            def mapped_path(value):
                return root if value == '/opt/vision' else root / 'state' if value == '/state' else real_path(value)
            def controlled_import(name, *args, **kwargs):
                if name == 'server' and import_failure:
                    raise ModuleNotFoundError('private dependency /sensitive/path')
                return real_import(name, *args, **kwargs)
            output = io.StringIO()
            with patch.dict(sys.modules, {'server': native}), patch.object(sys, 'path', sys.path.copy()), \
                    patch('pathlib.Path', side_effect=mapped_path), patch('builtins.__import__', side_effect=controlled_import), \
                    patch('os.getuid', return_value=10001, create=True), patch('platform.python_version', return_value='3.12.15'), \
                    contextlib.redirect_stdout(output):
                if failure or import_failure or server_failure or http_failure:
                    with self.assertRaises(SystemExit) as stopped:
                        exec(compile(PROGRAM, str(SOURCE), 'exec'), {})
                    self.assertEqual(stopped.exception.code, 1)
                else:
                    exec(compile(PROGRAM, str(SOURCE), 'exec'), {})
            if failure or import_failure:
                native.make_server.assert_not_called()
            else:
                native.make_server.assert_called_once()
            for front in fronts:
                self.assertEqual(front.fileno(), -1)  # Success and failure close the real listening socket.
            return json.loads(output.getvalue()), native

    def test_success_checks_runtime_and_real_loopback_http_with_disposable_credentials(self):
        result, module = self.run_program()
        self.assertEqual(result, {'status': 'native_launch_check_passed', 'runtimeSha256': 'a' * 64,
                                 'pythonVersion': '3.12.15', 'uid': 10001,
                                 'modelFilesValidated': True, 'httpServerChecked': True,
                                 'serviceAuthChecked': True, 'operatorAuthChecked': True,
                                 'productionQualified': False})
        self.assertEqual(module.Host.call_args.args[1], 'a' * 64)

    def test_runtime_faults_preserve_fixed_codes_or_errno_and_hide_raw_details(self):
        for fault, code, number in [(ValueError('runtime_file_changed'), 'runtime_file_changed', None),
                                    (ValueError('linked_engine_path'), 'linked_engine_path', None),
                                    (PermissionError(13, 'private-token /sensitive/path'), 'native_boot_failed', 13)]:
            with self.subTest(code=code):
                result, _ = self.run_program(failure=fault)
                self.assertEqual(result, {'status': 'native_boot_unavailable', 'phase': 'runtime_identity',
                                          'code': code, 'errno': number})
                self.assertNotIn('private-token', json.dumps(result))
                self.assertNotIn('/sensitive', json.dumps(result))

    def test_import_failure_is_classified_without_the_dependency_name(self):
        result, module = self.run_program(import_failure=True)
        self.assertEqual(result, {'status': 'native_boot_unavailable', 'phase': 'module_import',
                                  'code': 'native_boot_failed', 'errno': None})
        module.Host.assert_not_called()
        self.assertNotIn('private', json.dumps(result))

    def test_socket_failure_preserves_numeric_errno_without_credentials_or_paths(self):
        result, _ = self.run_program(server_failure=PermissionError(13, 'private-token /sensitive/path'))
        self.assertEqual(result, {'status': 'native_boot_unavailable', 'phase': 'server_credentials',
                                  'code': 'native_boot_failed', 'errno': 13})
        self.assertNotIn('private-token', json.dumps(result))

    def test_incorrect_http_identity_fails_and_closes_the_real_listening_socket(self):
        result, _ = self.run_program(http_failure=True)
        self.assertEqual(result, {'status': 'native_boot_unavailable', 'phase': 'http_self_check',
                                  'code': 'native_http_self_check_failed', 'errno': None})


if __name__ == '__main__':
    unittest.main()
