import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from community import native_scene_runtime as packaging
from community import native_scene_search as native
from community.search_snapshot import (CONFIRMED_RESOURCE, build_snapshot,
                                       cache_file, digest, encoded)


class NativeSceneRuntimeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.binary_dir = self.root / "native-build"
        self.models = self.root / "canonical-models"
        self.binary_dir.mkdir()
        self.models.mkdir()
        self.binary = self.binary_dir / "mma-vision.exe"
        self.binary.write_bytes(b"synthetic-native-not-executed")
        self.binary.chmod(0o755)
        self.dll = self.binary_dir / "DirectML.dll"
        self.dll.write_bytes(b"synthetic-dependency-not-loaded")
        self.countries = self.root / "compiled-countries.txt"
        self.countries.write_bytes(b"Italy\nUSA\n")
        for name in native.MODEL_FILES:
            (self.models / name).write_bytes(b"synthetic-model-" + name.encode())
        self.build = self.root / "build-evidence.json"
        self.receipt = {"status": "BUILD_AND_SYNTHETIC_TESTS_PASSED", "features": "four-view-index",
                        "productionQualified": False, "layout": dict(packaging.LAYOUT),
                        "binary": {"file": self.binary.name, **self.pin(self.binary)},
                        "runtimeDLLs": [{"file": self.dll.name, **self.pin(self.dll)}],
                        "sourceFiles": [{"path": "app\\src\\data\\country-names.txt", **self.pin(self.countries)}]}
        self.build.write_bytes(encoded(self.receipt))
        self.model_pins = self.root / "model-pins.json"
        self.inventory = {"files": [{"path": "models/canonical/" + name, **self.pin(self.models/name)}
                                    for name in native.MODEL_FILES]}
        self.model_pins.write_bytes(encoded(self.inventory))
        self.output = self.root / "prepared-runtime"

    def pin(self, path):
        return {"bytes": path.stat().st_size, "sha256": native.file_digest(path)}

    def prepare(self, **changes):
        args = {"build": self.build, "build_sha256": native.file_digest(self.build),
                "binary_dir": self.binary_dir, "model_pins": self.model_pins,
                "model_pins_sha256": native.file_digest(self.model_pins), "models": self.models,
                "countries": self.countries, "countries_sha256": native.file_digest(self.countries),
                "destination": self.output, "policy_id": "synthetic-identity-only", "query_modes": ["textOnly"]}
        return packaging.prepare_runtime(**{**args, **changes})

    def snapshot(self):
        cache = self.root / "cache"
        cache.mkdir()
        record = (b"\x00\x3c" + bytes([1])*768)*4
        key = "four-view-v4/synthetic-runtime-test.i8"
        cache_file(cache, key).write_bytes(record)
        row = {"id": 1, "asset_id": "synthetic-pano", "capture": "synthetic-only", "lane": "scene",
               "model": "synthetic-input", "state": "published", "contributor_id": "disposable-test-account",
               "lat": 10, "lon": 20, "heading": 0, "pitch": 0, "zoom": 1, "country": "Italy",
               "camera_generation": "gen4", "output_sha256": digest(record), "four_view_sha256": digest(record),
               "location_output_sha256": digest(record), "four_view_key": key}
        inventory = encoded({"version": 1, "resource": CONFIRMED_RESOURCE, "rows": [row]})
        policy = encoded({"version": 1, "policyId": "synthetic-only", "inputModel": "synthetic-input",
                          "outputModel": "vision-four-view-v4", "references": [{"assetId": row["asset_id"],
                          "capture": row["capture"], "lat": 10, "lng": 20, "heading": 0, "pitch": 0, "zoom": 1,
                          "approvedSha256": [digest(record)]}]})
        (self.root / "inventory.json").write_bytes(inventory)
        (self.root / "policy.json").write_bytes(policy)
        snapshot = self.root / "snapshot"
        report = build_snapshot(self.root / "inventory.json", digest(inventory), self.root / "policy.json",
                                digest(policy), cache, snapshot)
        return snapshot, report["snapshotSha256"]

    def test_prepared_runtime_starts_existing_engine_with_sealed_snapshot_and_pinned_dll(self):
        report = self.prepare()
        snapshot, snapshot_pin = self.snapshot()
        work = self.root / "engine-work"
        work.mkdir()
        engine = native.NativeSceneEngine(self.output / "runtime.json", report["runtimeSha256"],
                                          snapshot, snapshot_pin, work)
        engine.verify_runtime()
        engine.verify_mount()
        self.assertEqual(engine.config["queryModes"], ["textOnly"])
        self.assertEqual(self.pin(self.output/self.dll.name), self.pin(self.dll))
        self.assertEqual(engine.config["files"]["countries.txt"], self.pin(self.countries))
        self.assertTrue(report["identityOnly"])
        self.assertFalse(report["productionQualified"])
        for name in native.MODEL_FILES:
            self.assertEqual((self.output/"models"/name).stat().st_mtime_ns, (self.models/name).stat().st_mtime_ns)
        if os.name != "nt":
            self.assertTrue((self.output/self.binary.name).stat().st_mode & 0o100)

    def test_independent_build_and_model_manifest_pins_are_required_before_any_output(self):
        for field in ("build_sha256", "model_pins_sha256"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.prepare(**{field: "f"*64})
            self.assertFalse(self.output.exists())

    def test_changed_binary_model_or_dependency_cannot_be_packaged(self):
        for target in (self.binary, self.dll, self.models/"text_model.onnx"):
            before = target.read_bytes()
            target.write_bytes(before + b"damaged")
            with self.subTest(target=target.name), self.assertRaisesRegex(native.NativeSearchError, "packaging_asset_changed"):
                self.prepare()
            self.assertFalse(self.output.exists())
            target.write_bytes(before)

    def test_compiled_country_dependency_is_bound_to_build_receipt(self):
        self.countries.write_bytes(b"France\n")
        with self.assertRaisesRegex(native.NativeSearchError, "compiled_countries_mismatch"):
            self.prepare()
        self.assertFalse(self.output.exists())

    def test_unsafe_dependency_incomplete_models_and_wrong_native_layout_cannot_package(self):
        cases = [("build", lambda d: d["runtimeDLLs"][0].update(file="../private.dll")),
                 ("build", lambda d: d["layout"].update(viewsPerLocation=1)),
                 ("models", lambda d: d["files"].pop()),
                 ("models", lambda d: d["files"][0].update(path=d["files"][1]["path"]))]
        for kind, change in cases:
            document = copy.deepcopy(self.receipt if kind == "build" else self.inventory)
            change(document)
            path = self.build if kind == "build" else self.model_pins
            path.write_bytes(encoded(document))
            with self.subTest(kind=kind), self.assertRaises(native.NativeSearchError):
                self.prepare()
            self.assertFalse(self.output.exists())
            self.build.write_bytes(encoded(self.receipt))
            self.model_pins.write_bytes(encoded(self.inventory))

    def test_existing_output_and_model_directory_overlap_preserve_original_files(self):
        self.output.mkdir()
        saved = self.output/"retained-evidence.json"
        saved.write_bytes(b"preserve-this")
        with self.assertRaises(FileExistsError):
            self.prepare()
        self.assertEqual(saved.read_bytes(), b"preserve-this")
        with self.assertRaisesRegex(native.NativeSearchError, "packaging_output_overlaps_input"):
            self.prepare(destination=self.models/"new-runtime")
        self.assertFalse((self.models/"new-runtime").exists())

    def test_copy_failure_preserves_partial_output_without_completed_runtime_marker(self):
        original = packaging.copy_asset
        calls = []
        def failed_copy(source, target, pin):
            calls.append(target)
            if len(calls) == 2:
                raise OSError("private original path must not be in report")
            return original(source, target, pin)
        with patch.object(packaging, "copy_asset", side_effect=failed_copy), self.assertRaises(OSError):
            self.prepare()
        self.assertTrue((self.output/self.binary.name).is_file())
        self.assertFalse((self.output/"runtime.json").exists())
        self.assertEqual(json.loads((self.output/"failure-report.json").read_bytes()),
                         {"ready": False, "error": "runtime_packaging_failed"})

    def test_linked_model_inputs_are_rejected_without_reading_alternate_file(self):
        original = self.models/"text_model.onnx"
        relocated = self.root/"same-bytes-but-linked.onnx"
        original.rename(relocated)
        try:
            original.symlink_to(relocated)
        except OSError:
            self.skipTest("Host cannot create symlinks")
        with self.assertRaisesRegex(native.NativeSearchError, "linked_engine_path"):
            self.prepare()
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
