"""Compile and exercise the fixed offline launch diagnostic; no models/network."""
import builtins
import contextlib
import io
import json
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
    def run_program(self, *, failure=None, import_failure=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'runtime-package.json').write_text(json.dumps({'runtimeSha256': 'a' * 64}))
            native = types.ModuleType('server')
            native.native = types.SimpleNamespace(strict_json=json.loads)
            native.Host = Mock(side_effect=failure)
            native.make_server = Mock()
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
                if failure or import_failure:
                    with self.assertRaises(SystemExit) as stopped:
                        exec(compile(PROGRAM, str(SOURCE), 'exec'), {})
                    self.assertEqual(stopped.exception.code, 1)
                else:
                    exec(compile(PROGRAM, str(SOURCE), 'exec'), {})
            native.make_server.assert_not_called()
            return json.loads(output.getvalue()), native

    def test_success_checks_the_runtime_without_starting_a_service(self):
        result, module = self.run_program()
        self.assertEqual(result, {'status': 'native_launch_check_passed', 'runtimeSha256': 'a' * 64,
                                 'pythonVersion': '3.12.15', 'uid': 10001,
                                 'modelFilesValidated': True, 'productionQualified': False})
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


if __name__ == '__main__':
    unittest.main()
