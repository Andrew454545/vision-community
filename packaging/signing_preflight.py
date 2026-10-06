"""Fail closed, naming only missing signing settings, before any signing step.

Values are never printed. A complete configuration only allows a signing
attempt; the builders still require valid signatures, timestamps, the exact
publisher and (on Mac) accepted notarization before a public-ready receipt.
"""
import os
import sys

REQUIRED = {
    'mac': ('MAC_DEVELOPER_ID_P12_BASE64', 'MAC_DEVELOPER_ID_P12_PASSWORD', 'MAC_SIGNING_IDENTITY',
            'APPLE_NOTARY_KEY_P8', 'APPLE_NOTARY_KEY_ID', 'APPLE_NOTARY_ISSUER'),
    'windows': ('AZURE_CLIENT_ID', 'AZURE_TENANT_ID', 'AZURE_SUBSCRIPTION_ID', 'ARTIFACT_SIGNING_ENDPOINT',
                'ARTIFACT_SIGNING_ACCOUNT', 'ARTIFACT_SIGNING_PROFILE', 'WINDOWS_PUBLISHER_SUBJECT'),
}


def missing(platform, environment=os.environ):
    names = [name for name in REQUIRED[platform] if not environment.get(name, '').strip()]
    if platform == 'mac' and not names and not environment['MAC_SIGNING_IDENTITY'].startswith('Developer ID Application: '):
        names.append('MAC_SIGNING_IDENTITY (must be a Developer ID Application identity)')
    if platform == 'windows' and not names and not environment['ARTIFACT_SIGNING_ENDPOINT'].startswith('https://'):
        names.append('ARTIFACT_SIGNING_ENDPOINT (must be the account region https endpoint)')
    return names


def main(argv):
    if len(argv) != 2 or argv[1] not in REQUIRED:
        print('usage: signing_preflight.py mac|windows')
        return 2
    names = missing(argv[1])
    if names:
        print('Signing is not configured, so no candidate was signed. Missing: ' + ', '.join(names))
        print('See docs/SIGNING-ACCOUNT-SETUP.md. Unsigned builds stay maintainer previews.')
        return 1
    print('Signing settings are present. Signature, timestamp, publisher and notarization checks still decide.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
