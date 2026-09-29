import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from community.background import BackgroundContributor, WAIT_SECONDS, main, single_instance
from community.contribute import ContributeError
from community.desktop import DesktopApp, DesktopError


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

    def worker(self, root):
        app = Mock()
        app.client = None
        app.assets = {"binary": Path(root) / "runtime/bin/mma-vision.exe",
                      "model_dir": Path(root) / "runtime/models"}
        app.connect.return_value = {"recoveryCode": "private-test-code"}
        app.indexer.return_value = {"batches": 1, "accepted": 16}
        app.require_qualification.side_effect = None
        worker = BackgroundContributor(root, app_factory=lambda *a, **kw: app)
        return worker, app

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
            self.assertEqual(app2.indexer.call_args.kwargs["work_dir"], Path(root) / "indexes")
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
