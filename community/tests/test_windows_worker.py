"""Entry point failures retain reports and never publish exception contents."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from community import windows_worker


class WindowsWorkerTests(unittest.TestCase):
    def test_non_windows_refuses_before_starting_worker(self):
        with patch.object(sys, 'platform', 'linux'), patch('community.background.main') as run:
            with self.assertRaisesRegex(RuntimeError, 'windows_required'):
                windows_worker.main()
            run.assert_not_called()

    def test_success_uses_the_existing_background_and_keeps_saved_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            account = root / 'account.json'
            account.write_text('existing private account', encoding='utf-8')
            with patch.object(sys, 'platform', 'win32'), patch.object(sys, 'argv', ['worker', '--root', folder]), patch('community.background.main') as run:
                self.assertEqual(windows_worker.main(), 0)
                run.assert_called_once_with()
            self.assertEqual(account.read_text(), 'existing private account')
            self.assertFalse((root / 'NEEDS-ATTENTION').exists())

    def test_startup_failure_preserves_previous_reports_and_account(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            account = root / 'account.json'
            account.write_text('private-account-token', encoding='utf-8')
            for _ in range(2):
                with patch.object(sys, 'platform', 'win32'), patch.object(sys, 'argv', ['worker', '--root', folder]), patch('community.background.main', side_effect=RuntimeError('private-account-token native-output')):
                    self.assertEqual(windows_worker.main(), 1)
            reports = list((root / 'setup-failures').glob('*.json'))
            self.assertEqual(len(reports), 2)
            for report in reports:
                body = report.read_text()
                self.assertNotIn('private-account-token', body)
                self.assertNotIn('native-output', body)
                self.assertNotIn(folder, body)
                self.assertEqual(json.loads(body)['errorType'], 'RuntimeError')
            self.assertTrue((root / 'NEEDS-ATTENTION').is_file())
            self.assertEqual(account.read_text(), 'private-account-token')


if __name__ == '__main__':
    unittest.main()
