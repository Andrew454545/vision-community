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
    install_runtime,
    load_manifest,
    manifest_path,
)


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
        entry = {
            "asset": "vision-object",
            "path": "object-runtime/vision-object",
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "executable": True,
        }
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)

            def fetch(url, partial, item):
                self.assertTrue(url.endswith("/vision-object"))
                partial.write_bytes(payload)

            with mock.patch("community.bootstrap.download_file", fetch):
                first = install_runtime({"files": [entry]}, root, release="https://example.test/runtime")
                second = install_runtime({"files": [entry]}, root, release="https://example.test/runtime")
            path = root / "object-runtime" / "vision-object"
            self.assertEqual(first, ["installed vision-object"])
            self.assertEqual(second, ["present vision-object"])
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
