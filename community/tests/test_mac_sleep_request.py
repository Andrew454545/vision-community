"""Mac idle-sleep ownership: API guards plus finite real macOS assertions.

No models, imagery, service, accounts or persistent power settings are used.
Only the fixture caller's VISION assertions are inspected; other applications'
assertions are neither retained nor printed.
"""
import ctypes
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from community import background
from community.desktop import DesktopError

REPO = Path(__file__).resolve().parents[2]
NAME = 'VISION Community processing'
TYPE = 'PreventUserIdleSystemSleep'


class MacSleepGuards(unittest.TestCase):
    def api(self, *, result=0, token=73, strings=(11, 12), released=0):
        cf, io = Mock(), Mock()
        cf.CFStringCreateWithCString.side_effect = strings
        def create(*args):
            args[-1]._obj.value = token
            return result
        io.IOPMAssertionCreateWithDescription.side_effect = create
        io.IOPMAssertionRelease.return_value = released
        return cf, io

    def test_native_request_uses_system_frameworks_idle_only_and_no_timeout(self):
        cf, io = self.api(token=0)  # IOPMAssertionID is an opaque uint32, not a pointer.
        with patch.object(ctypes, 'CDLL', side_effect=[cf, io]) as load:
            request = background._MacSleepRequest()
        self.assertEqual([c.args[0] for c in load.call_args_list], [
            '/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation',
            '/System/Library/Frameworks/IOKit.framework/IOKit'])
        self.assertEqual([c.args[1:] for c in cf.CFStringCreateWithCString.call_args_list],
            [(TYPE.encode(), 0x08000100), (NAME.encode(), 0x08000100)])
        self.assertEqual(io.IOPMAssertionCreateWithDescription.call_args.args[:-1],
            (11, 12, None, None, None, 0.0, None))
        self.assertEqual([c.args[0] for c in cf.CFRelease.call_args_list], [12, 11])
        self.assertEqual(io.IOPMAssertionCreateWithDescription.argtypes[-1], ctypes.POINTER(ctypes.c_uint32))
        self.assertIs(io.IOPMAssertionCreateWithDescription.restype, ctypes.c_int32)
        self.assertEqual(io.IOPMAssertionRelease.argtypes, [ctypes.c_uint32])
        request.close()
        request.close()
        io.IOPMAssertionRelease.assert_called_once_with(0)

    def test_creation_denial_frees_strings_without_claiming_an_assertion(self):
        cf, io = self.api(result=-536870206)
        with patch.object(ctypes, 'CDLL', side_effect=[cf, io]), self.assertRaises(OSError):
            background._MacSleepRequest()
        self.assertEqual(cf.CFRelease.call_count, 2)
        io.IOPMAssertionRelease.assert_not_called()

    def test_string_allocation_denial_releases_only_completed_allocations(self):
        for strings, expected in (((0,), []), ((11, 0), [11])):
            with self.subTest(strings=strings):
                cf, io = self.api(strings=strings)
                with patch.object(ctypes, 'CDLL', side_effect=[cf, io]), self.assertRaises(OSError):
                    background._MacSleepRequest()
                self.assertEqual([c.args[0] for c in cf.CFRelease.call_args_list], expected)
                io.IOPMAssertionCreateWithDescription.assert_not_called()

    def test_release_denial_is_preserved_and_the_same_token_is_never_reused(self):
        cf, io = self.api(released=-536870206)
        with patch.object(ctypes, 'CDLL', side_effect=[cf, io]):
            request = background._MacSleepRequest()
        with self.assertRaisesRegex(OSError, 'keep_awake_release_failed'):
            request.close()
        request.close()
        io.IOPMAssertionRelease.assert_called_once_with(73)

    def test_mac_context_releases_when_native_work_fails(self):
        request = Mock()
        original = RuntimeError('finite indexing fixture failed')
        with patch.object(background, 'os', SimpleNamespace(name='posix')), \
             patch.object(background.sys, 'platform', 'darwin'), \
             patch.object(background, '_MacSleepRequest', return_value=request):
            with self.assertRaises(RuntimeError) as caught:
                with background.keep_awake():
                    raise original
        self.assertIs(caught.exception, original)
        request.close.assert_called_once()

    def test_mac_request_failure_stops_before_work_and_hides_private_os_text(self):
        for error in (OSError('PRIVATE details'), AttributeError('PRIVATE API')):
            with self.subTest(error=type(error).__name__), \
                 patch.object(background, 'os', SimpleNamespace(name='posix')), \
                 patch.object(background.sys, 'platform', 'darwin'), \
                 patch.object(background, '_MacSleepRequest', side_effect=error):
                with self.assertRaisesRegex(DesktopError, '^keep_awake_failed$'):
                    with background.keep_awake():
                        self.fail('Indexing must not start after a denied sleep request')

    def test_mac_release_failure_stops_with_fixed_diagnostic(self):
        request = Mock()
        request.close.side_effect = OSError('PRIVATE release details')
        with patch.object(background, 'os', SimpleNamespace(name='posix')), \
             patch.object(background.sys, 'platform', 'darwin'), \
             patch.object(background, '_MacSleepRequest', return_value=request):
            with self.assertRaisesRegex(DesktopError, '^keep_awake_release_failed$'):
                with background.keep_awake():
                    pass
        request.close.assert_called_once()

    def test_allow_sleep_never_loads_frameworks(self):
        with patch.object(background, 'os', SimpleNamespace(name='posix')), \
             patch.object(background.sys, 'platform', 'darwin'), \
             patch.object(background, '_MacSleepRequest') as create:
            with background.keep_awake(False):
                pass
        create.assert_not_called()


def assertions_for(pid):
    """Read back only this finite fixture process's matching assertions."""
    cf = ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
    io = ctypes.CDLL('/System/Library/Frameworks/IOKit.framework/IOKit')
    pointer = ctypes.c_void_p
    signatures = {
        'CFRelease': ([pointer], None),
        'CFNumberCreate': ([pointer, ctypes.c_long, pointer], pointer),
        'CFDictionaryGetValue': ([pointer, pointer], pointer),
        'CFPropertyListCreateData': ([pointer, pointer, ctypes.c_long, ctypes.c_ulong, ctypes.POINTER(pointer)], pointer),
        'CFDataGetLength': ([pointer], ctypes.c_ssize_t),
        'CFDataGetBytePtr': ([pointer], pointer),
    }
    for name, (args, result) in signatures.items():
        function = getattr(cf, name)
        function.argtypes, function.restype = args, result
    io.IOPMCopyAssertionsByProcess.argtypes = [ctypes.POINTER(pointer)]
    io.IOPMCopyAssertionsByProcess.restype = ctypes.c_int32
    table, error = pointer(), pointer()
    key = data = None
    try:
        if io.IOPMCopyAssertionsByProcess(ctypes.byref(table)) != 0 or not table:
            raise AssertionError('Could not read Mac assertion ownership')
        owner = ctypes.c_int32(pid)
        key = cf.CFNumberCreate(None, 3, ctypes.byref(owner))  # kCFNumberSInt32Type.
        if not key:
            raise AssertionError('Could not create finite assertion owner key')
        array = cf.CFDictionaryGetValue(table, key)
        if not array:
            return []
        data = cf.CFPropertyListCreateData(None, array, 200, 0, ctypes.byref(error))
        if not data:
            raise AssertionError('Could not inspect finite assertion receipt')
        length = cf.CFDataGetLength(data)
        if not 0 < length <= 1024 * 1024:
            raise AssertionError('Unexpected finite assertion receipt size')
        values = plistlib.loads(ctypes.string_at(cf.CFDataGetBytePtr(data), length))
        return [value for value in values if value.get('AssertName') == NAME and value.get('AssertType') == TYPE]
    finally:
        for value in (data, key, error, table):
            if value:
                cf.CFRelease(value)


def wait_for_count(pid, expected):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        found = assertions_for(pid)
        if len(found) == expected:
            return found
        time.sleep(.05)
    raise AssertionError('macOS did not confirm the expected finite assertion count')


@unittest.skipUnless(sys.platform == 'darwin', 'Actual macOS idle-sleep assertions')
class ActualMacSleepRequests(unittest.TestCase):
    def test_actual_nested_assertions_release_separately_after_body_failure(self):
        baseline = len(assertions_for(os.getpid()))
        with background.keep_awake():
            self.assertTrue(all(value['AssertLevel'] == 255 for value in wait_for_count(os.getpid(), baseline + 1)))
            with self.assertRaisesRegex(RuntimeError, 'finite work interruption'):
                with background.keep_awake():
                    self.assertTrue(all(value['AssertLevel'] == 255 for value in wait_for_count(os.getpid(), baseline + 2)))
                    raise RuntimeError('finite work interruption')
            wait_for_count(os.getpid(), baseline + 1)
        wait_for_count(os.getpid(), baseline)

    def test_actual_abrupt_caller_exit_releases_assertion_and_preserves_work(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            saved = root / 'saved-work'
            saved.write_bytes(b'unchanged finite checkpoint')
            code = ('import sys; from pathlib import Path; '
                    f'sys.path.insert(0,{str(REPO)!r}); '
                    'from community.background import keep_awake; '
                    'request=keep_awake(); request.__enter__(); '
                    f'Path({str(root / "ready")!r}).write_bytes(b"ready"); '
                    'sys.stdin.buffer.read(1)')
            child = subprocess.Popen([sys.executable, '-I', '-B', '-c', code],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                deadline = time.monotonic() + 10
                while not (root / 'ready').exists() and time.monotonic() < deadline and child.poll() is None:
                    time.sleep(.05)
                self.assertTrue((root / 'ready').exists(), 'Finite Mac assertion caller did not start')
                receipt = wait_for_count(child.pid, 1)
                self.assertEqual(receipt[0]['AssertLevel'], 255)
                child.kill()  # SIGKILL: deliberately bypass the context manager.
                child.wait(timeout=10)
                wait_for_count(child.pid, 0)
                self.assertEqual(saved.read_bytes(), b'unchanged finite checkpoint')
            finally:
                child.stdin.close()
                if child.poll() is None:
                    child.kill()
                child.wait(timeout=10)


if __name__ == '__main__':
    unittest.main()
