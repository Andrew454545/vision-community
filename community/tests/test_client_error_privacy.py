"""Fixed diagnostics for service, native and unexpected local errors."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from community.contribute import CommunityClient, ContributeError, service_error_code
from community.desktop import DesktopApp, DesktopClient, DesktopError, public_error
from community.vision_index import VisionIndexError


class ClientErrorPrivacyTests(unittest.TestCase):
    def test_shared_reports_never_copy_unknown_short_codes_or_private_paths(self):
        private = 'fixture-private-account-code'
        errors = (ContributeError(private, 503), VisionIndexError(private, 409),
                  DesktopError(private), OSError('/Users/Private Person/' + private),
                  ContributeError({'token': private}, 401),
                  ContributeError([private], 503))
        with tempfile.TemporaryDirectory() as folder:
            app = DesktopApp(Path(folder))
            for error in errors:
                with self.subTest(error_type=type(error).__name__):
                    app.record_failure(error)
                    raw = (app.root / 'desktop-failure.json').read_text(encoding='utf-8')
                    report = json.loads(raw)
                    self.assertEqual(report['code'], type(error).__name__)
                    self.assertEqual(report['error_type'], type(error).__name__)
                    self.assertNotIn(private, raw)
                    self.assertNotIn('Private Person', raw)
                    self.assertNotIn(private, public_error(error))
                    if getattr(error, 'status', None) in (401, 409, 503):
                        self.assertEqual(report['http_status'], error.status)

    def test_known_reports_retain_recognizable_reasons_without_exception_message(self):
        with tempfile.TemporaryDirectory() as folder:
            app = DesktopApp(Path(folder))
            for error in (ContributeError('expired_lease', 409),
                          VisionIndexError('indexer_no_progress'),
                          VisionIndexError('vision_binary_timeout'),
                          DesktopError('scene_verification_unavailable')):
                app.record_failure(error)
                report = json.loads((app.root / 'desktop-failure.json').read_text(encoding='utf-8'))
                self.assertEqual(report['code'], str(error))
                self.assertNotIn('message', report)

    def test_alternate_client_error_paths_use_fixed_fallbacks_and_http_status(self):
        client = CommunityClient('http://127.0.0.1:1')
        desktop = DesktopClient('http://127.0.0.1:1')
        for owner, action, fallback in (
            (client, lambda: client.lease('scene', 16, 'slow'), 'lease_failed'),
            (client, lambda: client.renew('a' * 32), 'renew_failed'),
            (client, lambda: client.authorize_local_search({}), 'search_failed'),
            (desktop, lambda: desktop.audit_submission('a' * 32), 'verification_failed'),
        ):
            target = CommunityClient if owner is desktop else owner
            with self.subTest(fallback=fallback), patch.object(target, 'request',
                    return_value=(409, {'error': {'private': 'fixture-private-account-code'}}, None)):
                with self.assertRaises(ContributeError) as caught:
                    action()
                self.assertEqual((caught.exception.code, caught.exception.status), (fallback, 409))

    def test_missing_and_structured_error_values_do_not_use_untrusted_fallback_text(self):
        for data in ({}, [], {'error': []}, {'error': 5}, {'error': 'future-unknown-code'}):
            self.assertEqual(service_error_code(data), 'http_error')
            self.assertEqual(service_error_code(data, 'fixture-private-account-code'), 'http_error')


if __name__ == '__main__':
    unittest.main()
