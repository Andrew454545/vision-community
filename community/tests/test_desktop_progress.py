import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from community.desktop import DesktopApp


class DesktopProgressTests(unittest.TestCase):
    def test_new_pc_check_resets_previous_batch_before_native_work(self):
        observed = []
        with tempfile.TemporaryDirectory() as folder:
            def canary(*args, **kwargs):
                observed.append(app.snapshot())
                return {"status": "COMPLETE", "runtimeProfile": {"sha256": "b" * 64}, "submission": {}}
            app = DesktopApp(Path(folder), canary=canary, profile_matches=lambda *args, **kwargs: True)
            app.update(ready=True, savedCode=True, batchCompleted=8, batchTotal=8)
            app.client = SimpleNamespace(profile_id=None, request=lambda *args: (200,
                {"qualified": True, "profileId": "b" * 64, "expiresAt": time.time() + 3600}, None))
            with patch.object(app, "capabilities"):
                app.check_pc().join(timeout=10)
            self.assertEqual((observed[0]["batchCompleted"], observed[0]["batchTotal"]), (0, 112))
            self.assertEqual(app.snapshot()["phase"], "ready")
            self.assertTrue(app.snapshot()["qualified"])

    def test_processing_clears_canary_total_then_uses_actual_lease_size_without_credit(self):
        observed = []
        with tempfile.TemporaryDirectory() as folder:
            def indexer(**kwargs):
                observed.append(app.snapshot())
                kwargs["progress_callback"]({"event": "indexing", "completedLocations": 4, "totalLocations": 8})
                observed.append(app.snapshot())
                return {"batches": 0}
            app = DesktopApp(Path(folder), indexer=indexer)
            app.update(ready=True, savedCode=True, batchCompleted=112, batchTotal=112, units=8)
            app.client = SimpleNamespace(pending=1, undelivered=0,
                resume_submissions=lambda: {"accepted": 0, "unitsEarned": 0})
            with patch.object(app, "require_qualification"), patch.object(app, "capabilities"):
                app.start().join(timeout=10)
            self.assertEqual((observed[0]["batchCompleted"], observed[0]["batchTotal"]), (0, 0))
            self.assertEqual((observed[1]["batchCompleted"], observed[1]["batchTotal"]), (4, 8))
            self.assertEqual(app.snapshot()["units"], 8)
            self.assertEqual(app.snapshot()["completed"], 0)
            self.assertEqual(app.snapshot()["pending"], 1)
            self.assertEqual(app.snapshot()["phase"], "ready")


if __name__ == "__main__":
    unittest.main()
