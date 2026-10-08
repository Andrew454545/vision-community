"""Analytical fixtures for PQ layout and decoded-vector measurements.

No model/runtime/downloads. Synthetic centroids are never production assets.
"""
import io
import json
import math
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from calibration import compare_object_indexes as comparison


def synthetic_book():
    raw = bytearray(comparison.CODEBOOK_BYTES)
    for subquantizer in range(128):
        for code, values in ((0, (1, 0, 0, 0)), (1, (0, 1, 0, 0)), (2, (-1, 0, 0, 0)),
                             (3, (1, 0, 0, 0)), (4, (2, 0, 0, 0))):
            struct.pack_into("<4f", raw, (subquantizer * 256 + code) * 16, *values)
    raw = bytes(raw)
    return comparison.PQ128Codebook(raw, comparison.digest(raw))


class ObjectEmbeddingComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = synthetic_book()

    def measure(self, left, right):
        result = comparison.embedding_metrics()
        comparison.measure_embeddings(result, self.book.decode(left), self.book.decode(right))
        return result

    def test_centroid_layout_preserves_subquantizer_and_component_order(self):
        codes = bytes([0, 1, 2] + [255] * 125)
        decoded = self.book.decode(codes)
        self.assertEqual(len(decoded), 512)
        self.assertEqual(decoded[:12], (1, 0, 0, 0, 0, 1, 0, 0, -1, 0, 0, 0))
        self.assertEqual(decoded[12:], (0,) * 500)

    def test_final_subquantizer_and_centroid_are_addressed_exactly(self):
        raw = bytearray(comparison.CODEBOOK_BYTES)
        struct.pack_into("<4f", raw, (127 * 256 + 255) * 16, 11, 12, 13, 14)
        raw = bytes(raw)
        book = comparison.PQ128Codebook(raw, comparison.digest(raw))
        self.assertEqual(book.decode(bytes([255] * 128))[-4:], (11, 12, 13, 14))
        self.assertEqual(book.decode(bytes([255] * 128))[:-4], (0,) * 508)

    def test_one_code_change_has_known_l2_relative_l2_and_cosine(self):
        result = self.measure(bytes(128), bytes([1]) + bytes(127))
        self.assertAlmostEqual(result["maximumAbsoluteL2"], math.sqrt(2))
        self.assertAlmostEqual(result["maximumRelativeL2"], math.sqrt(2 / 128))
        self.assertAlmostEqual(result["minimumCosineSimilarity"], 127 / 128)
        self.assertEqual(result["undefinedCosinePairs"], 0)

    def test_orthogonal_and_opposite_decoded_vectors(self):
        orthogonal = self.measure(bytes(128), bytes([1] * 128))
        opposite = self.measure(bytes(128), bytes([2] * 128))
        self.assertAlmostEqual(orthogonal["minimumCosineSimilarity"], 0)
        self.assertAlmostEqual(opposite["minimumCosineSimilarity"], -1)
        self.assertAlmostEqual(opposite["maximumRelativeL2"], 2)

    def test_identical_features_have_zero_distance(self):
        result = self.measure(bytes(128), bytes(128))
        self.assertAlmostEqual(result["minimumCosineSimilarity"], 1)
        self.assertEqual(result["maximumAbsoluteL2"], 0)
        self.assertEqual(result["maximumRelativeL2"], 0)

    def test_distinct_codes_can_decode_to_identical_vectors(self):
        result = self.measure(bytes(128), bytes([3] * 128))
        self.assertEqual(result["maximumAbsoluteL2"], 0)
        self.assertAlmostEqual(result["minimumCosineSimilarity"], 1)

    def test_relative_l2_uses_reference_norm_not_candidate_norm(self):
        forward = self.measure(bytes(128), bytes([4] * 128))
        reverse = self.measure(bytes([4] * 128), bytes(128))
        self.assertAlmostEqual(forward["maximumRelativeL2"], 1)
        self.assertAlmostEqual(reverse["maximumRelativeL2"], .5)

    def test_zero_reference_has_explicit_undefined_metrics(self):
        result = self.measure(bytes([255] * 128), bytes(128))
        self.assertEqual(result["undefinedCosinePairs"], 1)
        self.assertEqual(result["undefinedRelativeL2Pairs"], 1)
        self.assertIsNone(result["minimumCosineSimilarity"])
        self.assertIsNone(result["maximumRelativeL2"])
        self.assertAlmostEqual(result["maximumAbsoluteL2"], math.sqrt(128))
        json.dumps(result, allow_nan=False)

    def test_zero_candidate_keeps_defined_relative_error(self):
        result = self.measure(bytes(128), bytes([255] * 128))
        self.assertEqual(result["undefinedCosinePairs"], 1)
        self.assertEqual(result["undefinedRelativeL2Pairs"], 0)
        self.assertEqual(result["maximumRelativeL2"], 1)

    def test_both_zero_does_not_turn_undefined_cosine_into_success(self):
        result = self.measure(bytes([255] * 128), bytes([255] * 128))
        self.assertEqual(result["maximumAbsoluteL2"], 0)
        self.assertIsNone(result["minimumCosineSimilarity"])
        self.assertIsNone(result["maximumRelativeL2"])

    def test_aggregate_retains_worst_pair_and_undefined_counts(self):
        result = comparison.embedding_metrics()
        for right in (bytes(128), bytes([1] * 128), bytes([2] * 128), bytes([255] * 128)):
            comparison.measure_embeddings(result, self.book.decode(bytes(128)), self.book.decode(right))
        self.assertEqual(result["pairsCompared"], 4)
        self.assertAlmostEqual(result["minimumCosineSimilarity"], -1)
        self.assertEqual(result["maximumRelativeL2"], 2)
        self.assertEqual(result["undefinedCosinePairs"], 1)

    def test_nonfinite_centroid_is_refused_even_with_a_matching_pin(self):
        for value in (math.nan, math.inf, -math.inf):
            raw = bytearray(comparison.CODEBOOK_BYTES)
            struct.pack_into("<f", raw, 0, value)
            raw = bytes(raw)
            with self.assertRaisesRegex(ValueError, "nonfinite_comparison_codebook"):
                comparison.PQ128Codebook(raw, comparison.digest(raw))

    def test_wrong_size_pin_and_code_length_are_refused(self):
        with self.assertRaisesRegex(ValueError, "invalid_comparison_codebook_size"):
            comparison.PQ128Codebook(b"bad", "0" * 64)
        with self.assertRaisesRegex(ValueError, "comparison_codebook_pin_mismatch"):
            comparison.PQ128Codebook(bytes(comparison.CODEBOOK_BYTES), "0" * 64)
        with self.assertRaisesRegex(ValueError, "invalid_semantic_codes"):
            self.book.decode(bytes(127))

    def test_large_finite_centroids_keep_finite_measurements(self):
        raw = struct.pack("<f", 3e38) * 131072
        book = comparison.PQ128Codebook(raw, comparison.digest(raw))
        result = comparison.embedding_metrics()
        comparison.measure_embeddings(result, book.decode(bytes(128)), book.decode(bytes([1] * 128)))
        json.dumps(result, allow_nan=False)
        self.assertEqual(result["maximumAbsoluteL2"], 0)

    def test_rejected_locations_do_not_decode_placeholders_as_real_vectors(self):
        record = bytes(144)  # Length fixture; content is validated by the caller.
        report = comparison.compare_semantic(record * 16, record * 16, self.book, [False])
        self.assertFalse(report["decodedEmbeddingDistanceMeasured"])
        self.assertEqual(report["embeddingMetrics"]["pairsCompared"], 0)
        self.assertEqual(report["embeddingMetrics"]["excludedRejectedPairs"], 16)
        self.assertIsNone(report["embeddingMetrics"]["minimumCosineSimilarity"])

    def test_mixed_active_and_rejected_locations_keep_raw_differences_visible(self):
        left = bytes(144 * 32)
        right = bytearray(left); right[16 * 144] = 1
        report = comparison.compare_semantic(left, bytes(right), self.book, [True, False])
        self.assertTrue(report["decodedEmbeddingDistanceMeasured"])
        self.assertEqual(report["differentCodeBytes"], 1)
        self.assertEqual(report["embeddingMetrics"]["pairsCompared"], 16)
        self.assertEqual(report["embeddingMetrics"]["excludedRejectedPairs"], 16)

    def test_malformed_pair_lengths_or_mask_are_refused(self):
        for left, right, mask in ((bytes(144), bytes(144), [True]),
                                  (bytes(144 * 16), bytes(144 * 32), [True]),
                                  (bytes(144 * 16), bytes(144 * 16), [1])):
            with self.assertRaises(ValueError):
                comparison.compare_semantic(left, right, self.book, mask)


class CodebookCLIIntegrationTests(unittest.TestCase):
    def test_unpinned_codebook_produces_preserved_failure_without_loading_models(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            model_folder = root / "model"; model_folder.mkdir()
            book = model_folder / "book.bin"; book.write_bytes(bytes(comparison.CODEBOOK_BYTES))
            (root / "source.tsv").write_bytes(b"synthetic source\n")
            output = root / "report"
            with patch("sys.stdout", new=io.StringIO()), \
                 patch.object(comparison, "load_index", side_effect=AssertionError("Unpinned book reached native index reader")):
                result = comparison.main(["--reference-manifest", str(root / "gold/manifest.json"),
                    "--reference-sha256", "0" * 64, "--candidate-manifest", str(root / "candidate/manifest.json"),
                    "--candidate-sha256", "0" * 64, "--source", str(root / "source.tsv"),
                    "--codebook", str(book), "--out", str(output)])
            self.assertEqual(result, 1)
            report = json.loads((output / "object-index-comparison.json").read_bytes())
            self.assertEqual(report["status"], "FAILED")
            self.assertFalse(report["qualified"])

    def test_input_recheck_detects_codebook_change_during_comparison(self):
        raw = bytes(comparison.CODEBOOK_BYTES)
        checksum = comparison.digest(raw)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            book_path = root / "book.bin"; book_path.write_bytes(raw)
            source = root / "source.tsv"; source.write_bytes(b"source\n")
            manifest = {"countries": [""], "globalStart": 0, "totalLocations": 1,
                        "classes": [], "hotConcepts": [], "semantic": {"codebookSha256": checksum}}
            files = {"semantic-pq128.bin": bytes(144 * 16)}
            original = comparison.compare_semantic
            def changed(*args):
                result = original(*args)
                book_path.write_bytes(bytes([1]) + raw[1:])
                return result
            with patch.object(comparison, "CODEBOOK_SHA256", checksum), \
                 patch.object(comparison, "load_index", return_value=(manifest, files, "a" * 64)), \
                 patch.object(comparison, "compare_semantic", side_effect=changed):
                with self.assertRaisesRegex(ValueError, "comparison_inputs_changed"):
                    comparison.compare(root / "gold.json", "a" * 64, root / "actual.json", "a" * 64, source, book_path)

    def test_codebook_must_match_the_validated_manifest_identity(self):
        raw = bytes(comparison.CODEBOOK_BYTES)
        checksum = comparison.digest(raw)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            book_path = root / "book.bin"; book_path.write_bytes(raw)
            source = root / "source.tsv"; source.write_bytes(b"source\n")
            manifest = {"semantic": {"codebookSha256": "b" * 64}}
            with patch.object(comparison, "CODEBOOK_SHA256", checksum), \
                 patch.object(comparison, "load_index", return_value=(manifest, {}, "a" * 64)):
                with self.assertRaisesRegex(ValueError, "comparison_codebook_identity_mismatch"):
                    comparison.compare(root / "gold.json", "a" * 64, root / "actual.json", "a" * 64, source, book_path)


if __name__ == "__main__":
    unittest.main()
