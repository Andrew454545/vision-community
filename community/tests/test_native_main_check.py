"""Exercise the fixed private diagnostic with disposable server subprocesses."""
import contextlib
import io
import json
import os
from pathlib import Path
import re
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[2] / 'deploy/cloudflare/native-container-host/main-check.js'
PROGRAM = re.search(r'export const MAIN_CHECK = String.raw`(.*?)`;', SOURCE.read_text(), re.S).group(1)

SERVER = '''import json, os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def reply(self, status, value):
        raw = json.dumps(value).encode()
        self.send_response(status)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers(); self.wfile.write(raw)
    def do_GET(self):
        if self.headers.get('Authorization') != 'Bearer ' + os.environ['VISION_HOST_SECRET']:
            self.reply(401, {'error': 'unauthorized'}); return
        self.reply(200, {'status': 'native_host_available', 'runtimeSha256': 'a'*64,
            'identityOnly': True, 'auditReady': False, 'searchReady': False, 'activeNativeProcessesMaximum': 1})
    def do_POST(self):
        self.rfile.read(int(self.headers.get('Content-Length', 0)))
        allowed = self.headers.get('Authorization') == 'Bearer ' + os.environ['VISION_HOST_OPERATOR_SECRET']
        self.reply(400 if allowed else 401, {'error': 'invalid_request' if allowed else 'unauthorized'})
ThreadingHTTPServer(('127.0.0.1', PORT), Handler).serve_forever()
'''

class NativeMainCheckTests(unittest.TestCase):
    def run_program(self, script, timeout=20, exited_during_signal=False, measurements=False):
        with socket.socket() as reserve:
            reserve.bind(('127.0.0.1', 0)); port = reserve.getsockname()[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / 'runtime-package.json'
            package.write_text(json.dumps({'runtimeSha256': 'a' * 64}))
            server = root / 'server.py'
            server.write_text(script.replace('PORT', str(port)))
            program = PROGRAM.replace("'/opt/vision/runtime-package.json'", repr(str(package))).replace(
                "'/opt/vision/server.py'", repr(str(server))).replace('8080', str(port)).replace(
                'time.monotonic() + 20', 'time.monotonic() + ' + str(timeout))
            output = io.StringIO()
            def exited_terminate(process):
                # Exercise a real subprocess exiting while stop() signals it.
                original_terminate(process)
                process.wait(timeout=2)
                raise ProcessLookupError()
            import subprocess
            original_terminate = subprocess.Popen.terminate
            with patch.dict(os.environ, {'VISION_HOST_SECRET': 'a' * 64, 'VISION_HOST_OPERATOR_SECRET': 'b' * 64}), \
                    patch('os.getuid', return_value=10001, create=True), patch('platform.python_version', return_value='3.12.15'), \
                    contextlib.redirect_stdout(output):
                with contextlib.ExitStack() as cleanup:
                    if exited_during_signal:
                        # Use the Windows signalling branch on either platform;
                        # no orphan or platform-specific mock process is involved.
                        program = program.replace("if os.name == 'posix':", 'if False:')
                        cleanup.enter_context(patch('subprocess.Popen.terminate', exited_terminate))
                    with self.assertRaises(SystemExit) as stopped:
                        exec(compile(program, str(SOURCE), 'exec'), {})
            result = json.loads(output.getvalue())
            self.assertEqual(stopped.exception.code, 0 if result['status'] == 'native_main_check_passed' else 1)
            with socket.socket() as probe:
                probe.settimeout(0.2)
                self.assertNotEqual(probe.connect_ex(('127.0.0.1', port)), 0)
            self.assertNotIn(str(root), output.getvalue())
            if result['status'] == 'native_boot_unavailable':
                self.assertEqual(set(result), {'status', 'phase', 'code', 'errno', 'childExitCode', 'stdoutBytes', 'stderrBytes', 'serverLine'})
                for key in ('stdoutBytes', 'stderrBytes'):
                    self.assertTrue(0 <= result[key] <= 8192)
                if not measurements:
                    result = {key: result[key] for key in ('status', 'phase', 'code', 'errno')}
            return result

    def test_exact_program_subprocess_checks_http_authentication_and_stops(self):
        result = self.run_program(SERVER)
        self.assertEqual(result['status'], 'native_main_check_passed')
        self.assertTrue(result['mainProgramChecked'])
        self.assertTrue(result['serviceAuthChecked'])
        self.assertTrue(result['operatorAuthChecked'])
        self.assertFalse(result['productionQualified'])

    def test_startup_errors_are_classified_without_private_text(self):
        for script, code in [("raise ModuleNotFoundError('private-token /sensitive/path')", 'native_module_missing'),
                ("raise ValueError('private_host_secret_required')", 'private_host_secret_required'),
                ("raise ValueError('private-token /sensitive/path')", 'native_main_program_failed')]:
            with self.subTest(code=code):
                result = self.run_program(script)
                self.assertEqual(result, {'status': 'native_boot_unavailable', 'phase': 'main_program', 'code': code, 'errno': None})
                self.assertNotIn('private-token', json.dumps(result))
                self.assertNotIn('/sensitive', json.dumps(result))

    def test_deadline_stops_a_server_that_never_listens(self):
        result = self.run_program('import time; time.sleep(120)', timeout=0.2)
        self.assertEqual(result['code'], 'native_main_program_failed')

    def test_child_exception_classes_and_errno_hide_private_details(self):
        cases = [('NameError', 'native_main_name_error', None),
                 ('UnboundLocalError', 'native_main_name_error', None),
                 ('TypeError', 'native_main_type_error', None),
                 ('AttributeError', 'native_main_attribute_error', None),
                 ('PermissionError', 'native_main_permission_error', 13),
                 ('FileNotFoundError', 'native_main_file_missing', 2),
                 ('OSError', 'native_main_os_error', 98),
                 ('RuntimeError', 'native_main_runtime_error', None)]
        for kind, code, number in cases:
            with self.subTest(kind=kind):
                args = repr('private-token /sensitive/path')
                if number is not None:
                    args = str(number) + ', ' + args
                result = self.run_program('raise ' + kind + '(' + args + ')')
                self.assertEqual(result, {'status': 'native_boot_unavailable', 'phase': 'main_program',
                                         'code': code, 'errno': number})
                self.assertNotIn('private-token', json.dumps(result))
                self.assertNotIn('/sensitive', json.dumps(result))

    def test_child_errno_outside_receipt_range_is_discarded(self):
        result = self.run_program("raise OSError(9999, 'private-token /sensitive/path')")
        self.assertEqual(result['code'], 'native_main_os_error')
        self.assertIsNone(result['errno'])

    def test_socket_resolution_error_discards_private_text(self):
        result = self.run_program("import socket; raise socket.gaierror(-3, 'private-token /sensitive/path')")
        self.assertEqual(result, {'status': 'native_boot_unavailable', 'phase': 'main_program',
                                 'code': 'native_main_dns_error', 'errno': None})

    def test_silent_child_exit_has_bounded_numeric_evidence(self):
        result = self.run_program('import sys; sys.exit(7)', measurements=True)
        self.assertEqual(result['childExitCode'], 7)
        self.assertEqual((result['stdoutBytes'], result['stderrBytes']), (0, 0))

    def test_large_private_child_output_stops_at_receipt_limit(self):
        result = self.run_program("print('private-token' * 10000, flush=True)", measurements=True)
        self.assertLessEqual(result['stdoutBytes'], 8192)
        self.assertNotIn('private-token', json.dumps(result))

    def test_pinned_native_exception_uses_only_an_allowlisted_code(self):
        for message, expected in [('invalid_native_runtime', 'invalid_native_runtime'),
                                  ('private-token /sensitive/path', 'native_main_program_failed')]:
            script = "class NativeSearchError(ValueError): pass\nNativeSearchError.__module__ = 'community.native_scene_search'\nraise NativeSearchError(" + repr(message) + ')'
            result = self.run_program(script)
            self.assertEqual(result['code'], expected)
            self.assertNotIn('private-token', json.dumps(result))

    def test_only_immutable_server_frame_is_retained_as_a_number(self):
        script = "import sys; print('  File \"/opt/vision/server.py\", line 321, in main', file=sys.stderr); print('  File \"/private-token/sensitive.py\", line 987, in private', file=sys.stderr); sys.exit(1)"
        result = self.run_program(script, measurements=True)
        self.assertEqual(result['serverLine'], 321)
        self.assertNotIn('private-token', json.dumps(result))

    def test_hostname_encoding_fault_is_classified_without_private_text(self):
        result = self.run_program("raise UnicodeError('private-token /sensitive/path')")
        self.assertEqual(result['code'], 'native_main_hostname_encoding_error')
        self.assertNotIn('private-token', json.dumps(result))

    def test_incorrect_runtime_identity_is_rejected_and_server_is_stopped(self):
        result = self.run_program(SERVER.replace("'a'*64", "'b'*64"))
        self.assertEqual(result['phase'], 'http_self_check')
        self.assertEqual(result['code'], 'native_http_self_check_failed')

    def test_child_exiting_during_shutdown_keeps_verified_receipt(self):
        result = self.run_program(SERVER, exited_during_signal=True)
        self.assertEqual(result['status'], 'native_main_check_passed')

    def test_child_exiting_during_shutdown_preserves_original_failure(self):
        result = self.run_program('import time; time.sleep(120)', timeout=0.2, exited_during_signal=True)
        self.assertEqual(result['code'], 'native_main_program_failed')

if __name__ == '__main__': unittest.main()
