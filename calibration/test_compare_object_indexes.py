import copy
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zlib
from unittest.mock import patch

from calibration import compare_object_indexes as comparison
from community.object_features import crc8, crc16
from community.tests.test_object_features import mutate


class ObjectIndexComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.gold, self.files, self.source = mutate({})
        self.gold["viewQuality"].update(policy="vision-per-view-quality-v1", viewCount=6,
            implementationIdentity="a" * 64, protectedAuthorityManifestSha256="b" * 64,
            blurAreaFractionExclusive=0.5, tileGrid=8, tunnelVisionProbabilityInclusive=0.85,
            tunnelEvidencePolicy="none-darkness-never-rejects-v1")
        self.actual, self.candidate_files = copy.deepcopy(self.gold), dict(self.files)
        self.source_path = self.root / "locations.tsv"
        self.source_path.write_bytes(self.source)

    def write(self, name, manifest, files):
        folder = self.root / name
        folder.mkdir(exist_ok=True)
        manifest = copy.deepcopy(manifest)
        entries = [manifest[key] for key in ("offsets", "metadata", "globalIds", "semantic", "viewQuality")]
        entries += manifest["classes"] + manifest["hotConcepts"]
        for entry in entries:
            raw = files[entry["file"]]
            entry.update(bytes=len(raw), records=len(raw) // entry.get("recordBytes", 32),
                         sha256=comparison.digest(raw))
        for filename, raw in files.items():
            (folder / filename).write_bytes(raw)
        raw = json.dumps(manifest, ensure_ascii=False).encode("utf-8")
        path = folder / "manifest.json"
        path.write_bytes(raw)
        return path, comparison.digest(raw)

    def pair(self):
        return (*self.write("gold", self.gold, self.files),
                *self.write("candidate", self.actual, self.candidate_files))

    def result(self):
        return comparison.compare(*self.pair(), self.source_path)

    def change_common(self, field, value):
        name = next(entry["file"] for entry in self.actual["classes"] if entry["records"])
        raw = bytearray(self.candidate_files[name])
        values = list(struct.unpack("<I5fH3BH", raw[:31]))
        values[field] = value
        raw[:31] = struct.pack("<I5fH3BH", *values)
        raw[31] = crc8(raw[:31])
        self.candidate_files[name] = bytes(raw)
        return next(i for i, e in enumerate(self.actual["classes"]) if e["file"] == name)

    def change_semantic(self, offset, value):
        raw = bytearray(self.candidate_files["semantic-pq128.bin"])
        raw[offset:offset + len(value)] = value
        raw[142:144] = struct.pack("<H", crc16(raw[:142]))
        self.candidate_files["semantic-pq128.bin"] = bytes(raw)

    def test_complete_identity_is_diagnostic_only(self):
        report = self.result()
        self.assertEqual(report["status"], "COMPLETE")
        self.assertTrue(report["exactFeatureMatch"])
        self.assertEqual(report["semantic"]["recordsCompared"], 32)
        for flag in ("qualified", "referenceProvenanceVerified", "identicalPixelsVerified",
                     "nativeSearchParityVerified", "serverAuthorization"):
            self.assertFalse(report[flag])
        self.assertNotIn("pano", json.dumps(report).lower())
        self.assertNotIn(str(self.root), json.dumps(report))

    def test_paths_and_allocation_labels_do_not_change_feature_comparison(self):
        self.actual["sourceId"] = "different-native-allocation"
        self.actual["sourceTsv"] = "/private/other-machine.tsv"
        self.actual["untrustedExtra"] = {"private": "do not copy"}
        self.assertTrue(self.result()["exactFeatureMatch"])

    def test_support_change_is_discrete(self):
        i = self.change_common(8, 22)
        report = self.result()
        self.assertFalse(report["exactFeatureMatch"])
        self.assertEqual(report["lanes"]["classes"][i]["discreteDifferences"], 1)

    def test_score_and_packed_confidence_changes_are_measured(self):
        i = self.change_common(1, 0.75)
        self.change_common(10, round(0.75 * 65535))
        lane = self.result()["lanes"]["classes"][i]
        self.assertGreater(lane["maximumScoreDifference"], 0)
        self.assertGreater(lane["maximumConfidenceDifference"], 0)

    def test_heading_wrap_is_circular(self):
        gold = struct.pack("<I5fH3BH", 0, .5, 359.9, 0, 1, .1, 0, 5, 1, 0, 32768)
        actual = struct.pack("<I5fH3BH", 0, .5, .1, 0, 1, .1, 0, 5, 1, 0, 32768)
        lane = comparison.compare_lane(gold + bytes(1), actual + bytes(1))
        self.assertAlmostEqual(lane["maximumHeadingDegrees"], .2, places=4)

    def test_missing_detection_is_not_hidden_by_shared_score_metrics(self):
        name = next(entry["file"] for entry in self.actual["hotConcepts"] if entry["records"])
        i = next(i for i, entry in enumerate(self.actual["hotConcepts"]) if entry["file"] == name)
        self.candidate_files[name] = b""
        lane = self.result()["lanes"]["hotConcepts"][i]
        self.assertEqual(lane["missingRecords"], 1)
        self.assertEqual(lane["sharedRecords"], 0)

    def test_added_detection_is_visible(self):
        name = next(entry["file"] for entry in self.actual["hotConcepts"] if entry["records"])
        self.files[name], self.candidate_files[name] = b"", self.files[name]
        lanes = self.result()["lanes"]["hotConcepts"]
        self.assertEqual(sum(lane["extraRecords"] for lane in lanes), 1)

    def test_semantic_code_changes_do_not_claim_embedding_accuracy(self):
        self.change_semantic(0, bytes([self.candidate_files["semantic-pq128.bin"][0] ^ 1]))
        semantic = self.result()["semantic"]
        self.assertEqual(semantic["differentCodeBytes"], 1)
        self.assertEqual(semantic["differentRecords"], 1)
        self.assertFalse(semantic["decodedEmbeddingDistanceMeasured"])

    def test_semantic_face_change_is_kept_visible(self):
        current = self.files["semantic-pq128.bin"][140]
        self.change_semantic(140, bytes([(current + 1) % 6]))
        self.assertEqual(self.result()["semantic"]["differentFaces"], 1)

    def test_view_quality_mask_change_is_measured(self):
        unused = 5
        semantic = bytearray(self.candidate_files["semantic-pq128.bin"])
        for offset in range(0, 16 * 144, 144):
            if semantic[offset + 140] == unused:
                semantic[offset + 140] = 0
                semantic[offset + 142:offset + 144] = struct.pack("<H", crc16(semantic[offset:offset + 142]))
        self.candidate_files["semantic-pq128.bin"] = bytes(semantic)
        raw = bytearray(self.candidate_files["view-quality.bin"])
        raw[1], raw[2] = 63 ^ (1 << unused), 1 << unused
        raw[4:8] = struct.pack("<I", zlib.crc32(raw[:4]))
        self.candidate_files["view-quality.bin"] = bytes(raw)
        self.actual["viewQuality"].update(keptViews=11, blurRejectedViews=1)
        report = self.result()
        self.assertEqual(report["viewQualityDifferences"], 1)
        self.assertFalse(report["exactFeatureMatch"])

    def test_different_quality_authority_cannot_be_called_execution_drift(self):
        self.actual["viewQuality"]["protectedAuthorityManifestSha256"] = "c" * 64
        with self.assertRaisesRegex(ValueError, "comparison_quality_policy_mismatch"):
            self.result()

    def test_nonfinite_manifest_json_is_refused(self):
        with self.assertRaisesRegex(ValueError, "nonfinite_manifest_value"):
            comparison.strict_json(b'{"value":NaN}')

    def test_semantic_boxes_and_logit_calibration_are_measured(self):
        original_x1 = struct.unpack_from("<H", self.files["semantic-pq128.bin"], 128)[0]
        self.change_semantic(128, struct.pack("<H", original_x1 + 1))
        self.change_semantic(136, struct.pack("<2e", .25, 2))
        semantic = self.result()["semantic"]
        self.assertAlmostEqual(semantic["maximumBoxDifference"], 1 / 65535)
        self.assertGreater(semantic["maximumLogitShiftDifference"], 0)
        self.assertGreater(semantic["maximumLogitScaleDifference"], 0)

    def test_changed_manifest_pin_is_refused(self):
        gold, checksum, actual, actual_checksum = self.pair()
        with self.assertRaisesRegex(ValueError, "manifest_pin_mismatch"):
            comparison.compare(gold, "0" * 64, actual, actual_checksum, self.source_path)

    def test_changed_feature_is_refused_even_with_a_valid_record_crc(self):
        gold, checksum, actual, actual_checksum = self.pair()
        self.change_semantic(0, b"\x7f")
        (actual.parent / "semantic-pq128.bin").write_bytes(self.candidate_files["semantic-pq128.bin"])
        with self.assertRaisesRegex(ValueError, "invalid_comparison_index"):
            comparison.compare(gold, checksum, actual, actual_checksum, self.source_path)

    def test_different_source_bytes_are_refused(self):
        self.source_path.write_bytes(self.source.replace(b"\t", b" \t", 1))
        with self.assertRaises(ValueError):
            self.result()

    def test_source_change_during_comparison_is_refused(self):
        arguments = self.pair()
        original = comparison.compare_semantic
        def changed(*args):
            self.source_path.write_bytes(b"changed")
            return original(*args)
        with patch.object(comparison, "compare_semantic", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "comparison_inputs_changed"):
                comparison.compare(*arguments, self.source_path)

    def test_duplicate_manifest_keys_and_traversal_are_refused(self):
        with self.assertRaisesRegex(ValueError, "duplicate_manifest_key"):
            comparison.strict_json(b'{"version":4,"version":4}')
        self.actual["classes"][0]["file"] = "../outside.bin"
        # A malformed envelope must be rejected before a file outside its root is read.
        path = self.root / "bad"; path.mkdir()
        raw = json.dumps(self.actual).encode()
        (path / "manifest.json").write_bytes(raw)
        with self.assertRaisesRegex(ValueError, "invalid_comparison_file"):
            comparison.load_index(path / "manifest.json", comparison.digest(raw), self.source)

    def test_incomplete_native_index_is_refused(self):
        self.actual["completed"] = False
        with self.assertRaisesRegex(ValueError, "invalid_comparison_index"):
            self.result()

    def test_failed_cli_preserves_report_without_private_paths_or_overwrite(self):
        gold, checksum, actual, actual_checksum = self.pair()
        out = self.root / "report"
        args = ["--reference-manifest", str(gold), "--reference-sha256", "0" * 64,
                "--candidate-manifest", str(actual), "--candidate-sha256", actual_checksum,
                "--source", str(self.source_path), "--out", str(out)]
        with patch("sys.stdout", new=io.StringIO()):
            self.assertEqual(comparison.main(args), 1)
        report = (out / "object-index-comparison.json").read_bytes()
        self.assertEqual(json.loads(report)["status"], "FAILED")
        self.assertNotIn(str(self.root).encode(), report)
        with self.assertRaises(FileExistsError):
            comparison.main(args)
        self.assertEqual((out / "object-index-comparison.json").read_bytes(), report)

    def test_invalid_native_contents_leave_a_failed_cli_report(self):
        gold, checksum, actual, actual_checksum = self.pair()
        (actual.parent / "semantic-pq128.bin").write_bytes(b"bad")
        out = self.root / "invalid-native-report"
        with patch("sys.stdout", new=io.StringIO()):
            code = comparison.main(["--reference-manifest", str(gold), "--reference-sha256", checksum,
                "--candidate-manifest", str(actual), "--candidate-sha256", actual_checksum,
                "--source", str(self.source_path), "--out", str(out)])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads((out / "object-index-comparison.json").read_bytes())["status"], "FAILED")

    def test_outputs_inside_input_folder_are_refused(self):
        gold, checksum, actual, actual_checksum = self.pair()
        args = ["--reference-manifest", str(gold), "--reference-sha256", checksum,
                "--candidate-manifest", str(actual), "--candidate-sha256", actual_checksum,
                "--source", str(self.source_path), "--out", str(gold.parent / "report")]
        with self.assertRaisesRegex(ValueError, "comparison_output_overlaps_input"):
            comparison.main(args)


if __name__ == "__main__":
    unittest.main()
