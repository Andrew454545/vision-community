"""Signing automation fails closed and cannot publish a download."""
from pathlib import Path
import sys
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'packaging'))
from signing_preflight import REQUIRED, main, missing


class SigningPreflightTests(unittest.TestCase):
    def complete(self, platform):
        values = {name: 'configured' for name in REQUIRED[platform]}
        values['MAC_SIGNING_IDENTITY'] = 'Developer ID Application: Example (TEAM123456)'
        values['ARTIFACT_SIGNING_ENDPOINT'] = 'https://eus.codesigning.azure.net/'
        return values

    def test_every_missing_or_blank_setting_is_named_without_values(self):
        for platform, names in REQUIRED.items():
            self.assertEqual(missing(platform, {}), list(names))
            values = self.complete(platform)
            self.assertEqual(missing(platform, values), [])
            for name in names:
                self.assertEqual(missing(platform, {**values, name: '  '}), [name])

    def test_wrong_identity_kind_and_insecure_endpoint_are_refused(self):
        values = self.complete('mac')
        self.assertTrue(missing('mac', {**values, 'MAC_SIGNING_IDENTITY': 'Apple Development: Example'}))
        values = self.complete('windows')
        self.assertTrue(missing('windows', {**values, 'ARTIFACT_SIGNING_ENDPOINT': 'http://example.invalid'}))

    def test_command_exit_codes(self):
        self.assertEqual(main(['signing_preflight.py']), 2)
        self.assertEqual(main(['signing_preflight.py', 'linux']), 2)

    def test_signing_workflow_is_manual_gated_and_never_publishes(self):
        text = (ROOT / '.github/workflows/signed-candidates.yml').read_text(encoding='utf-8')
        triggers = text[text.index('\non:\n') + 5:text.index('\npermissions:')]
        self.assertEqual(triggers.split(), ['workflow_dispatch:'])
        self.assertIn('\npermissions:\n  contents: read\njobs:', text)
        jobs = re.split(r'\n  (?=[a-z-]+:\n)', text[text.index('\njobs:\n') + 7:].strip())
        self.assertEqual([job.split(':')[0] for job in jobs], ['mac-signed', 'windows-signed'])
        for job in jobs:
            self.assertIn('environment: signing', job)
            # Preflight runs before any credential is loaded or used.
            self.assertLess(job.index('signing_preflight.py'), min(job.index(word) for word in ('Prepare-Signing.sh', 'azure/login') if word in job))
            self.assertEqual(job.count('actions/upload-artifact'), 1)
            self.assertIn('retention-days: 7', job)
            # Only the Azure federated sign-in token may be requested.
            self.assertIn(re.findall(r'([\w-]+): write', job), ([], ['id-token']))
        for forbidden in ('gh release', 'softprops', 'releases/download', 'xattr -d', 'spctl --master-disable', 'ExecutionPolicy', 'pull_request'):
            self.assertNotIn(forbidden, text)


if __name__ == '__main__':
    unittest.main()
