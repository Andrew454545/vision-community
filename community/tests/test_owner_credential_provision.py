"""Synthetic vault APIs only. Never reads or writes a real saved credential."""
import ctypes
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
import warnings

from community import owner_credential_provision as setup
from community import owner_search_credentials as vault
from community.owner_search_agent import _exclusive
from community.owner_search_service import SCOPE
from community.search_snapshot import digest, encoded

SECRET, OLD = 'a' * 64, 'b' * 64
ORIGIN = 'https://owner.example.test'
ROOT = Path(__file__).resolve().parents[2]


class MemoryVault:
    def __init__(self, secret=None):
        self.value, self.writes, self.reads = secret, [], 0
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def read(self):
        self.reads += 1
        return self.value
    def write(self, value, *, replace):
        self.writes.append((value, replace))
        self.value = value


class OwnerCredentialProvisionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.state = self.root / 'state'; self.state.mkdir()
        self.config = {'version': 1, 'scope': SCOPE, 'origin': ORIGIN, 'environment': 'staging',
                       'state': str(self.state), 'lanes': {'scene': {'policyId': 'fixture',
            'runtime': str(self.root / 'native/runtime.json'), 'runtimeSha256': 'c' * 64,
            'snapshot': str(self.root / 'snapshot'), 'snapshotSha256': 'd' * 64}}}
        self.path = self.root / 'owner.private.json'
        self.path.write_bytes(encoded(self.config)); self.pin = digest(self.path.read_bytes())
        self.memory = MemoryVault()
        self.backend = self.enterContext(patch.object(setup, '_backend', return_value=self.memory))

    def provision(self, value=SECRET, **kwargs):
        return setup.provision_credential(self.path, self.pin, value, **kwargs)

    def test_first_setup_exact_origin_readback_and_no_activation_or_private_file_output(self):
        for marker in ('PAUSE', 'STOP', 'outbox.json', 'supervisor.failure.json'):
            (self.state / marker).write_bytes(b'preserved fixture')
        before = {p.name: p.read_bytes() for p in self.state.iterdir()}
        self.assertEqual(self.provision(), {'status': 'stored', 'activation': 'unchanged'})
        self.backend.assert_called_once_with(vault.credential_target(ORIGIN))
        self.assertEqual(self.memory.writes, [(SECRET, False)])
        self.assertEqual(self.memory.reads, 2)
        after = {p.name: p.read_bytes() for p in self.state.iterdir()}
        self.assertEqual({k: after[k] for k in before}, before)
        self.assertEqual(set(after) - set(before), {'service.lock'})
        self.assertNotIn(SECRET.encode(), b''.join(after.values()) + self.path.read_bytes())
        self.assertFalse((self.state / 'ACTIVATE.private.json').exists())

    def test_identical_setup_is_noop_and_different_existing_secret_is_never_overwritten(self):
        self.memory.value = SECRET
        self.assertEqual(self.provision()['status'], 'unchanged')
        self.assertEqual(self.memory.writes, [])
        self.memory.value = OLD
        with self.assertRaisesRegex(setup.CredentialProvisionError, '^owner_credential_exists$'):
            self.provision()
        self.assertEqual(self.memory.value, OLD); self.assertEqual(self.memory.writes, [])

    def test_rotation_requires_exact_old_pin_and_reads_back_one_replacement(self):
        self.memory.value = OLD
        with self.assertRaisesRegex(setup.CredentialProvisionError, '^owner_credential_changed$'):
            self.provision(replace_sha256=digest(SECRET.encode()))
        self.assertEqual(self.memory.writes, [])
        self.assertEqual(self.provision(replace_sha256=digest(OLD.encode()))['status'], 'stored')
        self.assertEqual(self.memory.writes, [(SECRET, True)])

    def test_rotation_pin_cannot_authorize_missing_or_identical_but_unexpected_credential(self):
        for current in (None, SECRET):
            self.memory.value = current
            with self.assertRaisesRegex(setup.CredentialProvisionError, '^owner_credential_changed$'):
                self.provision(replace_sha256=digest(OLD.encode()))
        self.assertEqual(self.memory.writes, [])

    def test_invalid_secrets_replacement_pins_or_config_hash_never_access_vault(self):
        for secret in (None, {}, '', 'A' * 64, SECRET + '\n', 'PRIVATE'):
            with self.assertRaises(setup.CredentialProvisionError): self.provision(secret)
        for pin in (True, '', 'A' * 64, SECRET + '\n'):
            with self.assertRaises(setup.CredentialProvisionError): self.provision(replace_sha256=pin)
        with self.assertRaises(setup.CredentialProvisionError):
            setup.provision_credential(self.path, 'e' * 64, SECRET)
        self.backend.assert_not_called()

    def test_pinned_configuration_changed_during_vault_access_refuses_write(self):
        def read():
            self.path.write_bytes(self.path.read_bytes() + b' ')
            return None
        self.memory.read = read
        with self.assertRaises(setup.CredentialProvisionError): self.provision()
        self.assertEqual(self.memory.writes, [])

    def test_config_changed_after_write_preserves_written_secret_for_recovery(self):
        original = self.memory.write
        def write(value, **kwargs):
            original(value, **kwargs)
            self.path.write_bytes(self.path.read_bytes() + b' ')
        self.memory.write = write
        with self.assertRaises(setup.CredentialProvisionError): self.provision()
        self.assertEqual(self.memory.value, SECRET)
        self.assertEqual(len(self.memory.writes), 1)

    def test_failed_readback_does_not_delete_or_rollback_possibly_successful_write(self):
        values = iter([None, OLD]); self.memory.read = lambda: next(values)
        with self.assertRaisesRegex(setup.CredentialProvisionError, '^owner_credential_readback_required$'):
            self.provision()
        self.assertEqual(self.memory.value, SECRET); self.assertEqual(len(self.memory.writes), 1)

    def test_denied_or_malformed_selected_item_is_never_interpreted_as_absent(self):
        self.memory.value = 'PRIVATE malformed item'
        with self.assertRaises(setup.CredentialProvisionError): self.provision()
        self.memory.read = MagicMock(side_effect=PermissionError('PRIVATE native error and ' + SECRET))
        with self.assertRaisesRegex(setup.CredentialProvisionError, '^owner_provision_unavailable$'):
            self.provision()
        self.assertEqual(self.memory.writes, [])

    def test_application_service_lock_prevents_credential_change_under_running_owner(self):
        with _exclusive(self.state, name='service.lock'):
            with self.assertRaisesRegex(setup.CredentialProvisionError, '^owner_service_busy$'):
                self.provision()
        self.backend.assert_not_called()
        self.assertEqual(self.provision()['status'], 'stored')

    def cli(self, *, inputs=None, tty=True, arguments=None):
        out, err, stdin = io.StringIO(), io.StringIO(), io.StringIO()
        err.isatty = lambda: tty; stdin.isatty = lambda: tty
        args = arguments or ['--config', str(self.path), '--config-sha256', self.pin]
        with patch.object(setup.sys, 'stdin', stdin), patch.object(setup.sys, 'stdout', out), \
                patch.object(setup.sys, 'stderr', err), patch.object(setup.getpass, 'getpass', side_effect=inputs or [SECRET, SECRET]) as prompt:
            status = setup.main(args)
        return status, json.loads(out.getvalue()), err.getvalue(), prompt

    def test_interactive_hidden_confirmation_and_redacted_receipt(self):
        status, receipt, err, prompt = self.cli()
        self.assertEqual(status, 0); self.assertEqual(receipt['status'], 'stored')
        self.assertEqual(prompt.call_count, 2)
        self.assertIn(ORIGIN, err); self.assertIn('Processing stays paused', err)
        self.assertNotIn(SECRET, err + json.dumps(receipt))

    def test_redirected_input_mismatch_cancel_and_echo_warning_never_write(self):
        status, receipt, _, prompt = self.cli(tty=False)
        self.assertEqual(receipt['error'], 'owner_interactive_terminal_required'); prompt.assert_not_called()
        status, receipt, _, _ = self.cli(inputs=[SECRET, OLD])
        self.assertEqual(receipt['error'], 'owner_secret_confirmation_required')
        status, receipt, _, _ = self.cli(inputs=KeyboardInterrupt())
        self.assertEqual(receipt['status'], 'cancelled')
        def warning(*_): warnings.warn('PRIVATE fallback ' + SECRET, setup.getpass.GetPassWarning)
        status, receipt, err, _ = self.cli(inputs=warning)
        self.assertEqual(receipt['error'], 'owner_provision_unavailable')
        self.assertNotIn(SECRET, err + json.dumps(receipt)); self.backend.assert_not_called()

    def test_accidentally_pasted_cli_secret_and_bad_config_never_echo_or_prompt(self):
        status, receipt, err, prompt = self.cli(arguments=['--secret', SECRET])
        self.assertEqual(status, 1); self.assertEqual(receipt['error'], 'invalid_owner_provision_arguments')
        self.assertNotIn(SECRET, err + json.dumps(receipt)); prompt.assert_not_called()
        self.path.write_bytes(b'PRIVATE ' + SECRET.encode())
        status, _, _, prompt = self.cli(); self.assertEqual(status, 1); prompt.assert_not_called()
        self.backend.assert_not_called()

    def test_isolated_cli_rejects_redirected_input_without_vault_or_native_assets(self):
        env = dict(os.environ, PYTHONPATH='PRIVATE-untrusted-path', VISION_OWNER_SEARCH_SECRET=SECRET)
        result = subprocess.run([sys.executable, '-I', '-B', str(ROOT/'owner-credential.py'),
            '--config', str(self.path), '--config-sha256', self.pin], input=SECRET.encode(),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, env=env,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)['error'], 'owner_interactive_terminal_required')
        self.assertNotIn(SECRET.encode(), result.stdout + result.stderr)
        self.assertEqual(list(self.state.iterdir()), [])


class WindowsProvisionAPITests(unittest.TestCase):
    def setUp(self):
        self.target = vault.credential_target(ORIGIN)
        self.api = SimpleNamespace(CredReadW=MagicMock(return_value=0), CredWriteW=MagicMock(return_value=1), CredFree=MagicMock())
        self.enterContext(patch.object(setup.ctypes, 'WinDLL', return_value=self.api, create=True))

    def test_missing_item_is_distinguished_from_denied_without_any_overwrite(self):
        with setup.WindowsVault(self.target) as selected:
            for code in (5, 1312, 0):
                with patch.object(setup.ctypes, 'get_last_error', return_value=code, create=True):
                    with self.assertRaises(setup.CredentialProvisionError): selected.read()
            with patch.object(setup.ctypes, 'get_last_error', return_value=1168, create=True):
                self.assertIsNone(selected.read())
        self.api.CredFree.assert_not_called(); self.api.CredWriteW.assert_not_called()

    def test_write_is_exact_local_generic_item_then_private_mutable_blob_is_zeroed(self):
        observed = {}
        def write(pointer, flags):
            item = ctypes.cast(pointer, ctypes.POINTER(vault._Credential)).contents
            observed.update(kind=item.Type, target=item.TargetName, user=item.UserName, persist=item.Persist,
                attributes=item.AttributeCount, flags=flags, size=item.CredentialBlobSize,
                raw=ctypes.string_at(item.CredentialBlob, item.CredentialBlobSize), pointer=item.CredentialBlob)
            # Hold the pointer's underlying buffer through the mock call record.
            observed['item'] = pointer._obj
            return 1
        self.api.CredWriteW.side_effect = write
        with setup.WindowsVault(self.target) as selected: selected.write(SECRET, replace=False)
        self.assertEqual({k: observed[k] for k in ('kind', 'target', 'user', 'persist', 'attributes', 'flags', 'size')},
            {'kind': 1, 'target': self.target, 'user': vault.ACCOUNT, 'persist': 2, 'attributes': 0, 'flags': 0, 'size': 128})
        self.assertEqual(observed['raw'], SECRET.encode('utf-16-le'))
        self.assertEqual(ctypes.string_at(observed['pointer'], 128), bytes(128))

    def test_selected_item_roundtrip_uses_same_decoder_as_running_owner(self):
        raw = SECRET.encode('utf-16-le'); blob = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
        item = vault._Credential(Type=1, TargetName=self.target, UserName=vault.ACCOUNT,
                                CredentialBlobSize=len(raw), CredentialBlob=blob)
        def read(target, kind, flags, pointer):
            ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(vault._Credential)))[0] = ctypes.pointer(item)
            return 1
        self.api.CredReadW.side_effect = read
        with setup.WindowsVault(self.target) as selected:
            self.assertEqual(selected.read(), SECRET)
            item.UserName = 'unrelated'
            with self.assertRaises(vault.OwnerCredentialError): selected.read()
        self.assertEqual(self.api.CredFree.call_count, 2)

    def test_failed_write_still_zeroes_blob_and_never_deletes_an_item(self):
        captured = {}
        def fail(pointer, flags): captured['item'] = pointer._obj; return 0
        self.api.CredWriteW.side_effect = fail
        with setup.WindowsVault(self.target) as selected:
            with self.assertRaises(setup.CredentialProvisionError): selected.write(SECRET, replace=True)
        item = captured['item']; self.assertEqual(ctypes.string_at(item.CredentialBlob, 128), bytes(128))


class MacProvisionAPITests(unittest.TestCase):
    def setUp(self):
        self.target = vault.credential_target(ORIGIN)
        self.api = SimpleNamespace(**{k: MagicMock(return_value=0) for k in (
            'SecKeychainOpen', 'SecKeychainFindGenericPassword', 'SecKeychainItemFreeContent',
            'SecKeychainAddGenericPassword', 'SecKeychainItemModifyAttributesAndData')})
        self.core = SimpleNamespace(CFRelease=MagicMock())
        self.enterContext(patch.object(setup, 'plain_path', side_effect=lambda p: p))
        self.loader = self.enterContext(patch.object(setup.ctypes, 'CDLL', side_effect=[self.api, self.core]))
        self.popen = self.enterContext(patch.object(vault.subprocess, 'Popen'))
        def open_keychain(path, pointer): ctypes.cast(pointer, ctypes.POINTER(ctypes.c_void_p))[0] = 11; return 0
        self.api.SecKeychainOpen.side_effect = open_keychain
        self.value, self.buffer, self.denied = None, None, 0
        def find(keychain, service_size, service, account_size, account, length, data, item):
            self.assertEqual(keychain.value, 11)
            self.assertEqual((service_size, service, account_size, account),
                             (len(self.target), self.target.encode(), len(vault.ACCOUNT), vault.ACCOUNT.encode()))
            if self.denied: return self.denied
            if self.value is None: return -25300
            self.buffer = ctypes.create_string_buffer(self.value)
            ctypes.cast(length, ctypes.POINTER(ctypes.c_uint32))[0] = len(self.value)
            ctypes.cast(data, ctypes.POINTER(ctypes.c_void_p))[0] = ctypes.cast(self.buffer, ctypes.c_void_p)
            ctypes.cast(item, ctypes.POINTER(ctypes.c_void_p))[0] = 22
            return 0
        self.api.SecKeychainFindGenericPassword.side_effect = find

    def test_missing_login_keychain_never_creates_or_unlocks_anything(self):
        self.api.SecKeychainOpen.side_effect = None; self.api.SecKeychainOpen.return_value = -25294
        with self.assertRaises(setup.CredentialProvisionError):
            with setup.MacVault(self.target): pass
        self.api.SecKeychainFindGenericPassword.assert_not_called()
        self.api.SecKeychainAddGenericPassword.assert_not_called(); self.popen.assert_not_called()

    def test_exact_current_login_keychain_uses_framework_memory_and_no_child_arguments(self):
        captured = {}
        def add(keychain, slen, service, alen, account, size, password, item):
            self.assertEqual((slen, service, alen, account),
                             (len(self.target), self.target.encode(), len(vault.ACCOUNT), vault.ACCOUNT.encode()))
            self.value = ctypes.string_at(password, size)
            captured['blob'] = password
            ctypes.cast(item, ctypes.POINTER(ctypes.c_void_p))[0] = 22
            return 0
        self.api.SecKeychainAddGenericPassword.side_effect = add
        with setup.MacVault(self.target) as selected:
            self.assertIsNone(selected.read()); selected.write(SECRET, replace=False)
            self.assertEqual(self.value, SECRET.encode())
            self.assertEqual(bytes(captured['blob']), bytes(64))
            self.assertEqual(selected.read(), SECRET)
        self.assertTrue(self.api.SecKeychainOpen.call_args.args[0].decode().replace('\\', '/').endswith('/Library/Keychains/login.keychain-db'))
        self.assertEqual(self.loader.call_args_list[0].args, ('/System/Library/Frameworks/Security.framework/Security',))
        self.assertEqual(self.api.SecKeychainItemFreeContent.call_count, 1)
        self.assertEqual(self.core.CFRelease.call_count, 3)  # Old item, new item, Keychain.
        self.api.SecKeychainItemModifyAttributesAndData.assert_not_called(); self.popen.assert_not_called()

    def test_mac_rotation_modifies_only_password_data_preserving_service_account_and_acl(self):
        self.value = OLD.encode()
        captured = {}
        def modify(item, attributes, size, password):
            self.assertEqual(item.value, 22); self.assertIsNone(attributes)
            self.value = ctypes.string_at(password, size); captured['blob'] = password
            return 0
        self.api.SecKeychainItemModifyAttributesAndData.side_effect = modify
        with setup.MacVault(self.target) as selected:
            self.assertEqual(selected.read(), OLD); selected.write(SECRET, replace=True)
            self.assertEqual(bytes(captured['blob']), bytes(64)); self.assertEqual(selected.read(), SECRET)
        self.api.SecKeychainAddGenericPassword.assert_not_called(); self.popen.assert_not_called()

    def test_mac_denied_or_oversized_secret_is_not_missing_and_frees_native_content(self):
        with setup.MacVault(self.target) as selected:
            for status in (-25308, -25293, -128):
                self.denied = status
                with self.assertRaises(setup.CredentialProvisionError): selected.read()
            self.denied = 0; self.value = b'x' * 10000
            with self.assertRaises(setup.CredentialProvisionError): selected.read()
        self.api.SecKeychainItemFreeContent.assert_called_once()
        self.api.SecKeychainAddGenericPassword.assert_not_called()

    def test_mac_duplicate_or_denied_write_does_not_fall_back_to_delete_unlock_or_replace(self):
        self.api.SecKeychainAddGenericPassword.return_value = -25299
        with setup.MacVault(self.target) as selected:
            self.assertIsNone(selected.read())
            with self.assertRaises(setup.CredentialProvisionError): selected.write(SECRET, replace=False)
            with self.assertRaises(setup.CredentialProvisionError): selected.write(SECRET, replace=True)
        self.api.SecKeychainAddGenericPassword.assert_called_once()
        self.api.SecKeychainItemModifyAttributesAndData.assert_not_called(); self.popen.assert_not_called()


class ProvisionBackendSelectionTests(unittest.TestCase):
    def test_selection_does_not_load_os_apis_until_explicit_enter_and_refuses_other_platforms(self):
        with patch.object(setup.ctypes, 'WinDLL', create=True) as windows, patch.object(setup.ctypes, 'CDLL') as mac:
            with patch.object(setup.sys, 'platform', 'win32'):
                self.assertIsInstance(setup._backend(vault.credential_target(ORIGIN)), setup.WindowsVault)
            with patch.object(setup.sys, 'platform', 'darwin'):
                self.assertIsInstance(setup._backend(vault.credential_target(ORIGIN)), setup.MacVault)
            with patch.object(setup.sys, 'platform', 'linux'):
                with self.assertRaises(setup.CredentialProvisionError): setup._backend(vault.credential_target(ORIGIN))
            windows.assert_not_called(); mac.assert_not_called()
