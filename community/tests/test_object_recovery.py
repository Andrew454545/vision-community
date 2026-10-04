import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from community.object_index import (OBJECT_FEATURE, _default_runner, index_object_tsv,
                                    object_index_is_complete)
from community.vision_index import MAX_INDEX_FAILURES, MAX_NO_PROGRESS, VisionIndexError

CPU_POOL = "[vision-object] ONNX Runtime global threads: 1, spinning disabled"


class ObjectRecoveryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / "index"
        self.calls = []

    def checkpoint(self, cursor, **changes):
        self.output.mkdir(exist_ok=True)
        (self.output / "checkpoint.json").write_text(json.dumps({
            "feature": OBJECT_FEATURE, "nextLocationIndex": cursor, "completed": False, **changes,
        }))

    def complete(self, total=1):
        (self.output / "manifest.json").write_text(json.dumps({"completed": True, "indexedLocations": total}))

    def run_index(self, action, total=1):
        def runner(argv, _env, _cwd):
            self.calls.append(argv)
            if "index-segment" in argv:
                code, stdout, stderr = action()
                return code, stdout, stderr + "\n" + CPU_POOL if code == 0 else stderr
            return 0, json.dumps({"valid": True, "indexVersion": 4, "full": "--full" in argv}), CPU_POOL
        index_object_tsv(self.root / "locations.tsv", output_dir=self.output, source_id="synthetic",
                         total=total, binary=self.root / "vision-object", model_dir=self.root / "models",
                         runner=runner, use_nice=False)

    def failures(self):
        return [json.loads(path.read_text()) for path in self.root.glob("object-failure-*.json")]

    def test_transient_exits_resume_then_require_both_native_verifications(self):
        attempts = 0
        def action():
            nonlocal attempts
            attempts += 1
            if attempts < MAX_INDEX_FAILURES:
                return 1, "", "synthetic transient interruption"
            self.complete()
            return 0, "", ""
        self.run_index(action)
        self.assertEqual(attempts, MAX_INDEX_FAILURES)
        self.assertEqual(len(self.calls), MAX_INDEX_FAILURES + 2)
        self.assertIn("--full", self.calls[-1])
        self.assertEqual(self.failures(), [])

    def test_repeated_failures_stop_at_a_finite_limit_and_preserve_each_failure(self):
        self.checkpoint(0)
        for _ in range(2):
            self.calls = []
            with patch("community.object_index.time.time_ns", return_value=1000):
                with self.assertRaisesRegex(VisionIndexError, "vision_binary_failed"):
                    self.run_index(lambda: (1, "", "private native error"))
            self.assertEqual(len(self.calls), MAX_INDEX_FAILURES)
        self.assertTrue((self.output / "checkpoint.json").exists())
        reports = self.failures()
        self.assertEqual(len(reports), 2)
        self.assertTrue(all(row["failedAttempts"] == MAX_INDEX_FAILURES for row in reports))
        self.assertNotIn("private", json.dumps(reports))

    def test_clean_exit_without_progress_stops_instead_of_spinning_forever(self):
        with self.assertRaisesRegex(VisionIndexError, "vision_no_progress"):
            self.run_index(lambda: (0, "", ""))
        self.assertEqual(len(self.calls), MAX_NO_PROGRESS)
        self.assertEqual(self.failures()[0]["noProgressAttempts"], MAX_NO_PROGRESS)

    def test_real_progress_can_resume_many_clean_checkpoints_without_the_stall_limit(self):
        cursor, total = 0, MAX_NO_PROGRESS + 2
        def action():
            nonlocal cursor
            cursor += 1
            self.checkpoint(cursor)
            if cursor == total:
                self.complete(total)
            return 0, "", ""
        self.run_index(action, total)
        self.assertEqual(cursor, total)
        self.assertEqual(len(self.calls), total + 2)

    def test_regressed_malformed_and_noninteger_checkpoints_stop_with_evidence(self):
        self.checkpoint(1)
        def regress():
            self.checkpoint(0)
            return 0, "", ""
        with self.assertRaisesRegex(VisionIndexError, "object_checkpoint_regressed"):
            self.run_index(regress, 2)
        for value in (True, "1", -1, 3):
            self.checkpoint(value)
            self.calls = []
            with self.assertRaisesRegex(VisionIndexError, "invalid_object_checkpoint"):
                self.run_index(lambda: (0, "", ""), 2)
            self.assertEqual(self.calls, [])
        (self.output / "checkpoint.json").write_text("not-json")
        with self.assertRaisesRegex(VisionIndexError, "invalid_object_checkpoint"):
            self.run_index(lambda: (0, "", ""), 2)

    def test_regression_after_failed_native_exit_cannot_be_hidden_by_the_retry(self):
        self.checkpoint(1)
        def regress():
            self.checkpoint(0)
            return 1, "", ""
        with self.assertRaisesRegex(VisionIndexError, "object_checkpoint_regressed"):
            self.run_index(regress, 2)
        self.assertEqual(len(self.calls), 1)

    def test_launch_timeout_and_unexpected_errors_are_not_retried_indefinitely(self):
        for code in ("vision_binary_launch_failed", "vision_binary_timeout"):
            self.calls = []
            def fail():
                raise VisionIndexError(code)
            with self.assertRaisesRegex(VisionIndexError, code):
                self.run_index(fail)
            self.assertEqual(len(self.calls), 1)
        def private_error():
            raise OSError("private local path")
        with self.assertRaises(OSError):
            self.run_index(private_error)
        self.assertTrue(any(report["code"] == "object_indexing_failed" for report in self.failures()))
        self.assertNotIn("private local path", json.dumps(self.failures()))

    def test_completion_cannot_be_claimed_with_coerced_or_overrun_cursor_values(self):
        for value in (True, "1", 2):
            self.checkpoint(value, completed=True)
            self.assertFalse(object_index_is_complete(self.output, 1))
        self.checkpoint(1, completed=True)
        self.assertTrue(object_index_is_complete(self.output, 1))
        self.complete(True)
        (self.output / "checkpoint.json").unlink()
        self.assertFalse(object_index_is_complete(self.output, 1))

    def test_failed_full_verification_preserves_completed_data_and_failure_phase(self):
        self.output.mkdir()
        self.complete()
        def runner(argv, _env, _cwd):
            self.calls.append(argv)
            return 0, json.dumps({"valid": "--full" not in argv, "indexVersion": 4, "full": True}), CPU_POOL
        with self.assertRaisesRegex(VisionIndexError, "verification_failed"):
            index_object_tsv(self.root / "locations.tsv", output_dir=self.output, source_id="synthetic", total=1,
                             binary=self.root / "vision-object", model_dir=self.root / "models", runner=runner)
        self.assertEqual(len(self.calls), 2)
        self.assertTrue((self.output / "manifest.json").exists())
        self.assertEqual(self.failures()[0]["phase"], "verification")

    def test_cpu_runtime_cannot_ignore_budget_or_retry_missing_attestation(self):
        for stderr in ("", CPU_POOL.replace("threads: 1", "threads: 4")):
            self.calls = []
            def runner(argv, env, _cwd):
                self.calls.append(argv)
                for key in ("VISION_ORT_THREADS", "ORT_NUM_THREADS", "OMP_NUM_THREADS", "RAYON_NUM_THREADS"):
                    self.assertEqual(env[key], "1")
                self.assertEqual(argv[argv.index("--checkpoint-every") + 1], "1")
                self.assertEqual(argv[argv.index("--stop-after") + 1], "1")
                self.complete()
                return 0, "", stderr
            with patch.dict(os.environ, {"VISION_ORT_THREADS": "64", "OMP_NUM_THREADS": "64"}):
                with patch("community.object_index.object_uses_cpu", return_value=True):
                    with self.assertRaisesRegex(VisionIndexError, "vision_object_runtime_update_required"):
                        index_object_tsv(self.root / "locations.tsv", output_dir=self.output,
                            source_id="synthetic", total=1, binary=self.root / "vision-object",
                            model_dir=self.root / "models", runner=runner)
            self.assertEqual(len(self.calls), 1)
            self.assertTrue((self.output / "manifest.json").exists())
            (self.output / "manifest.json").unlink()
        self.assertTrue(all(x["code"] == "vision_object_runtime_update_required" for x in self.failures()))

    def test_completed_cpu_checkpoint_still_requires_the_bounded_verifier(self):
        self.output.mkdir()
        self.complete()
        def runner(argv, _env, _cwd):
            self.calls.append(argv)
            return 0, json.dumps({"valid": True, "indexVersion": 4, "full": True}), ""
        with patch("community.object_index.object_uses_cpu", return_value=True):
            with self.assertRaisesRegex(VisionIndexError, "vision_object_runtime_update_required"):
                index_object_tsv(self.root / "locations.tsv", output_dir=self.output,
                    source_id="synthetic", total=1, binary=self.root / "vision-object",
                    model_dir=self.root / "models", runner=runner)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.failures()[0]["phase"], "verification")

    def test_mac_reference_process_settings_remain_compatible(self):
        def runner(argv, env, _cwd):
            self.calls.append(argv)
            self.assertEqual(env["VISION_ORT_THREADS"], "reference-setting")
            if "index-segment" in argv:
                self.assertNotIn("--cpu", argv)
                self.assertNotIn("--stop-after", argv)
                self.assertEqual(argv[argv.index("--checkpoint-every") + 1], "10")
                self.complete()
            return 0, json.dumps({"valid": True, "indexVersion": 4, "full": True}), ""
        with patch.dict(os.environ, {"VISION_ORT_THREADS": "reference-setting"}):
            with patch("community.object_index.object_uses_cpu", return_value=False):
                index_object_tsv(self.root / "locations.tsv", output_dir=self.output,
                    source_id="synthetic", total=1, binary=self.root / "vision-object",
                    model_dir=self.root / "models", runner=runner)
        self.assertEqual(len(self.calls), 3)

    def test_default_object_runner_times_out_and_keeps_logs_instead_of_hanging(self):
        with patch("community.vision_index.INDEX_TIMEOUT_SECONDS", 0.01):
            with self.assertRaisesRegex(VisionIndexError, "vision_binary_timeout"):
                _default_runner([sys.executable, "-c", "import time; time.sleep(60)"], {}, self.root)
        reports = list(self.root.glob("process-*.exit.json"))
        self.assertEqual(len(reports), 1)
        self.assertEqual(json.loads(reports[0].read_text())["status"], "TIMEOUT")
        self.assertEqual(len(list(self.root.glob("process-*.stderr.log"))), 1)


if __name__ == "__main__":
    unittest.main()
