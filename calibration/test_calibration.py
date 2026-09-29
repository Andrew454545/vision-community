import importlib.util
import json
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("calibration_runner", Path(__file__).with_name("run_windows.py"))
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class CalibrationTest(unittest.TestCase):
    def test_decoded_metrics_respect_direction_signed_values_and_scale(self):
        def record(values, scale=1):
            return (struct.pack("<e", scale) + struct.pack("<768b", *(values + [0] * (768 - len(values))))) * 4

        original = record([3, -4])
        same_direction = runner.decoded_difference(record([3, -4], 2), original)
        self.assertAlmostEqual(same_direction["cosine_similarity"]["mean"], 1)
        self.assertAlmostEqual(same_direction["relative_l2_error"]["mean"], 1)
        self.assertAlmostEqual(same_direction["candidate_to_reference_norm_ratio"]["mean"], 2)
        self.assertAlmostEqual(same_direction["decoded_coordinate_mae"], 7 / 768)
        opposite = runner.decoded_difference(record([-3, 4]), original)
        self.assertAlmostEqual(opposite["cosine_similarity"]["min"], -1)
        self.assertAlmostEqual(opposite["normalized_l2_distance"]["max"], 2)
        orthogonal = runner.decoded_difference(record([4, 3]), original)
        self.assertAlmostEqual(orthogonal["cosine_similarity"]["mean"], 0)
        equivalent = runner.decoded_difference(record([6, -8], 0.5), original)
        self.assertEqual(equivalent["decoded_coordinate_rmse"], 0)
        self.assertEqual(equivalent["interpretation"], "DIAGNOSTIC_ONLY_NO_ACCEPTANCE_THRESHOLD")

    def test_decoded_comparison_rejects_bad_geometry_scale_and_zero_norm(self):
        valid = (struct.pack("<e", 1) + bytes([1]) * 768) * 4
        for candidate in (b"", valid[:-1], valid + valid):
            with self.assertRaisesRegex(ValueError, "incomparable_geometry"):
                runner.decoded_difference(candidate, valid)
        for scale in (0, -1, float("inf"), float("nan")):
            with self.assertRaisesRegex(ValueError, "invalid_view_scale"):
                runner.decoded_difference((struct.pack("<e", scale) + bytes([1]) * 768) * 4, valid)
        with self.assertRaisesRegex(ValueError, "zero_norm_view"):
            runner.decoded_difference((struct.pack("<e", 1) + bytes(768)) * 4, valid)

    def test_thread_plan_balances_order_and_requires_explicit_valid_cells(self):
        self.assertEqual(runner.trial_plan([1, 2, 4]),
                         [(1, 1), (2, 1), (4, 1), (2, 2), (4, 2), (1, 2), (4, 3), (1, 3), (2, 3)])
        self.assertEqual(runner.trial_plan([1]), [(1, 1), (1, 2), (1, 3)])
        for counts in ([], [1, 1], [0], [8]):
            with self.assertRaises(ValueError):
                runner.trial_plan(counts)

    def test_thread_cells_use_fresh_paths_and_keep_failed_trial_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            results = root / "results"
            results.mkdir()
            summary = {"requested_inference_threads": [1, 2], "runs": [], "production_approved": False}
            calls = []

            def indexer(_fixture, **kwargs):
                calls.append(kwargs)
                if len(calls) == 3:
                    raise RuntimeError("simulated_indexer_failure")

            blob = b"test payload"
            with patch.object(runner, "verify_output", return_value=(blob, {"payload_sha256": "abc"})), \
                 patch.object(runner, "compare_payloads", return_value={"diagnostic": True}):
                with self.assertRaisesRegex(RuntimeError, "simulated_indexer_failure"):
                    runner.run_trials(results, root, root / "binary", root / "model", summary, indexer=indexer)
            self.assertEqual([call["inference_threads"] for call in calls], [1, 2, 2])
            self.assertEqual(len({call["index_dir"] for call in calls}), 3)
            self.assertEqual(summary["completed_runs"], 2)
            self.assertEqual(summary["failed_runs"], 1)
            self.assertEqual(summary["unstarted_runs"], 3)
            self.assertFalse(summary["production_approved"])
            self.assertIn("threads_2_vs_1_replica_1", summary["cross_thread_comparisons"])
            failure = json.loads((results / "runs/threads-02/run-02/run-summary.json").read_text())
            self.assertEqual(failure["error"], "simulated_indexer_failure")

    def test_existing_runtime_is_verified_without_repair(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "runtime.bin"
            path.write_bytes(b"good")
            assets = [{"path": "runtime.bin", "bytes": 4, "sha256": runner.sha(path)}]
            runner.verify_existing_runtime(root, assets)
            path.write_bytes(b"bad!")
            with self.assertRaisesRegex(ValueError, "existing_runtime_checksum_mismatch"):
                runner.verify_existing_runtime(root, assets)
            self.assertEqual(path.read_bytes(), b"bad!")

    def test_real_fixture_integrity_and_canary(self):
        inventory = runner.verify_fixture()
        self.assertIn("historical-reference.i8", inventory)

    def test_modified_fixture_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            copied = Path(temp) / "fixture"
            shutil.copytree(runner.FIXTURE, copied)
            with (copied / "fixture-1024.tsv").open("ab") as f:
                f.write(b"\n")
            with self.assertRaisesRegex(ValueError, "fixture_file_changed"):
                runner.verify_fixture(copied)

    def test_exact_counts_include_scales_and_view_boundaries(self):
        view = struct.pack("<e", 1) + bytes(768)
        original = view * 4096
        changed = bytearray(original)
        changed[0] ^= 1
        changed[770 + 10] = 1
        changed[3080 + 10] = 1
        diff = runner.exact_difference(original, bytes(changed))
        self.assertEqual(diff, {"byte_identical": False, "affected_locations": 2,
                               "affected_views": 3, "affected_scales": 1, "differing_bytes": 3})
        with self.assertRaisesRegex(ValueError, "incomparable_geometry"):
            runner.exact_difference(original, original[:-1])

    def test_invalid_scale_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid_view_scale"):
            runner.record_hashes(bytes(3080 * 1024))

    def test_incomplete_mask_cannot_pass_on_payload_length(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); index = root / "index"; index.mkdir()
            runner.write_json(root / "checkpoint.json", {"nextLocationIndex": 1024, "incompleteLocations": 0})
            runner.write_json(index / "manifest.json", {"version": 4, "viewsPerLocation": 4,
                "bytesPerLocation": 3080, "indexedLocations": 1024})
            shutil.copyfile(runner.FIXTURE / "historical-reference.i8", index / "shard-000000.i8")
            (index / "shard-000000.mask").write_bytes(b"\x0f" * 1023 + b"\x07")
            with self.assertRaisesRegex(ValueError, "incomplete_view_mask"):
                runner.verify_output(root)
            (index / "shard-000000.mask").write_bytes(b"\x0f" * 1024)
            self.assertEqual(runner.verify_output(root)[1]["locations"], 1024)

    def test_scene_only_asset_selection(self):
        manifest_path = runner.REPO / "community/runtime_manifest.json"
        self.assertEqual(runner.sha(manifest_path), runner.EXPECTED_RUNTIME_SHA256)
        manifest = json.loads(manifest_path.read_text())
        assets = runner.scene_assets(manifest)
        self.assertEqual(len(assets), 10)
        self.assertFalse(any("object" in a["asset"] for a in assets))

    def test_package_redacts_paths_and_preserves_binary(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); results = root / "results"; results.mkdir()
            runner.write_json(results / "input.json", {"path": str(root / "models")})
            blob = b"\x00\xffunmodified"
            (results / "record.i8").write_bytes(blob)
            archive = runner.make_results_zip(results, root)
            with runner.zipfile.ZipFile(archive) as z:
                self.assertEqual(z.read("record.i8"), blob)
                self.assertNotIn(str(root), z.read("input.json").decode())
                self.assertIn("$TEST_ROOT", z.read("input.json").decode())
                json.loads(z.read("input.json"))

    def test_process_adapter_prevents_hidden_resume(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            adapter = runner.LoggedProcess(root, root)
            adapter.index_calls = 1
            with self.assertRaisesRegex(RuntimeError, "no_automatic_resume"):
                adapter(["unused", "index-four-views"], {}, root)


if __name__ == "__main__":
    unittest.main()
