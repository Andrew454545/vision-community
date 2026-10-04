"""Per-user startup contract guards, without registering a computer task."""
from pathlib import Path
import tempfile
import unittest

from community.mac_launch_agent import agent_config, verify_loaded


class MacLaunchAgentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.python = self.root / 'private-python'
        self.entry = self.root / 'immutable-entry.py'
        self.python.write_bytes(b'finite path fixture')
        self.entry.write_bytes(b'finite entry fixture')

    def config(self, **kwargs):
        return agent_config(self.root, self.python, self.entry, home=self.root, **kwargs)

    def readback(self, config):
        return ('program = ' + config['ProgramArguments'][0] + '\narguments = {\n' +
            '\n'.join(config['ProgramArguments']) + '\n}\nrun interval = ' +
            str(config['StartInterval']) + ' seconds\n')

    def test_default_is_per_user_finite_recovery_without_rapid_keepalive_or_expiry(self):
        plan = self.config()
        self.assertEqual(plan['Label'], 'org.visioncommunity.background')
        self.assertEqual(plan['ProgramArguments'][1:3], ['-I', '-B'])
        arguments = plan['ProgramArguments']
        self.assertEqual(arguments[arguments.index('--root') + 1], str(self.root))
        self.assertEqual(arguments[arguments.index('--day-start') + 1], '06:00')
        self.assertEqual(arguments[arguments.index('--night-start') + 1], '00:00')
        self.assertEqual((plan['RunAtLoad'], plan['KeepAlive'], plan['StartInterval'], plan['ThrottleInterval']),
                         (True, False, 900, 300))
        self.assertEqual(plan['Umask'], 0o077)
        self.assertFalse(plan['AbandonProcessGroup'])
        self.assertNotIn('UserName', plan)
        self.assertNotIn('ExitTimeOut', plan)
        self.assertNotIn('LaunchOnlyOnce', plan)
        self.assertNotIn('Disabled', plan)
        self.assertEqual(plan['StandardOutPath'], '/dev/null')
        self.assertEqual(plan['StandardErrorPath'], '/dev/null')

    def test_invalid_settings_scope_or_recovery_credentials_never_enter_program_arguments(self):
        for options in ({'label': 'other.account'}, {'retry_minutes': 0}, {'retry_minutes': True},
                        {'storage_limit_gb': 4097}, {'prevent_sleep': 1}, {'schedule': {}},
                        {'label': 'org.visioncommunity.check.' + 'g' * 32}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.config(**options)
        with self.assertRaises(ValueError):
            agent_config(self.root, self.python, Path(__file__), home=self.root)
        self.assertNotIn('recoveryCode', str(self.config()))
        self.assertNotIn('--url', self.config()['ProgramArguments'])

    def test_allow_sleep_is_explicit_and_loaded_program_interval_and_arguments_must_match(self):
        plan = self.config(prevent_sleep=False)
        self.assertEqual(plan['ProgramArguments'][-1], '--no-keep-awake')
        text = self.readback(plan)
        verify_loaded(text, plan)
        for changed in (text.replace('900 seconds', '3 seconds'), text.replace('-I\n', ''),
                        text.replace('--root\n', '--url\n'), text + 'x' * 65537):
            with self.subTest(change=changed[-30:]), self.assertRaises(ValueError):
                verify_loaded(changed, plan)


if __name__ == '__main__':
    unittest.main()
