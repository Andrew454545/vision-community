import importlib.util
import json
from pathlib import Path
import shutil
import struct
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("calibration_runner", Path(__file__).with_name("run_windows.py"))
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class CalibrationTest(unittest.TestCase):
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
        manifest = json.loads((runner.REPO / "community/runtime_manifest.json").read_text())
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
