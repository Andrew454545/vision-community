"""Read one explicitly selected owner-search credential from the user's OS vault.

No enumeration, provisioning, command-line secret, plaintext fallback or import
side effect. Native calls are made only when an approved operator invokes read.
"""
from __future__ import annotations

import ctypes
import hashlib
from pathlib import Path
import re
import subprocess
import sys
import threading
from urllib.parse import urlsplit

ACCOUNT = "owner-search-agent"
PREFIX = "VISIONCommunity.OwnerSearch."
HEX = re.compile(r"[0-9a-f]{64}\Z")


class OwnerCredentialError(ValueError):
    pass


def canonical_origin(origin):
    try:
        if (not isinstance(origin, str) or len(origin) > 300 or not origin.isascii()
                or any(ord(character) <= 32 or ord(character) == 127 for character in origin)):
            raise ValueError
        parts = urlsplit(origin)
        host = parts.hostname
        if (parts.scheme != 'https' or not host or parts.username is not None or parts.password is not None
                or parts.port not in (None, 443) or parts.path not in ('', '/') or parts.query or parts.fragment
                or not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?', host)
                or any(not label or len(label) > 63 or label.startswith('-') or label.endswith('-') for label in host.split('.'))):
            raise ValueError
        return 'https://' + host
    except (ValueError, TypeError):
        raise OwnerCredentialError('invalid_owner_origin') from None


def credential_target(origin):
    return PREFIX + hashlib.sha256(canonical_origin(origin).encode('ascii')).hexdigest()


class _FileTime(ctypes.Structure):
    _fields_ = [('low', ctypes.c_uint32), ('high', ctypes.c_uint32)]


class _Credential(ctypes.Structure):
    _fields_ = [('Flags', ctypes.c_uint32), ('Type', ctypes.c_uint32),
                ('TargetName', ctypes.c_wchar_p), ('Comment', ctypes.c_wchar_p),
                ('LastWritten', _FileTime), ('CredentialBlobSize', ctypes.c_uint32),
                ('CredentialBlob', ctypes.POINTER(ctypes.c_ubyte)), ('Persist', ctypes.c_uint32),
                ('AttributeCount', ctypes.c_uint32), ('Attributes', ctypes.c_void_p),
                ('TargetAlias', ctypes.c_wchar_p), ('UserName', ctypes.c_wchar_p)]


def _windows_value(item, target):
    # Shared by the read-only runner and the explicitly invoked provisioner.
    # Never interpret a denied, unrelated or oversized credential as missing.
    if (item.Type != 1 or item.TargetName != target or item.UserName != ACCOUNT
            or item.CredentialBlobSize not in (64, 128) or not item.CredentialBlob):
        raise OwnerCredentialError('owner_credentials_unavailable')
    raw = ctypes.string_at(item.CredentialBlob, item.CredentialBlobSize)
    value = raw.decode('ascii' if len(raw) == 64 else 'utf-16-le')
    if not HEX.fullmatch(value):
        raise OwnerCredentialError('owner_credentials_unavailable')
    return value


def _windows_read(target):
    api = ctypes.WinDLL('Advapi32.dll', use_last_error=True)
    pointer = ctypes.POINTER(_Credential)()
    api.CredReadW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
                              ctypes.POINTER(ctypes.POINTER(_Credential))]
    api.CredReadW.restype = ctypes.c_int
    api.CredFree.argtypes, api.CredFree.restype = [ctypes.c_void_p], None
    if not api.CredReadW(target, 1, 0, ctypes.byref(pointer)):
        raise OwnerCredentialError('owner_credentials_unavailable')
    try:
        if not pointer:
            raise OwnerCredentialError('owner_credentials_unavailable')
        # Windows' generic-credential UI stores a Unicode password. Accept that
        # exact representation or the explicit 64-byte ASCII application blob.
        return _windows_value(pointer.contents, target)
    finally:
        api.CredFree(pointer)


def _mac_read(target):
    # Fixed Apple binary, one service/account and the current user's login
    # keychain only. Never add/unlock/enumerate/change keychain ACLs or pass a
    # password in arguments/environment. stdout is bounded private memory.
    keychain = Path.home() / 'Library/Keychains/login.keychain-db'
    process = subprocess.Popen(['/usr/bin/security', 'find-generic-password', '-s', target,
                                '-a', ACCOUNT, '-w', str(keychain)],
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               env={'PATH': '/usr/bin:/bin', 'LANG': 'C'}, shell=False)
    timed_out = threading.Event()

    def expire():
        timed_out.set()
        try: process.kill()
        except OSError: pass

    timer = threading.Timer(10, expire)
    timer.daemon = True
    try:
        timer.start()
        raw = process.stdout.read(67)  # 64 hex chars plus LF/CRLF; reject excess.
        if len(raw) > 66:
            raise OwnerCredentialError('owner_credentials_unavailable')
        status = process.wait(timeout=1)
        if timed_out.is_set() or status != 0:
            raise OwnerCredentialError('owner_credentials_unavailable')
        if raw.endswith(b'\r\n'): raw = raw[:-2]
        elif raw.endswith(b'\n'): raw = raw[:-1]
        return raw.decode('ascii')
    finally:
        timer.cancel()
        if process.poll() is None:
            try: process.kill()
            except OSError: pass
        try: process.wait(timeout=1)
        except (OSError, subprocess.TimeoutExpired): pass
        process.stdout.close()


def read_owner_search_secret(origin):
    target = credential_target(origin)  # Validate destination before OS access.
    try:
        if sys.platform == 'win32': secret = _windows_read(target)
        elif sys.platform == 'darwin': secret = _mac_read(target)
        else: raise OwnerCredentialError('owner_credentials_unavailable')
        if not isinstance(secret, str) or not HEX.fullmatch(secret):
            raise OwnerCredentialError('owner_credentials_unavailable')
        return secret
    except Exception:
        # Includes missing/locked/denied credentials, bad native data and timeouts.
        # The caller gets neither native diagnostics nor a plaintext alternative.
        raise OwnerCredentialError('owner_credentials_unavailable') from None
