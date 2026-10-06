import base64
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from calibration import reference_envelope as transport


@unittest.skipUnless(importlib.util.find_spec('cryptography'), 'Maintainer reference transport requires cryptography')
class ReferenceEnvelopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        cls.private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption())
        cls.public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)

    def seal(self):
        return transport.seal(b'private fixture values', self.public, source_revision='a' * 40, run_id=123)

    def open(self, value, **overrides):
        return transport.open_envelope(value, self.private, self.public,
                                       **{'source_revision': 'a' * 40, 'run_id': 123, **overrides})

    def test_private_roundtrip_uses_fresh_keys_and_ciphertexts(self):
        first, second = self.seal(), self.seal()
        self.assertNotEqual(first['ciphertext'], second['ciphertext'])
        self.assertNotEqual(first['nonce'], second['nonce'])
        self.assertNotEqual(first['wrappedKey'], second['wrappedKey'])
        self.assertNotIn('private fixture values', json.dumps(first))
        self.assertEqual(self.open(first), b'private fixture values')

    def test_changed_ciphertext_nonce_or_wrapped_key_cannot_be_opened(self):
        from cryptography.exceptions import InvalidTag
        for field in ('ciphertext', 'nonce', 'wrappedKey'):
            value = self.seal()
            raw = bytearray(base64.b64decode(value[field]))
            raw[len(raw) // 2] ^= 1
            value[field] = base64.b64encode(raw).decode()
            with self.subTest(field=field), self.assertRaises((InvalidTag, ValueError)):
                self.open(value)

    def test_wrong_run_source_key_extra_fields_or_recipient_are_refused(self):
        for field in ('runId', 'sourceRevision', 'recipientSha256', 'extra'):
            value = self.seal()
            value[field] = 124 if field == 'runId' else 'b' * 64
            with self.subTest(field=field), self.assertRaises(transport.check.CheckError):
                self.open(value)

    def test_plaintext_or_envelope_over_budget_is_refused(self):
        with self.assertRaises(transport.check.CheckError):
            transport.seal(b'x' * (transport.MAXIMUM + 1), self.public, source_revision='a' * 40, run_id=123)
        value = self.seal()
        value['ciphertext'] = base64.b64encode(b'x' * (transport.MAXIMUM + 17)).decode()
        with self.assertRaises(transport.check.CheckError):
            self.open(value)


class ReferencePacketTests(unittest.TestCase):
    def test_extra_files_cannot_export_images_models_or_keys(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary).resolve()
            (folder / 'mac-object-reference.json').write_text('{"status":"INCOMPLETE"}')
            self.assertIn('mac-object-reference.json', json.loads(transport.pack(folder))['files'])
            for name in ('face.png', 'source.tsv', 'model.onnx', 'private.pem', 'cpu-common-1.json.tmp'):
                (folder / name).write_text('private')
                with self.subTest(name=name), self.assertRaisesRegex(transport.check.CheckError, 'unexpected_reference_file'):
                    transport.pack(folder)
                (folder / name).unlink()
