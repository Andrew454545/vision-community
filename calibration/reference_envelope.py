"""Authenticated private transport for reduced reference values on public CI.

Encryption preserves privacy; it does not authenticate authorship or approval.
Correlate the expected source revision/run with independent GitHub metadata.
The recipient private key never leaves the operator's computer.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re

from community import object_canary as check

MAXIMUM = 16 * 1024**2
ALGORITHM = 'RSA-OAEP-SHA256+A256GCM'
LABEL = b'vision-object-reference-envelope-v1'


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def pack(folder):
    folder = check.regular(folder, directory=True)
    files = {}
    size = 0
    for path in folder.iterdir():
        check.require(path.name == 'mac-object-reference.json' or re.fullmatch(
            r'(cpu|coreml-requested)-(common|hybrid-[01])-[12]\.json', path.name), 'unexpected_reference_file')
        check.regular(path)
        check.require(path.stat().st_size <= check.MAX_JSON and size + path.stat().st_size <= MAXIMUM, 'reference_file_limit')
        raw = path.read_bytes()
        check.require(len(raw) <= check.MAX_JSON, 'reference_file_limit')
        files[path.name] = base64.b64encode(raw).decode('ascii')
        size += len(files[path.name])
        check.require(size <= MAXIMUM, 'reference_packet_limit')
    check.require('mac-object-reference.json' in files, 'missing_reference_receipt')
    payload = canonical({'version': 1, 'files': files})
    check.require(len(payload) <= MAXIMUM, 'reference_packet_limit')
    return payload


def seal(payload, public_pem, *, source_revision, run_id):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    check.require(isinstance(payload, bytes) and len(payload) <= MAXIMUM, 'reference_packet_limit')
    check.require(re.fullmatch(r'[0-9a-f]{40}', source_revision or '') and type(run_id) is int and run_id > 0,
                  'invalid_reference_provenance')
    public = serialization.load_pem_public_key(public_pem)
    check.require(isinstance(public, rsa.RSAPublicKey) and 3072 <= public.key_size <= 8192, 'invalid_recipient_key')
    key, nonce = os.urandom(32), os.urandom(12)
    header = {'version': 1, 'algorithm': ALGORITHM, 'sourceRevision': source_revision, 'runId': run_id,
              'recipientSha256': hashlib.sha256(public_pem).hexdigest()}
    encrypted = AESGCM(key).encrypt(nonce, payload, canonical(header))
    wrapped = public.encrypt(key, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=LABEL))
    return {**header, 'wrappedKey': base64.b64encode(wrapped).decode('ascii'),
            'nonce': base64.b64encode(nonce).decode('ascii'), 'ciphertext': base64.b64encode(encrypted).decode('ascii')}


def open_envelope(envelope, private_pem, public_pem, *, source_revision, run_id):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    header_keys = ('version', 'algorithm', 'sourceRevision', 'runId', 'recipientSha256')
    check.require(isinstance(envelope, dict) and set(envelope) == {*header_keys, 'wrappedKey', 'nonce', 'ciphertext'}
                  and type(envelope['version']) is int and envelope['version'] == 1 and envelope['algorithm'] == ALGORITHM
                  and envelope['sourceRevision'] == source_revision and envelope['runId'] == run_id
                  and envelope['recipientSha256'] == hashlib.sha256(public_pem).hexdigest(), 'reference_envelope_mismatch')
    private = serialization.load_pem_private_key(private_pem, password=None)
    public = serialization.load_pem_public_key(public_pem)
    check.require(isinstance(private, rsa.RSAPrivateKey) and 3072 <= private.key_size <= 8192
                  and private.public_key().public_numbers() == public.public_numbers(), 'reference_recipient_mismatch')
    for name, maximum in (('wrappedKey', 4 * ((private.key_size // 8 + 2) // 3)),
                          ('nonce', 16), ('ciphertext', 4 * ((MAXIMUM + 18) // 3))):
        check.require(isinstance(envelope[name], str) and len(envelope[name]) <= maximum, 'reference_envelope_limit')
    values = [base64.b64decode(envelope[name], validate=True) for name in ('wrappedKey', 'nonce', 'ciphertext')]
    wrapped, nonce, encrypted = values
    check.require(len(wrapped) == private.key_size // 8 and len(nonce) == 12 and len(encrypted) <= MAXIMUM + 16,
                  'reference_envelope_limit')
    key = private.decrypt(wrapped, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=LABEL))
    return AESGCM(key).decrypt(nonce, encrypted, canonical({name: envelope[name] for name in header_keys}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder', type=Path, required=True)
    parser.add_argument('--public-key', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source-revision', required=True)
    parser.add_argument('--run-id', type=int, required=True)
    args = parser.parse_args()
    value = seal(pack(args.folder), check.regular(args.public_key).read_bytes(),
                 source_revision=args.source_revision, run_id=args.run_id)
    # New output only. No plaintext, private key or cryptographic key is printed.
    with args.out.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, allow_nan=False)
    print(json.dumps({'status': 'SEALED', 'bytes': args.out.stat().st_size, 'sha256': check.file_sha256(args.out)}))


if __name__ == '__main__':
    main()
