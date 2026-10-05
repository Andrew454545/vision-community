"""Real control helpers and form, using a disposable folder and mock scheduler."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from community.tests.test_windows_launcher import POWERSHELL, REPO, ps_string


CONTROL = REPO / 'windows/Background-Control.ps1'


@unittest.skipUnless(sys.platform == 'win32', 'Windows background controls')
class BackgroundControlTests(unittest.TestCase):
    def command(self, code, *, expected=0):
        result = subprocess.run([str(POWERSHELL), '-NoProfile', '-STA', '-Command',
            "$ErrorActionPreference='Stop'; . " + ps_string(CONTROL) + '; ' + code],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result.stdout.strip()

    def task(self, root, state='Running'):
        arguments = '-B "' + str(root / 'launchers/entry.py') + '" --root "' + str(root) + '" --accept-contributions'
        return ("function Get-ScheduledTask { [pscustomobject]@{Principal=[pscustomobject]@{UserId=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value};State=" + ps_string(state) +
                ";Actions=@([pscustomobject]@{Execute='C:\\private\\pythonw.exe';Arguments=" + ps_string(arguments) + '})} }; ')

    def test_controls_do_not_treat_old_processing_status_as_a_running_worker(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'background-status.json').write_text(json.dumps({'state': 'processing', 'updatedAt': '2026-09-01T00:00:00Z'}))
            status = self.command(self.task(root, 'Ready') + 'Get-VisionControlStatus ' + ps_string(root))
            self.assertIn('not running now', status)
            self.assertNotIn('Processing a batch', status)
            status = self.command(self.task(root) + 'Get-VisionControlStatus ' + ps_string(root))
            self.assertIn('Processing a batch', status)
            self.assertIn('Last saved report:', status)
            self.assertNotIn('healthy', status)

    def test_all_worker_states_have_plain_explanations(self):
        states = ('running', 'processing', 'preparing', 'checking_pc', 'paused', 'waiting_for_schedule',
                  'waiting_for_work', 'waiting_for_service', 'waiting_for_verification',
                  'retrying_indexing', 'waiting_for_space', 'needs_attention', 'stopped')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            values = {}
            for state in states:
                (root / (state + '.json')).write_text(json.dumps({'state': state, 'updatedAt': '2026-09-01T00:00:00Z'}))
            code = self.task(root) + '$values=@{}; '
            for state in states:
                code += '[IO.File]::Copy(' + ps_string(root / (state + '.json')) + ', ' + ps_string(root / 'background-status.json') + ', $true); '
                code += '$values[' + ps_string(state) + ']=Get-VisionControlStatus ' + ps_string(root) + '; '
            values = json.loads(self.command(code + '$values | ConvertTo-Json -Compress'))
            for state, message in values.items():
                self.assertIn('Last saved report:', message)
                self.assertNotIn('A saved progress report needs review', message)
            self.assertIn('retries automatically', values['waiting_for_service'])
            self.assertIn('saved failure needs review', values['needs_attention'])

    def test_pause_preserves_work_and_resume_requests_start_only_for_its_task(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'checkpoint.json').write_text('checkpoint')
            marker = root / 'start-request'
            mock = self.task(root) + 'function Start-ScheduledTask { [IO.File]::WriteAllText(' + ps_string(marker) + ", 'requested') }; "
            self.command(mock + 'Set-VisionControlPause ' + ps_string(root) + ' $true')
            self.assertTrue((root / 'PAUSE').exists())
            self.assertFalse(marker.exists())
            self.command(mock + 'Set-VisionControlPause ' + ps_string(root) + ' $false')
            self.assertFalse((root / 'PAUSE').exists())
            self.assertTrue(marker.exists())
            self.assertEqual((root / 'checkpoint.json').read_text(), 'checkpoint')

    def test_resume_cannot_clear_failure_or_installer_stop(self):
        for name in ('NEEDS-ATTENTION', 'STOP-AFTER-BATCH'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                (root / name).write_text('preserved')
                (root / 'PAUSE').write_text('preserved pause')
                mock = self.task(root) + "function Start-ScheduledTask { throw 'must not start' }; "
                self.command(mock + 'Set-VisionControlPause ' + ps_string(root) + ' $false', expected=1)
                self.assertEqual((root / name).read_text(), 'preserved')
                self.assertEqual((root / 'PAUSE').read_text(), 'preserved pause')

    def test_other_root_and_unrelated_tasks_are_not_controlled(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            other = root / 'other'
            for code in (self.task(other), "function Get-ScheduledTask { [pscustomobject]@{Actions=@([pscustomobject]@{Execute='unrelated.exe';Arguments='--root \"x\"'})} }; "):
                self.command(code + 'Set-VisionControlPause ' + ps_string(root) + ' $true', expected=1)
                self.assertFalse((root / 'PAUSE').exists())
            # Hosted Windows can supply RUNNER~1 for an existing parent while
            # PowerShell returns runneradmin. Compare filesystem identities.
            self.assertEqual(Path(self.command(self.task(other) + 'Get-VisionControlRoot')).resolve(), other.resolve())
            self.command(self.task(other) + 'Get-VisionControlRoot ' + ps_string(root), expected=1)

    def test_saved_account_is_written_once_without_console_disclosure(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "worker's folder"
            code = 'private synthetic code'
            output = self.command('Save-VisionControlAccount ' + ps_string(root) + ' ' + ps_string(code))
            self.assertNotIn(code, output)
            original = (root / 'account.json').read_bytes()
            self.command('Save-VisionControlAccount ' + ps_string(root) + " 'different code'")
            self.assertEqual((root / 'account.json').read_bytes(), original)
            self.assertEqual(json.loads(original)['recoveryCode'], code)
            self.assertEqual(list(root.glob('account-*.tmp')), [])

    def test_control_cannot_replace_another_service_account_or_reconfigure_its_task(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            original = json.dumps({'url': 'https://staging.example', 'recoveryCode': 'private synthetic code'}).encode()
            (root / 'account.json').write_bytes(original)
            self.command('Save-VisionControlAccount ' + ps_string(root) + " 'replacement'", expected=1)
            self.assertEqual((root / 'account.json').read_bytes(), original)
            mock = self.task(root).replace('--accept-contributions', '--accept-contributions --url https://staging.example')
            self.command(mock + 'Set-VisionControlPause ' + ps_string(root) + ' $true', expected=1)
            self.assertFalse((root / 'PAUSE').exists())

    def test_status_input_is_bounded_and_invalid_json_does_not_claim_health(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / 'background-status.json'
            for invalid in (b'x' * 65537, b'[]', b'"processing"', b'null', b'{', b'{"x":"\xff"}'):
                path.write_bytes(invalid)
                self.command(self.task(root) + 'Get-VisionControlStatus ' + ps_string(root), expected=1)

    def test_native_form_constructs_without_showing_or_starting_work(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            code = ("function Get-ScheduledTask { $null }; function Start-ScheduledTask { throw 'must not start' }; "
                    "$NoWindow=$true; $form = Show-VisionBackgroundControl " + ps_string(root) + '; '
                    "function Read-Controls($c) { foreach($child in $c.Controls) { $child; Read-Controls $child } }; "
                    "$controls=@(Read-Controls $form); @{visible=$form.Visible;buttons=@($controls | Where-Object { $_ -is [Windows.Forms.Button] } | ForEach-Object Text); "
                    "times=@($controls | Where-Object { $_ -is [Windows.Forms.DateTimePicker] } | ForEach-Object { $_.Value.ToString('HH:mm') }); "
                    "choices=@($controls | Where-Object { $_ -is [Windows.Forms.ComboBox] } | ForEach-Object { @{name=$_.AccessibleName;value=$_.Text;items=@($_.Items)} })} | ConvertTo-Json -Depth 6 -Compress; $form.Dispose()")
            ui = json.loads(self.command(code))
            self.assertFalse(ui['visible'])
            self.assertEqual(ui['times'], ['06:00', '00:00'])
            choices = {choice['name']: choice for choice in ui['choices']}
            self.assertEqual(choices['Work to process']['value'], 'Scenes')
            self.assertEqual(choices['Work to process']['items'], ['Scenes', 'Objects', 'Both - one batch at a time'])
            self.assertEqual(choices['Day processing speed']['value'], 'Medium')
            self.assertEqual(choices['Night processing speed']['value'], 'Maximum')
            for label in ('Save and enable', 'Pause after batch', 'Resume', 'Check status', 'Open saved files'):
                self.assertIn(label, ui['buttons'])
            self.assertFalse((root / 'account.json').exists())


if __name__ == '__main__':
    unittest.main()
