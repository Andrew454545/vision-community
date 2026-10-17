"""Finite Mac CI credential-cleanup checks; only synthetic invalid key material.

One case uses a real new temporary keychain and invalid certificate import.
Later-stage cases use local command fixtures. No valid signing credentials,
notarization requests, accounts, models, imagery or publication are used.
"""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

HELPERS = Path(__file__).resolve().parent / 'macos'


def run():
    if sys.platform != 'darwin': raise RuntimeError('mac_required')
    checks = {}
    def check(name, value):
        checks[name] = bool(value)
        if not value: raise RuntimeError(name)
    help_text = subprocess.run(['xcrun', 'notarytool', 'submit', '--help'], capture_output=True, text=True, check=True).stdout
    check('notarytool_explicit_keychain_option', '--keychain' in help_text)
    before = subprocess.run(['security', 'list-keychains', '-d', 'user'], capture_output=True, check=True).stdout
    with tempfile.TemporaryDirectory(prefix='vision-signing-check-') as folder:
        root = Path(folder).resolve()
        for label, failure in [('actual-invalid-import', 'actual'), ('early-failure', 'import'), ('late-failure', 'notary'), ('success-cleanup', '')]:
            case = root / label; case.mkdir()
            exported = case / 'environment'
            environment = {**os.environ, 'RUNNER_TEMP':str(case), 'GITHUB_ENV':str(exported),
                'MAC_DEVELOPER_ID_P12_BASE64':base64.b64encode(b'SYNTHETIC INVALID CERTIFICATE').decode(),
                'MAC_DEVELOPER_ID_P12_PASSWORD':'SYNTHETIC PASSWORD', 'APPLE_NOTARY_KEY_P8':'SYNTHETIC INVALID KEY',
                'APPLE_NOTARY_KEY_ID':'SYNTHETIC', 'APPLE_NOTARY_ISSUER':'SYNTHETIC'}
            if failure != 'actual':
                commands = case / 'bin'; commands.mkdir()
                bodies = {
                    'security': '#!/bin/bash\ncase "$1" in\ncreate-keychain) touch "${@: -1}";;\ndelete-keychain) rm -f "$2";;\nimport) if [ "$CASE_FAILURE" = import ]; then exit 42; fi;;\nesac\n',
                    'xcrun': '#!/bin/bash\nif [ "$CASE_FAILURE" = notary ]; then exit 43; fi\n',
                    'uuidgen': '#!/bin/bash\necho SYNTHETIC-PASSWORD\n'}
                for name, body in bodies.items():
                    path = commands / name; path.write_text(body); path.chmod(0o700)
                environment.update(PATH=str(commands)+':'+environment['PATH'], CASE_FAILURE=failure)
            attempt = subprocess.run(['/bin/bash', str(HELPERS / 'Prepare-Signing.sh')], env=environment, capture_output=True, timeout=30)
            check(label+'_expected_preparation_result', (attempt.returncode == 0) == (failure == ''))
            keychain = Path(exported.read_text().strip().split('=', 1)[1])
            check(label+'_bounded_scope', keychain.parent.parent == case and keychain.name == 'signing.keychain-db')
            if failure:
                check(label+'_directory_removed_after_failure', not keychain.parent.exists())
            else:
                check('successful_preparation_keeps_only_owned_keychain', sorted(p.name for p in keychain.parent.iterdir()) == ['VISION-SIGNING-TEMP', 'signing.keychain-db'])
            cleanup_environment = {**environment, 'VISION_SIGNING_KEYCHAIN':str(keychain)}
            cleaned = subprocess.run(['/bin/bash', str(HELPERS / 'Clean-Signing.sh')], env=cleanup_environment, capture_output=True, timeout=30)
            check(label+'_cleanup_is_safe_to_repeat', cleaned.returncode == 0 and not keychain.parent.exists())
        unrelated = root / 'unrelated'; unrelated.mkdir()
        untouched = unrelated / 'signing.keychain-db'; untouched.write_bytes(b'RETAINED SYNTHETIC FILE')
        refused = subprocess.run(['/bin/bash', str(HELPERS / 'Clean-Signing.sh')], env={**os.environ, 'RUNNER_TEMP':str(root), 'VISION_SIGNING_KEYCHAIN':str(untouched)}, capture_output=True, timeout=10)
        check('unfamiliar_cleanup_scope_preserved', refused.returncode != 0 and untouched.read_bytes() == b'RETAINED SYNTHETIC FILE')
    after = subprocess.run(['security', 'list-keychains', '-d', 'user'], capture_output=True, check=True).stdout
    check('user_keychain_search_list_unchanged', before == after)
    return {'status':'SIGNING_CLEANUP_PASS', 'checks':checks, 'validCredentialsUsed':False,
            'signedCandidateTested':False, 'notarizationRequests':0, 'productionQualified':False}


if __name__ == '__main__':
    try:
        value = run()
    except Exception as error:
        value = {'status':'INCOMPLETE', 'reason':type(error).__name__, 'signedCandidateTested':False}
    print(json.dumps(value))
    raise SystemExit(value['status'] != 'SIGNING_CLEANUP_PASS')
