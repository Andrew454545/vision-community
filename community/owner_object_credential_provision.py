"""Explicit future Object key setup; no activation and no search-key access."""
import getpass
import hmac
import json
import sys
import warnings

from . import owner_credential_provision as shared
from . import owner_object_credentials as vault
from .owner_object_service import load_configuration


def _backend(target):
    if sys.platform=='win32':return shared.WindowsVault(target,account=vault.ACCOUNT)
    if sys.platform=='darwin':return shared.MacVault(target,account=vault.ACCOUNT)
    raise shared.CredentialProvisionError('owner_platform_unsupported')


def provision_credential(path,checksum,secret,*,replace_sha256=None):
    return shared._provision_credential(path,checksum,secret,replace_sha256=replace_sha256,
        loader=load_configuration,target_for=vault.credential_target,backend=_backend)


def main(argv=None):
    parser=shared._Parser(description='Future private Object audit key setup; never activates processing.')
    parser.add_argument('--config',required=True);parser.add_argument('--config-sha256',required=True)
    parser.add_argument('--replace-sha256')
    try:
        args=parser.parse_args(argv);config=load_configuration(args.config,args.config_sha256)
        if not (sys.stdin is not None and sys.stderr is not None and sys.stdin.isatty() and sys.stderr.isatty()):
            raise shared.CredentialProvisionError('owner_interactive_terminal_required')
        sys.stderr.write('Object audit credential for '+config['origin']+' ('+config['environment']+'). Processing stays paused.\n')
        with warnings.catch_warnings():
            warnings.simplefilter('error',getpass.GetPassWarning)
            secret=getpass.getpass('Owner Object audit key (hidden): ');shared._secret(secret)
            if not hmac.compare_digest(secret,getpass.getpass('Repeat key (hidden): ')):
                raise shared.CredentialProvisionError('owner_secret_confirmation_required')
        result=provision_credential(args.config,args.config_sha256,secret,replace_sha256=args.replace_sha256);status=0
    except (KeyboardInterrupt,EOFError):result,status={'status':'cancelled','activation':'unchanged'},1
    except Exception as error:
        code=str(error) if isinstance(error,shared.CredentialProvisionError) else 'owner_provision_unavailable'
        result,status={'status':'operator_required','error':code,'activation':'unchanged'},1
    if sys.stdout is not None:sys.stdout.write(json.dumps(result)+'\n')
    return status


if __name__=='__main__':raise SystemExit(main())
