"""Synthetic record guards, separate from native inference/coverage approval."""
import base64
import binascii
import copy
import hashlib
import json
from pathlib import Path
import struct
import unittest
import zlib

from community.object_features import crc8, crc16, validate_feature_contents
from community.object_index import validate_object_index, VisionIndexError

FIXTURE = Path(__file__).with_name("fixtures") / "object-feature-content-v1.json"
DOCUMENT = json.loads(FIXTURE.read_text(encoding="utf-8"))


def mutate(case):
    baseline = copy.deepcopy(DOCUMENT["baseline"])
    manifest = baseline["manifest"]
    source = base64.b64decode(case.get("sourceBase64", baseline["sourceBase64"]))
    files = {name: bytearray(base64.b64decode(raw)) for name, raw in baseline["filesBase64"].items()}
    for name, raw in case.get("replacements", {}).items():
        files[name] = bytearray(base64.b64decode(raw))
    for write in case.get("writes", []):
        raw, offset = files[write["file"]], write["offset"]
        value = bytes.fromhex(write["hex"])
        raw[offset:offset + len(value)] = value
        checksum = write.get("checksum")
        size = {"crc8": 32, "crc16": 144, "crc32": 8}.get(checksum)
        if size:
            start = (offset // size) * size
            if checksum == "crc8":
                raw[start + 31] = crc8(raw[start:start + 31])
            elif checksum == "crc16":
                struct.pack_into("<H", raw, start + 142, binascii.crc_hqx(raw[start:start + 142], 0xffff))
            else:
                struct.pack_into("<I", raw, start + 4, zlib.crc32(raw[start:start + 4]))
    files = {name: bytes(raw) for name, raw in files.items()}
    entries = [manifest[key] for key in ("offsets", "metadata", "globalIds", "semantic", "viewQuality")]
    entries += manifest["classes"] + manifest["hotConcepts"]
    for entry in entries:
        raw = files[entry["file"]]
        entry.update(bytes=len(raw), records=len(raw) // entry.get("recordBytes", 32),
                     sha256=hashlib.sha256(raw).hexdigest())
    manifest.update(sourceBytes=len(source), sourceSha256=hashlib.sha256(source).hexdigest())
    for change in case.get("changes", []):
        target = manifest
        for key in change["path"][:-1]:
            target = target[key]
        target[change["path"][-1]] = change["value"]
    return manifest, files, source


class ObjectFeatureTests(unittest.TestCase):
    def test_frozen_replay_is_not_a_contribution(self):
        for value in (None, "a" * 64, ""):
            manifest, files, source = mutate({})
            manifest["frozenViewsManifestSha256"] = value
            with self.assertRaisesRegex(VisionIndexError, "verification_failed"):
                validate_object_index(manifest, files, source, DOCUMENT["items"], lease_id=DOCUMENT["leaseId"])

    def test_known_native_checksum_vectors(self):
        self.assertEqual(crc8(b"123456789"), 0xf4)
        self.assertEqual(crc16(b"123456789"), 0x29b1)
        self.assertEqual(zlib.crc32(b"123456789"), 0xcbf43926)

    def test_all_lanes_and_utf8_pointer_baseline(self):
        manifest, files, source = mutate({})
        self.assertEqual(validate_feature_contents(manifest, files, source),
                         {"locations": 2, "commonAndHotRecords": 3, "semanticRecords": 32, "qualityRecords": 2})
        result = validate_object_index(manifest, files, source, DOCUMENT["items"], lease_id=DOCUMENT["leaseId"])
        self.assertEqual(len(result), 2)
        self.assertNotIn("approved", result[0])

    def test_transport_budget_precedes_record_processing(self):
        manifest, files, source = mutate({})
        files["too-large.bin"] = bytes(32_000_001)
        with self.assertRaises(ValueError):
            validate_feature_contents(manifest, files, source)
        with self.assertRaises(ValueError):
            validate_feature_contents(manifest, {}, b"x" * (1024 * 1024 + 1))


def install_case(case):
    def test(self):
        manifest, files, source = mutate(case)
        if case["valid"]:
            self.assertEqual(len(validate_object_index(manifest, files, source, DOCUMENT["items"],
                               lease_id=DOCUMENT["leaseId"])), 2)
        else:
            with self.assertRaisesRegex(VisionIndexError, "^verification_failed$"):
                validate_object_index(manifest, files, source, DOCUMENT["items"], lease_id=DOCUMENT["leaseId"])
    test.__doc__ = case["name"]
    setattr(ObjectFeatureTests, "test_shared_" + case["name"], test)


for _case in DOCUMENT["cases"]:
    install_case(_case)

if __name__ == "__main__":
    unittest.main()
