"""Read only the separately named Object audit key, never the search credential."""
import hashlib

from . import owner_search_credentials as vault

ACCOUNT='owner-object-audit-agent'
PREFIX='VISIONCommunity.OwnerObjectAudit.'


def credential_target(origin):
    return PREFIX+hashlib.sha256(vault.canonical_origin(origin).encode('ascii')).hexdigest()


def read_owner_object_secret(origin):
    target=credential_target(origin)
    try:
        if vault.sys.platform=='win32':value=vault._windows_read(target,account=ACCOUNT)
        elif vault.sys.platform=='darwin':value=vault._mac_read(target,account=ACCOUNT)
        else:raise ValueError
        if not isinstance(value,str) or not vault.HEX.fullmatch(value):raise ValueError
        return value
    except Exception:
        raise vault.OwnerCredentialError('owner_credentials_unavailable') from None
