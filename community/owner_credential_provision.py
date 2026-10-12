"""Explicit future owner credential setup; inert and never activates processing.

The cost hold forbids invoking this against real credentials now. Offline tests
substitute both OS APIs. Secrets are entered at an interactive hidden prompt,
never accepted in arguments, environment, configuration or redirected input.
"""
from __future__ import annotations

import argparse
import ctypes
import getpass
import hashlib
import hmac
import json
from pathlib import Path
import sys
import warnings

from . import owner_search_credentials as vault
from .native_scene_search import plain_path
from .owner_search_agent import OwnerSearchError, _exclusive
from .owner_search_service import load_configuration


class CredentialProvisionError(ValueError):
    """Fixed codes only; native diagnostics and secret values stay private."""


def _secret(value):
    if not isinstance(value, str) or not vault.HEX.fullmatch(value):
        raise CredentialProvisionError('invalid_owner_secret')
    return value


class WindowsVault:
    """One local-machine generic item in the current user's credential vault."""

    def __init__(self, target):
        self.target = target

    def __enter__(self):
        self.api = ctypes.WinDLL('Advapi32.dll', use_last_error=True)
        self.api.CredReadW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
                                       ctypes.POINTER(ctypes.POINTER(vault._Credential))]
        self.api.CredReadW.restype = ctypes.c_int
        self.api.CredWriteW.argtypes = [ctypes.POINTER(vault._Credential), ctypes.c_uint32]
        self.api.CredWriteW.restype = ctypes.c_int
        self.api.CredFree.argtypes, self.api.CredFree.restype = [ctypes.c_void_p], None
        return self

    def __exit__(self, *_):
        pass

    def read(self):
        pointer = ctypes.POINTER(vault._Credential)()
        if not self.api.CredReadW(self.target, 1, 0, ctypes.byref(pointer)):
            if ctypes.get_last_error() == 1168:  # ERROR_NOT_FOUND only.
                return None
            raise CredentialProvisionError('owner_vault_unavailable')
        try:
            if not pointer:
                raise CredentialProvisionError('owner_vault_unavailable')
            return vault._windows_value(pointer.contents, self.target)
        finally:
            self.api.CredFree(pointer)

    def write(self, secret, *, replace):
        # Persist locally across login, without enterprise/roaming persistence.
        # The exact item was checked under the same application service lock.
        raw = bytearray(_secret(secret).encode('utf-16-le'))
        blob = (ctypes.c_ubyte * len(raw)).from_buffer(raw)
        item = vault._Credential(Type=1, TargetName=self.target, UserName=vault.ACCOUNT,
                                 CredentialBlobSize=len(raw), CredentialBlob=blob, Persist=2)
        try:
            if not self.api.CredWriteW(ctypes.byref(item), 0):
                raise CredentialProvisionError('owner_vault_unavailable')
        finally:
            raw[:] = b'\0' * len(raw)


class MacVault:
    """One exact service/account in the existing current-user login Keychain.

    The Security framework takes password bytes in memory. No `security -w
    SECRET` child, shell, Keychain creation/unlock, ACL edit or enumeration.
    Normal OS consent may still be required on a real Mac.
    """

    def __init__(self, target):
        self.target = target
        self.keychain, self.item = ctypes.c_void_p(), ctypes.c_void_p()

    def __enter__(self):
        # Resolve only this user's existing named Keychain. Missing/linked paths
        # cannot redirect setup to a new or unrelated credential store.
        path = plain_path(Path.home() / 'Library/Keychains/login.keychain-db')
        self.api = ctypes.CDLL('/System/Library/Frameworks/Security.framework/Security')
        self.core = ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
        self.core.CFRelease.argtypes, self.core.CFRelease.restype = [ctypes.c_void_p], None
        specs = {
            'SecKeychainOpen': [ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p)],
            'SecKeychainFindGenericPassword': [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p,
                ctypes.c_uint32, ctypes.c_char_p, ctypes.POINTER(ctypes.c_uint32),
                ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p)],
            'SecKeychainItemFreeContent': [ctypes.c_void_p, ctypes.c_void_p],
            'SecKeychainAddGenericPassword': [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p,
                ctypes.c_uint32, ctypes.c_char_p, ctypes.c_uint32, ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_void_p)],
            'SecKeychainItemModifyAttributesAndData': [ctypes.c_void_p, ctypes.c_void_p,
                                                       ctypes.c_uint32, ctypes.c_void_p],
        }
        for name, arguments in specs.items():
            method = getattr(self.api, name)
            method.argtypes, method.restype = arguments, ctypes.c_int32
        if self.api.SecKeychainOpen(str(path).encode('utf-8'), ctypes.byref(self.keychain)) != 0 or not self.keychain:
            self.close()
            raise CredentialProvisionError('owner_vault_unavailable')
        return self

    def close(self):
        for name in ('item', 'keychain'):
            value = getattr(self, name)
            if value:
                self.core.CFRelease(value)
                setattr(self, name, ctypes.c_void_p())

    def __exit__(self, *_):
        self.close()

    def read(self):
        if self.item:
            self.core.CFRelease(self.item)
            self.item = ctypes.c_void_p()
        target, account = self.target.encode('ascii'), vault.ACCOUNT.encode('ascii')
        length, data = ctypes.c_uint32(), ctypes.c_void_p()
        status = self.api.SecKeychainFindGenericPassword(self.keychain, len(target), target,
            len(account), account, ctypes.byref(length), ctypes.byref(data), ctypes.byref(self.item))
        try:
            if status == -25300:  # errSecItemNotFound only; denial is not absence.
                return None
            if status != 0 or not self.item or not data or length.value != 64:
                raise CredentialProvisionError('owner_vault_unavailable')
            return _secret(ctypes.string_at(data, 64).decode('ascii'))
        finally:
            if data:
                self.api.SecKeychainItemFreeContent(None, data)

    def write(self, secret, *, replace):
        if type(replace) is not bool or bool(self.item) != replace:
            raise CredentialProvisionError('owner_credential_changed')
        raw = bytearray(_secret(secret).encode('ascii'))
        blob = (ctypes.c_ubyte * len(raw)).from_buffer(raw)
        try:
            if replace:
                # NULL attributes preserves the item's service, account and ACL.
                status = self.api.SecKeychainItemModifyAttributesAndData(self.item, None, len(raw), blob)
            else:
                target, account = self.target.encode('ascii'), vault.ACCOUNT.encode('ascii')
                status = self.api.SecKeychainAddGenericPassword(self.keychain, len(target), target,
                    len(account), account, len(raw), blob, ctypes.byref(self.item))
            if status != 0:
                raise CredentialProvisionError('owner_vault_unavailable')
        finally:
            raw[:] = b'\0' * len(raw)


def _backend(target):
    if sys.platform == 'win32':
        return WindowsVault(target)
    if sys.platform == 'darwin':
        return MacVault(target)
    raise CredentialProvisionError('owner_platform_unsupported')


def provision_credential(path, checksum, secret, *, replace_sha256=None):
    """Explicit future invocation; writes one credential, never starts service.

    Default setup cannot replace an existing different secret. Rotation requires
    the independently supplied SHA-256 of the old secret. Every application
    provisioner/runner shares service.lock. External OS edits are outside this
    lock; OS vault APIs do not provide an atomic compare-and-swap guarantee.
    """
    _secret(secret)
    if replace_sha256 is not None and (not isinstance(replace_sha256, str) or not vault.HEX.fullmatch(replace_sha256)):
        raise CredentialProvisionError('invalid_owner_replacement_pin')
    try:
        config = load_configuration(path, checksum)
        target = vault.credential_target(config['origin'])
        state = plain_path(Path(config['state']), directory=True)
        with _exclusive(state, name='service.lock'):
            def guard():
                if load_configuration(path, checksum) != config:
                    raise CredentialProvisionError('owner_provision_configuration_required')
            guard()
            with _backend(target) as selected:
                current = selected.read()
                if current is not None:
                    _secret(current)
                if replace_sha256 is not None:
                    if current is None or not hmac.compare_digest(hashlib.sha256(current.encode('ascii')).hexdigest(), replace_sha256):
                        raise CredentialProvisionError('owner_credential_changed')
                if current is not None and hmac.compare_digest(current, secret):
                    guard()
                    return {'status': 'unchanged', 'activation': 'unchanged'}
                if current is not None and replace_sha256 is None:
                    raise CredentialProvisionError('owner_credential_exists')
                guard()
                selected.write(secret, replace=current is not None)
                # A denied/ambiguous readback does not erase or overwrite the
                # possibly successful write. Preserve it for operator recovery.
                actual = selected.read()
                if not isinstance(actual, str) or not hmac.compare_digest(actual, secret):
                    raise CredentialProvisionError('owner_credential_readback_required')
                guard()
                return {'status': 'stored', 'activation': 'unchanged'}
    except CredentialProvisionError:
        raise
    except OwnerSearchError as error:
        code = 'owner_service_busy' if error.code == 'owner_agent_busy' else 'owner_provision_unavailable'
        raise CredentialProvisionError(code) from None
    except Exception:
        raise CredentialProvisionError('owner_provision_unavailable') from None


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's normal error includes unexpected argument values, which
        # may be an accidentally pasted secret. Emit no argument diagnostics.
        raise CredentialProvisionError('invalid_owner_provision_arguments')


def main(argv=None):
    parser = _Parser(description='Future operator-only OS vault setup; never activates processing.')
    parser.add_argument('--config', required=True)
    parser.add_argument('--config-sha256', required=True)
    parser.add_argument('--replace-sha256')
    try:
        args = parser.parse_args(argv)
        config = load_configuration(args.config, args.config_sha256)
        if not (sys.stdin is not None and sys.stderr is not None and sys.stdin.isatty() and sys.stderr.isatty()):
            raise CredentialProvisionError('owner_interactive_terminal_required')
        sys.stderr.write('Owner credential for ' + config['origin'] + ' (' + config['environment'] + '). Processing stays paused.\n')
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            secret = getpass.getpass('Owner search key (hidden): ')
            _secret(secret)
            if not hmac.compare_digest(secret, getpass.getpass('Repeat key (hidden): ')):
                raise CredentialProvisionError('owner_secret_confirmation_required')
        result = provision_credential(args.config, args.config_sha256, secret, replace_sha256=args.replace_sha256)
        status = 0
    except (KeyboardInterrupt, EOFError):
        result, status = {'status': 'cancelled', 'activation': 'unchanged'}, 1
    except Exception as error:
        code = str(error) if isinstance(error, CredentialProvisionError) else 'owner_provision_unavailable'
        result, status = {'status': 'operator_required', 'error': code, 'activation': 'unchanged'}, 1
    if sys.stdout is not None:
        sys.stdout.write(json.dumps(result) + '\n')
    return status
