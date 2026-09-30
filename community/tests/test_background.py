import json
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from community.background import BackgroundContributor, ProcessingSchedule, WAIT_SECONDS, main, single_instance
from community.contribute import ContributeError
from community.desktop import DesktopApp, DesktopError
from community.vision_index import VisionIndexError


class BackgroundTest(unittest.TestCase):
    def test_transient_service_failures_retry_without_attention_marker(self):
        for status in (429, 502, 503, 504):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as root:
                worker, app = self.worker(root)
                app.capabilities.side_effect = ContributeError("http_error", status)
                worker.run(once=True)
                self.assertFalse((Path(root) / "NEEDS-ATTENTION").exists())
                app.capabilities.side_effect = None
                worker.run(once=True)
                app.indexer.assert_not_called()
                worker.wall_clock.return_value += WAIT_SECONDS
                worker.run(once=True)
                app.indexer.assert_called_once()

    def test_rejection_is_not_retried_even_with_transient_http_status(self):
        with tempfile.TemporaryDirectory() as root:
            worker, app = self.worker(root)
            app.capabilities.side_effect = ContributeError("verification_failed", 503)
            worker.run(once=True)
            worker.run(once=True)
            app.capabilities.assert_called_once()
            self.assertTrue((Path(root) / "NEEDS-ATTENTION").exists())

    def test_permission_error_during_work_is_not_hidden_as_duplicate_instance(self):
        with tempfile.TemporaryDirectory() as root:
            worker = Mock(root=Path(root))
            worker.run.side_effect = PermissionError("Cannot save failure report")
            with patch("sys.argv", ["background", "--root", root, "--accept-contributions"]), \
                    patch("community.background.BackgroundContributor", return_value=worker):
                with self.assertRaises(PermissionError):
                    main()

    def test_failure_report_retains_known_reason_without_raw_private_text(self):
        with tempfile.TemporaryDirectory() as root:
            app = DesktopApp(Path(root))
            app.record_failure(DesktopError("scene_verification_unavailable"))
            report = Path(root) / "desktop-failure.json"
            self.assertEqual(json.loads(report.read_text())["code"], "scene_verification_unavailable")
            app.record_failure(DesktopError("private credential example"))
            self.assertNotIn("private credential example", report.read_text())

    def worker(self, root, **settings):
        app = Mock()
        app.client = None
        app.assets = {"binary": Path(root) / "runtime/bin/mma-vision.exe",
                      "model_dir": Path(root) / "runtime/models"}
        app.connect.return_value = {"recoveryCode": "private-test-code"}
        def connect(*args, **kwargs):
            app.client = Mock()
            return {"recoveryCode": "private-test-code"}
        app.connect.side_effect = connect
        app.indexer.return_value = {"batches": 1, "accepted": 16}
        app.resume_submissions.return_value = {"accepted": 0, "unitsEarned": 0}
        app.require_qualification.side_effect = None
        settings.setdefault("schedule", ProcessingSchedule(day_pace="max", night_pace="max"))
        settings.setdefault("wall_clock", Mock(return_value=10000))
        worker = BackgroundContributor(root, app_factory=lambda *a, **kw: app, **settings)
        return worker, app

    def test_local_schedule_boundaries_midnight_and_custom_day_crossing_midnight(self):
        schedule = ProcessingSchedule()
        for hour, minute, expected in ((0, 0, "max"), (7, 59, "max"), (8, 0, "medium"),
                                       (21, 59, "medium"), (22, 0, "max"), (23, 59, "max")):
            self.assertEqual(schedule.pace_at(datetime(2026, 9, 30, hour, minute)), expected)
        reversed_schedule = ProcessingSchedule(day_start="20:00", night_start="06:00")
        self.assertEqual(reversed_schedule.pace_at(datetime(2026, 9, 30, 23)), "medium")
        self.assertEqual(reversed_schedule.pace_at(datetime(2026, 10, 1, 5)), "medium")
        self.assertEqual(reversed_schedule.pace_at(datetime(2026, 10, 1, 6)), "max")

    def test_schedule_rejects_invalid_times_before_setup(self):
        for bad in ("24:00", "08:60", "8:00", "aa:00", "-1:00", "+1:00", " 1:00", "０８:00"):
            with self.subTest(time=bad), self.assertRaises(ValueError):
                ProcessingSchedule(day_start=bad)
        with self.assertRaises(ValueError):
            ProcessingSchedule(day_start="08:00", night_start="08:00")

    def test_pacing_rests_without_changing_qualified_native_input(self):
        for pace, expected in (("medium", 60), ("slow", 180), ("max", 1)):
            with self.subTest(pace=pace), tempfile.TemporaryDirectory() as root:
                worker, app = self.worker(root, schedule=ProcessingSchedule(day_pace=pace),
                                          clock=lambda: datetime(2026, 9, 30, 12),
                                          elapsed_clock=Mock(side_effect=[100, 160]))
                self.assertEqual(worker.step(), expected)
                self.assertEqual(app.indexer.call_args.kwargs["pace"], "slow")
                self.assertEqual(app.indexer.call_args.kwargs["count"], 16)
                state = json.loads((Path(root) / "background-status.json").read_text())
                self.assertEqual(state["pace"], pace)
                self.assertEqual(state["schedule"]["clock"], "computer-local")
                self.assertEqual(worker.paced_wait, pace != "max")

    def test_scheduled_pause_does_not_download_connect_qualify_or_lease(self):
        with tempfile.TemporaryDirectory() as root:
            worker, app = self.worker(root, schedule=ProcessingSchedule(day_pace="pause"),
                                      clock=lambda: datetime(2026, 9, 30, 12))
            self.assertEqual(worker.step(), 60)
            self.assertEqual(app.mock_calls, [])
            self.assertEqual(json.loads((Path(root) / "background-status.json").read_text())["state"],
                             "waiting_for_schedule")

    def test_period_change_during_batch_takes_effect_when_batch_finishes(self):
        with tempfile.TemporaryDirectory() as root:
            clock = Mock(return_value=datetime(2026, 9, 30, 21, 59))
            worker, app = self.worker(root, schedule=ProcessingSchedule(day_pace="medium", night_pace="pause"),
                                      clock=clock, elapsed_clock=Mock(side_effect=[100, 160]))
            def finish_batch(**kwargs):
                clock.return_value = datetime(2026, 9, 30, 22, 1)
                return {"batches": 1, "accepted": 16}
            app.indexer.side_effect = finish_batch
            self.assertEqual(worker.step(), 60)
            self.assertEqual(worker.completed, 16)
            self.assertFalse(worker.paced_wait)
            self.assertEqual(worker.last_state, "waiting_for_schedule")

    def test_native_failure_backoff_survives_restart_and_success_resets_it(self):
        with tempfile.TemporaryDirectory() as root:
            first, app = self.worker(root, retry_minutes=1)
            app.indexer.side_effect = VisionIndexError("vision_binary_timeout")
            first.run(once=True)
            self.assertFalse((Path(root) / "NEEDS-ATTENTION").exists())
            record = json.loads((Path(root) / "background-retry.json").read_text())
            self.assertEqual(record["nextAttemptAt"], 10060)
            second, app2 = self.worker(root, retry_minutes=1)
            second.run(once=True)
            app2.indexer.assert_not_called()
            app2.capabilities.assert_not_called()
            second.wall_clock.return_value = 10060
            app2.indexer.side_effect = VisionIndexError("vision_binary_failed")
            second.run(once=True)
            record = json.loads((Path(root) / "background-retry.json").read_text())
            self.assertEqual(record["attempts"], 2)
            self.assertEqual(record["nextAttemptAt"], 10180)
            second.wall_clock.return_value = 10180
            app2.indexer.side_effect = None
            second.run(once=True)
            self.assertFalse((Path(root) / "background-retry.json").exists())
            self.assertEqual(second.completed, 16)
            app2.connect.assert_called_once_with("private-test-code")

    def test_wrapped_lease_http_failures_and_lease_expiration_retry(self):
        for code, status in (("http_error", 503), ("expired_lease", 409), ("lease_lost", 409)):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as root:
                worker, app = self.worker(root)
                app.indexer.side_effect = VisionIndexError(code, status)
                worker.run(once=True)
                self.assertFalse((Path(root) / "NEEDS-ATTENTION").exists())
                self.assertEqual(worker.last_state, "waiting_for_service")

    def test_bad_data_and_rejected_submissions_never_auto_retry(self):
        for code in ("checkpoint_configuration_mismatch", "invalid_embedding", "incomplete_view_mask",
                     "unverified_checkpoint", "scene_submission_rejected", "scene_qualification_changed"):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as root:
                worker, app = self.worker(root)
                app.indexer.side_effect = VisionIndexError(code, 503 if code.startswith("scene_") else 0)
                worker.run(once=True)
                worker.wall_clock.return_value += 86400
                worker.run(once=True)
                app.indexer.assert_called_once()
                self.assertTrue((Path(root) / "NEEDS-ATTENTION").exists())

    def test_cooldown_is_capped_and_corrupt_retry_state_is_preserved(self):
        with tempfile.TemporaryDirectory() as root:
            worker, app = self.worker(root)
            for _ in range(20):
                self.assertLessEqual(worker.retry_later("indexing"), 6 * 60 * 60)
            path = Path(root) / "background-retry.json"
            path.write_text("broken")
            worker.run(once=True)
            self.assertTrue((Path(root) / "NEEDS-ATTENTION").exists())
            self.assertEqual(path.read_text(), "broken")
            app.capabilities.assert_not_called()

    def test_stop_request_during_batch_exits_after_saving_batch(self):
        with tempfile.TemporaryDirectory() as root:
            worker, app = self.worker(root)
            def finish(**kwargs):
                (Path(root) / "STOP-AFTER-BATCH").touch()
                return {"batches": 1, "accepted": 16}
            app.indexer.side_effect = finish
            worker.run()
            app.indexer.assert_called_once()
            self.assertEqual(worker.completed, 16)
            self.assertEqual(worker.last_state, "stopped")
            self.assertTrue((Path(root) / "STOP-AFTER-BATCH").exists())

    def test_wait_rechecks_schedule_and_releases_sleep_inhibition(self):
        with tempfile.TemporaryDirectory() as root:
            clock = Mock(return_value=datetime(2026, 9, 30, 21, 59))
            worker, _ = self.worker(root, clock=clock, schedule=ProcessingSchedule(),
                                    elapsed_clock=Mock(return_value=100))
            worker.paced_wait = True
            stop = Mock()
            stop.is_set.return_value = False
            def advance(seconds):
                self.assertLessEqual(seconds, 5)
                clock.return_value = datetime(2026, 9, 30, 22)
                return False
            stop.wait.side_effect = advance
            with patch("community.background.keep_awake") as awake:
                worker.wait(600, stop)
                awake.assert_called_once_with(True)
                awake.return_value.__exit__.assert_called_once()
            worker.prevent_sleep = False
            stop.is_set.return_value = True
            with patch("community.background.keep_awake") as awake:
                worker.wait(600, stop)
                awake.assert_called_once_with(False)

    def test_unavailable_service_does_not_create_account_download_or_index(self):
        with tempfile.TemporaryDirectory() as root:
            worker, app = self.worker(root)
            app.capabilities.side_effect = DesktopError("scene_verification_unavailable")
            worker.run(once=True)
            app.prepare.assert_not_called()
            app.connect.assert_not_called()
            app.indexer.assert_not_called()
            state = json.loads((Path(root) / "background-status.json").read_text())
            self.assertEqual(state["state"], "waiting_for_service")
            self.assertFalse((Path(root) / "NEEDS-ATTENTION").exists())

    def test_restarts_recover_existing_account_without_creating_another(self):
        with tempfile.TemporaryDirectory() as root:
            first, app = self.worker(root)
            self.assertEqual(first.step(), 1)
            second, app2 = self.worker(root)
            second.step()
            app2.connect.assert_called_once_with("private-test-code")
            self.assertEqual(
                Path(app2.indexer.call_args.kwargs["work_dir"]).resolve(),
                (Path(root) / "indexes").resolve(),
            )
            self.assertNotIn("private-test-code", (Path(root) / "background-status.json").read_text())

    def test_pause_and_low_disk_do_not_claim_work(self):
        with tempfile.TemporaryDirectory() as root:
            worker, app = self.worker(root)
            marker = Path(root) / "PAUSE"
            marker.touch()
            self.assertEqual(worker.step(), WAIT_SECONDS)
            marker.unlink()
            with patch("community.background.shutil.disk_usage", return_value=Mock(free=1)):
                self.assertEqual(worker.step(), WAIT_SECONDS)
            app.capabilities.assert_not_called()
            app.indexer.assert_not_called()

    def test_rejected_check_is_preserved_and_not_repeated(self):
        with tempfile.TemporaryDirectory() as root:
            worker, app = self.worker(root)
            app.require_qualification.side_effect = DesktopError("pc_check_required")
            app.qualify.side_effect = DesktopError("scene_qualification_rejected")
            worker.run(once=True)
            worker.run(once=True)
            app.qualify.assert_called_once()
            app.record_failure.assert_called_once()
            app.indexer.assert_not_called()
            self.assertTrue((Path(root) / "NEEDS-ATTENTION").exists())

    def test_empty_queue_waits_without_busy_loop(self):
        with tempfile.TemporaryDirectory() as root:
            worker, app = self.worker(root)
            app.indexer.return_value = {"batches": 0, "accepted": 0}
            self.assertEqual(worker.step(), WAIT_SECONDS)

    def test_audit_backlog_waits_without_expensive_rechecks_or_attention_marker(self):
        with tempfile.TemporaryDirectory() as root:
            worker, app = self.worker(root)
            app.indexer.side_effect = ContributeError("scene_audit_backlog", 503)
            worker.run(once=True)
            self.assertFalse((Path(root) / "NEEDS-ATTENTION").exists())
            state = json.loads((Path(root) / "background-status.json").read_text())
            self.assertEqual(state["state"], "waiting_for_verification")
            app.resume_submissions.assert_called_once()

    def test_corrupt_saved_account_does_not_create_replacement(self):
        with tempfile.TemporaryDirectory() as root:
            worker, app = self.worker(root)
            (Path(root) / "account.json").write_text("broken")
            worker.run(once=True)
            app.connect.assert_not_called()
            app.indexer.assert_not_called()
            self.assertTrue((Path(root) / "NEEDS-ATTENTION").exists())

    def test_two_workers_cannot_own_the_same_root(self):
        with tempfile.TemporaryDirectory() as root:
            with single_instance(Path(root)):
                with self.assertRaises((BlockingIOError, PermissionError, OSError)):
                    with single_instance(Path(root)):
                        self.fail("Second worker acquired the lock")


if __name__ == "__main__":
    unittest.main()
