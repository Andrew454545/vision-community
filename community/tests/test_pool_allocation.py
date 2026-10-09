"""Offline integration checks for the actual bounded native pool tools.

Set VISION_POOL_IDENTITY and VISION_POOL_EXPORT to locally built binaries.
PyArrow is an operator dependency; the normal application does not need it.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

IDENTITY = os.environ.get("VISION_POOL_IDENTITY")
EXPORT = os.environ.get("VISION_POOL_EXPORT")
HAS_ARROW = importlib.util.find_spec("pyarrow") is not None
TOOLS = Path(__file__).resolve().parents[2] / "deploy/cloudflare/tools"


class PoolSplitTests(unittest.TestCase):
    def test_disjoint_union_reuses_only_ordered_verified_prefix(self):
        spec = importlib.util.spec_from_file_location("pool_split", TOOLS / "pool-split.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        original = bytes([0b10101101, 0b11001001, 0b111, 0b10101])
        outputs = module.split(original, 29, 3, 4)
        union = bytes([outputs[0][i] | outputs[1][i] | outputs[2][i] | outputs[3][i] for i in range(4)])
        self.assertEqual(union, bytes([0b10100000, *original[1:]]))
        self.assertEqual(sum(b.bit_count() for out in outputs for b in out) + 3,
                         sum(b.bit_count() for b in original))
        for i in range(4):
            for j in range(i):
                self.assertTrue(all(not (a & b) for a, b in zip(outputs[i], outputs[j])))
        with self.assertRaises(ValueError):
            module.split(original, 29, 100, 4)
        with self.assertRaises(ValueError):
            module.split(b"\x80", 1, 0, 4)


@unittest.skipUnless(IDENTITY and EXPORT and HAS_ARROW, "Explicit native binaries and operator PyArrow are required")
class PoolAllocationTests(unittest.TestCase):
    def setUp(self):
        import pyarrow as pa
        self.pa = pa
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.countries = self.root / "countries.tsv"
        self.countries.write_text("1\tCanada\n")

    def pano(self, n):
        return str(n).zfill(22)

    def tsv(self, name, panos):
        p = self.root / name
        p.write_text("".join(f"map\t{i}\t1\t2\t3\t4\t1\t{pano}\tCanada\n" for i, pano in enumerate(panos)))
        return p

    def arrow(self, panos, tags=None):
        pa = self.pa
        arrays = {"id": pa.array(range(len(panos)), type=pa.uint32()),
                  "pano_id": pa.array(panos, type=pa.string()),
                  "tags": pa.array(tags or [[1] for _ in panos], type=pa.list_(pa.uint32()))}
        for k, v in {"lat": 1., "lng": 2., "heading": 3., "pitch": 4., "zoom": 1.}.items():
            arrays[k] = pa.array([v] * len(panos), type=pa.float64())
        batch = pa.record_batch(arrays)
        path = self.root / "source.arrow"
        with pa.OSFile(str(path), "wb") as sink:
            with pa.ipc.new_file(sink, batch.schema) as writer:
                writer.write_batch(batch)
        return path

    def run_identity(self, spec, path, count, output="sealed"):
        p = self.root / "spec.tsv"
        p.write_text(spec)
        result = subprocess.run([IDENTITY, "source", str(p), str(self.root / output), str(count), str(path)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return self.root / output

    def test_exact_panorama_exclusion_and_duplicate_poses(self):
        local = self.tsv("indexed.tsv", [self.pano(1)])
        reserve = self.tsv("reserved.tsv", [self.pano(2)])
        path = self.arrow([self.pano(x) for x in [1, 2, 3, 3, 4]])
        out = self.run_identity(f"indexed\t0\t{local}\nreserved\t1\t{reserve}\n", path, 5)
        report = json.loads((out / "identity-report.json").read_text())
        self.assertEqual((report["eligibleUnique"], report["excludedLocalRows"], report["excludedReservedRows"],
                          report["duplicateSourceRows"]), (2, 1, 1, 1))
        self.assertEqual((out / "eligible.bits").read_bytes(), bytes([0b10100]))
        p = self.root / "spec.tsv"
        again = subprocess.run([IDENTITY, "source", str(p), str(out), "5", str(path)], capture_output=True)
        self.assertNotEqual(again.returncode, 0)

    def test_zero_queue_prefix_does_not_exclude_future_work(self):
        queue = self.tsv("queue.tsv", [self.pano(1), self.pano(2)])
        path = self.arrow([self.pano(1), self.pano(2)])
        out = self.run_identity(f"queue\t0\t{queue}\n", path, 2)
        self.assertEqual(json.loads((out / "identity-report.json").read_text())["eligibleUnique"], 2)

    def test_reservation_skips_indexed_and_duplicate_queue_ids(self):
        indexed = self.tsv("indexed.tsv", [self.pano(1)])
        queue = self.tsv("queue.tsv", [self.pano(x) for x in [1, 2, 2, 3, 4]])
        spec = self.root / "spec.tsv"
        spec.write_text(f"indexed\t0\t{indexed}\nqueue\t1\t{queue}\n")
        out = self.root / "owner"
        result = subprocess.run([IDENTITY, "owner", str(spec), str(out), "5", "2"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = (out / "local-reserved.tsv").read_text().splitlines()
        self.assertEqual([r.split("\t")[7] for r in rows], [self.pano(2), self.pano(3)])
        self.assertEqual(json.loads((out / "local-boundary.json").read_text())["exclusiveEndQueueRow"], 4)
        self.assertEqual(len(queue.read_text().splitlines()), 5)

    def test_missing_ack_keeps_current_shard(self):
        path = self.arrow([self.pano(1)])
        mask = self.root / "mask"
        mask.write_bytes(b"\x01")
        out = self.root / "render"
        result = subprocess.run([EXPORT, str(path), str(mask), str(self.countries), str(out), "1", "1"],
                                input="", capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("current shard retained", result.stderr)
        self.assertTrue((out / "shard-000000.tsv").is_file())

    def test_bad_country_and_out_of_range_mask_fail_closed(self):
        path = self.arrow([self.pano(1)], [[999]])
        mask = self.root / "mask"
        mask.write_bytes(b"\x01")
        result = subprocess.run([EXPORT, str(path), str(mask), str(self.countries), str(self.root / "bad-country"), "1", "1"],
                                input="", capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("outside authority", result.stderr)
        mask.write_bytes(b"\x80")
        result = subprocess.run([EXPORT, str(path), str(mask), str(self.countries), str(self.root / "bad-mask"), "1", "1"],
                                input="", capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("out-of-range", result.stderr)

    def test_publisher_readback_failure_preserves_unregistered_shard(self):
        path = self.arrow([self.pano(1)])
        out = self.run_identity("", path, 1)
        adapter = self.root / "adapter.py"
        adapter.write_text("def put(key,data): pass\ndef get(key): return b'corrupt remote bytes'\n")
        command = [sys.executable, str(TOOLS / "pool-publish.py"), "--source", str(path),
                   "--source-sha256", hashlib.sha256(path.read_bytes()).hexdigest(), "--source-rows", "1",
                   "--mask", str(out / "eligible.bits"), "--countries", str(self.countries),
                   "--identity-report", str(out / "identity-report.json"), "--exporter", EXPORT,
                   "--adapter", str(adapter), "--output", str(self.root / "publication"),
                   "--prefix", "catalog/offline-test", "--shard-id-start", "-100000"]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("readback mismatch", result.stderr)
        self.assertTrue((self.root / "publication/render-0/shard-000000.tsv").exists())
        self.assertFalse((self.root / "publication/complete.private.json").exists())
        self.assertFalse((self.root / "publication/manifest.private.json").exists())


if __name__ == "__main__":
    unittest.main()
