import json
from pathlib import Path
import tempfile
import unittest

from community.work_plan import WorkPlan, WorkPlanError


class WorkPlanTests(unittest.TestCase):
    def test_both_alternates_across_fresh_process_instances_and_recovers_interrupted_lane_first(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            plan = WorkPlan(root)
            plan.select("both")
            self.assertEqual(plan.begin(), "scene")
            recovered = WorkPlan(root)
            self.assertEqual(recovered.begin(), "scene")
            with self.assertRaisesRegex(WorkPlanError, "unfinished_lane_needs_recovery"):
                recovered.select("object")
            recovered.finish("scene")
            restarted = WorkPlan(root)
            self.assertEqual(restarted.begin(), "object")
            restarted.finish("object")
            self.assertEqual(WorkPlan(root).next_lane, "scene")

    def test_selection_and_single_lane_runs_never_change_account_or_saved_outputs(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "account.json").write_text("private retained account")
            (root / "saved-index.i8").write_bytes(b"retained result")
            for choice in ("scene", "object", "both"):
                plan = WorkPlan(root)
                plan.select(choice)
                lane = plan.begin()
                plan.finish(lane)
                self.assertEqual((root / "account.json").read_text(), "private retained account")
                self.assertEqual((root / "saved-index.i8").read_bytes(), b"retained result")

    def test_corrupt_selection_and_illegal_handover_are_preserved_and_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            plan = WorkPlan(root)
            with self.assertRaises(WorkPlanError):
                plan.select("unknown")
            with self.assertRaises(WorkPlanError):
                plan.finish("scene")
            path = root / "work-selection.json"
            for value in ({"version": 1}, {"version": True, "workType": "both", "nextLane": "scene", "activeLane": None},
                          {"version": 1, "workType": "scene", "nextLane": "object", "activeLane": None}):
                raw = json.dumps(value)
                path.write_text(raw)
                with self.assertRaises(WorkPlanError):
                    WorkPlan(root)
                self.assertEqual(path.read_text(), raw)


if __name__ == "__main__":
    unittest.main()
