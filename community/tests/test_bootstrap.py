import hashlib
import json
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from community.bootstrap import (
    BootstrapError,
    destination,
    download_file,
    files_for_platform,
    install_runtime,
    load_manifest,
    manifest_path,
    runtime_platform,
)
from community.object_index import index_segment_arguments, object_uses_cpu
from community.vision_index import command_prefix


class BootstrapTests(unittest.TestCase):
    def test_published_manifest_stays_out_of_live_vision_paths(self):
        manifest = load_manifest(manifest_path())
        self.assertGreaterEqual(len(manifest["files"]), 10)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for entry in manifest["files"]:
                path = destination(root, entry["path"])
                self.assertTrue(path.is_relative_to(root))
                self.assertNotIn("coreml-cache", entry["path"])
                self.assertNotIn("..", Path(entry["path"]).parts)
        windows = {item["path"] for item in files_for_platform(manifest, "windows-x86_64")}
        self.assertIn("bin/mma-vision.exe", windows)
        self.assertIn("bin/vision-object.exe", windows)
        self.assertIn("bin/DirectML.dll", windows)
        self.assertNotIn("bin/mma-vision.exe", {item["path"] for item in files_for_platform(manifest, "darwin-arm64")})

    def test_rejects_paths_outside_the_runtime_root(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with self.assertRaises(BootstrapError) as raised:
                destination(root, "../outside.bin")
            self.assertEqual(raised.exception.code, "unsafe_runtime_path")
            with self.assertRaises(BootstrapError) as raised:
                destination(root, "models/object-hybrid-v1/coreml-cache/model.mlmodelc")
            self.assertEqual(raised.exception.code, "refusing_live_vision_path")

    def test_install_writes_a_checked_file_and_skips_it_the_next_time(self):
        payload = b"vision-object-bytes"
        scene = b"mma-vision-bytes"
        entries = [
            {
                "asset": "mma-vision",
                "path": "automation/runtime/current/.vision-build/four-view-index/release/mma-vision",
                "bytes": len(scene),
                "sha256": hashlib.sha256(scene).hexdigest(),
                "executable": True,
            },
            {
                "asset": "vision-object",
                "path": "object-runtime/vision-object",
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "executable": True,
            },
        ]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)

            def fetch(url, partial, item):
                partial.write_bytes(scene if url.endswith("/mma-vision") else payload)

            with mock.patch("community.bootstrap.download_file", fetch):
                first = install_runtime({"files": entries}, root, release="https://example.test/runtime", platform_name="darwin-arm64")
                second = install_runtime({"files": entries}, root, release="https://example.test/runtime", platform_name="darwin-arm64")
            path = root / "object-runtime" / "vision-object"
            self.assertEqual(first, ["installed mma-vision", "installed vision-object"])
            self.assertEqual(second, ["present mma-vision", "present vision-object"])
            self.assertEqual(path.read_bytes(), payload)
            self.assertTrue(path.stat().st_mode & stat.S_IXUSR)

    def test_download_rejects_a_mismatched_file(self):
        payload = b"wrong"
        entry = {"bytes": 4, "sha256": hashlib.sha256(b"good").hexdigest()}

        class Response:
            def read(self, _size):
                if not hasattr(self, "done"):
                    self.done = True
                    return payload
                return b""

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        with tempfile.TemporaryDirectory() as folder:
            partial = Path(folder) / "file.partial"
            with mock.patch("community.bootstrap.urllib.request.urlopen", return_value=Response()):
                with self.assertRaises(BootstrapError) as raised:
                    download_file("https://example.test/file", partial, entry)
            self.assertEqual(raised.exception.code, "runtime_mismatch")
            self.assertFalse(partial.exists())


class BootstrapPlatformTests(unittest.TestCase):
    def test_platform_names(self):
        self.assertEqual(runtime_platform("win32", "AMD64"), "windows-x86_64")
        self.assertEqual(runtime_platform("linux", "aarch64"), "linux-arm64")
        self.assertEqual(runtime_platform("darwin", "arm64"), "darwin-arm64")

    def test_each_computer_gets_its_own_programs(self):
        manifest = {
            "files": [
                {"asset": "mma-vision", "executable": True, "platforms": ["darwin-arm64"], "path": "bin/mma-vision"},
                {"asset": "vision-object", "executable": True, "platforms": ["darwin-arm64"], "path": "bin/vision-object"},
                {"asset": "mma-vision-windows-x86_64.exe", "executable": True, "platforms": ["windows-x86_64"], "path": "bin/mma-vision.exe"},
                {"asset": "vision-object-windows-x86_64.exe", "executable": True, "platforms": ["windows-x86_64"], "path": "bin/vision-object.exe"},
                {"asset": "siglip-tokenizer.json", "path": "models/tokenizer.json"},
            ]
        }
        mac = [item["asset"] for item in files_for_platform(manifest, "darwin-arm64")]
        windows = [item["asset"] for item in files_for_platform(manifest, "windows-x86_64")]
        self.assertEqual(mac, ["mma-vision", "vision-object", "siglip-tokenizer.json"])
        self.assertEqual(windows, ["mma-vision-windows-x86_64.exe", "vision-object-windows-x86_64.exe", "siglip-tokenizer.json"])
        with self.assertRaises(BootstrapError) as raised:
            files_for_platform(manifest, "darwin-x86_64")
        self.assertEqual(raised.exception.code, "unsupported_platform")

    def test_windows_object_indexing_uses_cpu_and_skips_nice(self):
        self.assertFalse(object_uses_cpu("darwin"))
        self.assertTrue(object_uses_cpu("win32"))
        self.assertTrue(object_uses_cpu("linux"))
        with mock.patch("community.object_index.sys.platform", "win32"):
            arguments = index_segment_arguments(
                model_dir=Path("models"),
                source_tsv=Path("locations.tsv"),
                output_dir=Path("index"),
                source_id="community-" + "ab" * 8,
                total=1,
                global_start=0,
                model_cache=Path("cache"),
            )
        self.assertEqual(arguments[-1], "--cpu")
        binary = Path("mma-vision.exe")
        with mock.patch("community.vision_index.sys.platform", "win32"):
            self.assertEqual(command_prefix(binary, nice_level=19, use_nice=True), [str(binary)])


class BootstrapPageTests(unittest.TestCase):
    def test_public_instructions_use_the_setup_command(self):
        root = Path(__file__).resolve().parents[2]
        readme = (root / "README.md").read_text(encoding="utf-8")
        page = (root / "community" / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn("python3 -m community.bootstrap", readme)
        self.assertIn("python3 -m community.bootstrap", page)
        manifest = json.loads((root / "community" / "runtime_manifest.json").read_text(encoding="utf-8"))
        assets = [item["asset"] for item in manifest["files"]]
        self.assertEqual(len(assets), len(set(assets)))
