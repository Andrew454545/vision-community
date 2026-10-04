"""OS-request failures must stop work, preserve reports and release thread state."""
import ctypes
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from community import background
from community.desktop import DesktopApp, DesktopError


class SleepRequestTests(unittest.TestCase):
    def test_success_restores_previous_thread_flags_without_forcing_display_or_away_mode(self):
        for previous in (0x80000000, 0x80000001, 0x80000003):
            with self.subTest(previous=previous), patch.object(background,'os',SimpleNamespace(name='nt')), \
                 patch.object(background,'_sleep_state',side_effect=[previous,0x80000001]) as setter:
                with background.keep_awake():
                    setter.assert_called_once_with(0x80000001)
                self.assertEqual([c.args[0] for c in setter.call_args_list],[0x80000001,previous])

    def test_body_exception_still_releases_and_keeps_original_failure(self):
        error = RuntimeError('unit indexing interrupted')
        with patch.object(background,'os',SimpleNamespace(name='nt')), \
             patch.object(background,'_sleep_state',side_effect=[0x80000000,0x80000001]) as setter:
            with self.assertRaises(RuntimeError) as caught:
                with background.keep_awake(): raise error
            self.assertIs(caught.exception,error)
            self.assertEqual([c.args[0] for c in setter.call_args_list],[0x80000001,0x80000000])

    def test_request_denial_or_api_failure_never_enters_indexing(self):
        for failure in (0, OSError('private OS error'), AttributeError('missing API')):
            with self.subTest(failure=failure), patch.object(background,'os',SimpleNamespace(name='nt')), \
                 patch.object(background,'_sleep_state',side_effect=failure if isinstance(failure,Exception) else None,
                              return_value=failure) as setter:
                with self.assertRaisesRegex(DesktopError,'keep_awake_failed'):
                    with background.keep_awake(): self.fail('native work must not start')
                setter.assert_called_once_with(0x80000001)

    def test_release_denial_keeps_body_failure_as_context_and_does_not_claim_success(self):
        original = RuntimeError('unit native failure preserved as context')
        for release in (0, OSError('private release details')):
            with self.subTest(release=release), patch.object(background,'os',SimpleNamespace(name='nt')), \
                 patch.object(background,'_sleep_state',side_effect=[0x80000000,release]):
                with self.assertRaisesRegex(DesktopError,'keep_awake_release_failed') as caught:
                    with background.keep_awake(): raise original
                # The OS request's fixed error never includes raw native/private text.
                self.assertNotIn('private',str(caught.exception))
                if release == 0: self.assertIs(caught.exception.__context__,original)

    def test_disabled_or_nonwindows_never_calls_windows_api(self):
        for enabled, platform in ((False,'nt'), (True,'posix')):
            with self.subTest(enabled=enabled,platform=platform), patch.object(background,'os',SimpleNamespace(name=platform)), \
                 patch.object(background,'_sleep_state') as setter:
                with background.keep_awake(enabled): pass
                setter.assert_not_called()

    def test_execution_state_uses_unsigned_32_bit_windows_signature(self):
        setter = Mock(return_value=0x80000000)
        with patch.object(ctypes,'windll',SimpleNamespace(kernel32=SimpleNamespace(SetThreadExecutionState=setter)),create=True):
            self.assertEqual(background._sleep_state(0x80000001),0x80000000)
        self.assertEqual(setter.argtypes,[ctypes.c_uint32])
        self.assertIs(setter.restype,ctypes.c_uint32)
        setter.assert_called_once_with(0x80000001)

    def test_step_sleep_failure_stops_without_retry_or_new_indexing(self):
        for code in background.SLEEP_REQUEST_ERRORS:
            with self.subTest(code=code),tempfile.TemporaryDirectory() as folder:
                worker = background.BackgroundContributor(Path(folder))
                worker.step = Mock(side_effect=DesktopError(code))
                worker.wait = Mock()
                with patch.object(worker.app,'indexer') as indexer:
                    worker.run()
                indexer.assert_not_called()
                worker.step.assert_called_once()
                worker.wait.assert_not_called()
                self.assertTrue((worker.root/'NEEDS-ATTENTION').is_file())
                report = json.loads((worker.root/'desktop-failure.json').read_text())
                self.assertEqual(report['code'],code)
                status = json.loads((worker.root/'background-status.json').read_text())
                self.assertEqual(status['state'],'needs_attention')
                self.assertTrue(status['idleSleepPreventionRequested'])
                self.assertNotIn('preventsIdleSleepWhileWorking',status)
                self.assertFalse((worker.root/'background-retry.json').exists())

    def test_pacing_sleep_failure_retains_completed_work_and_exits_without_another_batch(self):
        for code in background.SLEEP_REQUEST_ERRORS:
            with self.subTest(code=code), tempfile.TemporaryDirectory() as folder:
                worker = background.BackgroundContributor(Path(folder))
                worker.completed = 16
                evidence = worker.root/'completed-unit-work.json'
                evidence.write_bytes(b'preserve completed unit output')
                worker.step = Mock(return_value=30)
                worker.wait = Mock(side_effect=DesktopError(code))
                worker.run()
                worker.step.assert_called_once()
                worker.wait.assert_called_once()
                self.assertEqual(evidence.read_bytes(),b'preserve completed unit output')
                self.assertEqual(json.loads((worker.root/'background-status.json').read_text())['acceptedThisRun'],16)
                self.assertEqual(json.loads((worker.root/'desktop-failure.json').read_text())['code'],code)
                self.assertTrue((worker.root/'NEEDS-ATTENTION').is_file())


if __name__=='__main__': unittest.main()
