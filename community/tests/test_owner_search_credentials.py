import ctypes
import io
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from community.owner_search_agent import HTTPSCoordinator, OwnerSearchError
from community import owner_search_credentials as vault

ORIGIN = 'https://coordinator.example'
SECRET = 'a' * 64


class OwnerSearchCredentialTests(unittest.TestCase):
    def test_scope_is_exact_canonical_https_origin_and_invalid_origins_never_read_os_vault(self):
        self.assertEqual(vault.credential_target(ORIGIN), vault.credential_target('https://COORDINATOR.example:443/'))
        self.assertNotEqual(vault.credential_target(ORIGIN), vault.credential_target('https://other.example'))
        self.assertTrue(vault.credential_target(ORIGIN).startswith(vault.PREFIX))
        with patch.object(vault, '_windows_read') as windows, patch.object(vault, '_mac_read') as mac:
            for invalid in ['http://coordinator.example', 'https://owner:SECRET@coordinator.example',
                            'https://coordinator.example:444', 'https://coordinator.example:PRIVATE',
                            'https://coordinator.example/private', 'https://coordinator.example?secret=PRIVATE',
                            'https://coordinator.example#PRIVATE', 'https://coordinator.example.',
                            '\nhttps://coordinator.example', 'https://@coordinator.example',
                            'https://:@coordinator.example',
                            'https://coordinator..example', 'https://-coordinator.example',
                            'https://☃.example', 'https://[::1]', None, {}]:
                with self.assertRaisesRegex(vault.OwnerCredentialError, '^invalid_owner_origin$'):
                    vault.read_owner_search_secret(invalid)
            windows.assert_not_called(); mac.assert_not_called()

    def test_missing_locked_or_malformed_secrets_have_no_plaintext_or_environment_fallback(self):
        with patch.object(vault.sys, 'platform', 'win32'):
            for value in [None, '', SECRET + '\n', 'A' * 64, 'not a secret', {'token': SECRET}]:
                with patch.object(vault, '_windows_read', return_value=value) as read:
                    with self.assertRaisesRegex(vault.OwnerCredentialError, '^owner_credentials_unavailable$'):
                        vault.read_owner_search_secret(ORIGIN)
                    read.assert_called_once_with(vault.credential_target(ORIGIN))
            with patch.object(vault, '_windows_read', side_effect=PermissionError('PRIVATE native path and secret')):
                with self.assertRaisesRegex(vault.OwnerCredentialError, '^owner_credentials_unavailable$'):
                    vault.read_owner_search_secret(ORIGIN)
        with patch.object(vault.sys, 'platform', 'linux'), patch.object(vault, '_windows_read') as read:
            with self.assertRaises(vault.OwnerCredentialError): vault.read_owner_search_secret(ORIGIN)
            read.assert_not_called()

    def fake_windows(self, raw, **changes):
        target = vault.credential_target(ORIGIN)
        blob = (ctypes.c_ubyte * max(1, len(raw))).from_buffer_copy(raw or b'\0')
        credential = vault._Credential(Type=1, TargetName=target, UserName=vault.ACCOUNT,
                                       CredentialBlobSize=len(raw), CredentialBlob=blob, Persist=2)
        for name, value in changes.items(): setattr(credential, name, value)
        def read(name, kind, flags, output):
            self.assertEqual((name, kind, flags), (target, 1, 0))
            ctypes.cast(output, ctypes.POINTER(ctypes.POINTER(vault._Credential)))[0] = ctypes.pointer(credential)
            return 1
        api = SimpleNamespace(CredReadW=MagicMock(side_effect=read), CredFree=MagicMock())
        return api, credential, blob

    def test_windows_generic_unicode_and_ascii_credentials_are_bounded_and_native_memory_freed(self):
        for raw in [SECRET.encode('ascii'), SECRET.encode('utf-16-le')]:
            api, credential, blob = self.fake_windows(raw)
            with patch.object(vault.ctypes, 'WinDLL', return_value=api, create=True), patch.object(vault.sys, 'platform', 'win32'):
                self.assertEqual(vault.read_owner_search_secret(ORIGIN), SECRET)
            api.CredReadW.assert_called_once(); api.CredFree.assert_called_once()
            self.assertEqual(ctypes.sizeof(credential), 80 if ctypes.sizeof(ctypes.c_void_p) == 8 else 52)

    def test_windows_wrong_owner_target_type_or_oversize_never_return_secret_and_always_free(self):
        for changes in [{'Type':2}, {'TargetName':'unrelated-credential'}, {'UserName':'unrelated-user'},
                        {'CredentialBlobSize':1000000}, {'CredentialBlob':ctypes.POINTER(ctypes.c_ubyte)()}]:
            api, credential, blob = self.fake_windows(SECRET.encode(), **changes)
            with patch.object(vault.ctypes, 'WinDLL', return_value=api, create=True), patch.object(vault.sys, 'platform', 'win32'):
                with self.assertRaisesRegex(vault.OwnerCredentialError, '^owner_credentials_unavailable$'):
                    vault.read_owner_search_secret(ORIGIN)
            api.CredFree.assert_called_once()

    def test_windows_denial_does_not_dereference_or_free_a_missing_result(self):
        api = SimpleNamespace(CredReadW=MagicMock(return_value=0), CredFree=MagicMock())
        with patch.object(vault.ctypes, 'WinDLL', return_value=api, create=True), patch.object(vault.sys, 'platform', 'win32'):
            with self.assertRaises(vault.OwnerCredentialError): vault.read_owner_search_secret(ORIGIN)
        api.CredFree.assert_not_called()

    def fake_mac(self, raw, status=0):
        process = SimpleNamespace(stdout=io.BytesIO(raw), wait=MagicMock(return_value=status),
                                  poll=MagicMock(return_value=status), kill=MagicMock())
        timer = MagicMock()
        return process, timer

    def test_mac_reads_one_exact_login_keychain_item_without_credential_arguments_or_environment(self):
        for suffix in [b'', b'\n', b'\r\n']:
            process, timer = self.fake_mac(SECRET.encode() + suffix)
            with patch.object(vault.sys, 'platform', 'darwin'), patch.object(vault.subprocess, 'Popen', return_value=process) as popen, \
                    patch.object(vault.threading, 'Timer', return_value=timer) as timer_factory:
                self.assertEqual(vault.read_owner_search_secret(ORIGIN), SECRET)
                command, options = popen.call_args.args[0], popen.call_args.kwargs
                self.assertEqual(command[:7], ['/usr/bin/security','find-generic-password','-s',vault.credential_target(ORIGIN),'-a',vault.ACCOUNT,'-w'])
                self.assertTrue(command[-1].replace('\\','/').endswith('/Library/Keychains/login.keychain-db'))
                self.assertEqual(options['env'], {'PATH':'/usr/bin:/bin','LANG':'C'})
                self.assertFalse(options['shell']); self.assertEqual(options['stderr'], vault.subprocess.DEVNULL)
                self.assertNotIn(SECRET, repr(command) + repr(options))
                self.assertEqual(timer_factory.call_args.args[0], 10)
                timer.start.assert_called_once(); timer.cancel.assert_called_once()
            self.assertTrue(process.stdout.closed)

    def test_mac_oversize_denial_or_nonhex_does_not_echo_secret_and_closes_private_pipe(self):
        for raw, status in [(SECRET.encode() + b'extra', 0), (SECRET.encode(), 44), (b'PRIVATE STDERR secret', 0), (b'\n'+SECRET.encode()+b'\n',0)]:
            process, timer = self.fake_mac(raw, status)
            with patch.object(vault.sys, 'platform', 'darwin'), patch.object(vault.subprocess, 'Popen', return_value=process), \
                    patch.object(vault.threading, 'Timer', return_value=timer):
                with self.assertRaisesRegex(vault.OwnerCredentialError, '^owner_credentials_unavailable$'):
                    vault.read_owner_search_secret(ORIGIN)
            self.assertTrue(process.stdout.closed)

    def test_mac_timeout_kills_only_owned_child_and_fails_without_unlocking_or_retry(self):
        process, timer = self.fake_mac(SECRET.encode())
        def start(): timer.callback()
        def make_timer(seconds, callback): timer.callback = callback; timer.start.side_effect = start; return timer
        with patch.object(vault.sys, 'platform', 'darwin'), patch.object(vault.subprocess, 'Popen', return_value=process), \
                patch.object(vault.threading, 'Timer', side_effect=make_timer):
            with self.assertRaises(vault.OwnerCredentialError): vault.read_owner_search_secret(ORIGIN)
        process.kill.assert_called_once(); self.assertTrue(process.stdout.closed)

    def test_explicit_coordinator_factory_reads_scoped_secret_without_network_or_activation(self):
        with patch.object(vault, 'read_owner_search_secret', return_value=SECRET) as read, \
                patch('community.owner_search_agent.http.client.HTTPSConnection') as connection:
            coordinator = HTTPSCoordinator.from_os_credentials('https://COORDINATOR.example:443/')
            self.assertEqual(coordinator.host, 'coordinator.example'); self.assertEqual(coordinator.secret, SECRET)
            read.assert_called_once_with(ORIGIN); connection.assert_not_called()
        with patch.object(vault, 'read_owner_search_secret', side_effect=OSError('PRIVATE detail')):
            with self.assertRaisesRegex(OwnerSearchError, '^owner_credentials_unavailable$'):
                HTTPSCoordinator.from_os_credentials(ORIGIN)
        with patch.object(vault, 'read_owner_search_secret') as read:
            with self.assertRaises(OwnerSearchError): HTTPSCoordinator.from_os_credentials('https://secret:PRIVATE@coordinator.example')
            read.assert_not_called()
