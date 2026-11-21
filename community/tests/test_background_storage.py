"""Storage-pressure recovery using disposable files and synthetic submissions."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import stat
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from community.background import BackgroundContributor, ProcessingSchedule, measure_storage
from community.contribute import CommunityClient, save_session
from community.desktop import DesktopApp, DesktopClient, DesktopError
from community.work_plan import WorkPlan


class StorageTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        free = patch("community.background.shutil.disk_usage", return_value=Mock(free=10 * 1024**3))
        free.start()
        self.addCleanup(free.stop)

    def worker(self, *, allowance=4096, **settings):
        app = Mock()
        app.work_plan = WorkPlan(self.root)
        app.client = None
        app.assets = {}
        app.resume_submissions.return_value = {"accepted": 0}
        app.indexer.return_value = {"accepted": 16, "batches": 1}
        app.run_batch.side_effect = lambda: app.indexer(url=worker.url, pace="slow", batches=1,
            count=16, client=app.client, persist_session=False, work_dir=worker.root / "indexes",
            **app.assets, use_nice=False)
        def connect(*args, **kwargs):
            app.client = Mock()
            return {"recoveryCode": "private-code-do-not-share"}
        app.connect.side_effect = connect
        worker = BackgroundContributor(self.root, app_factory=lambda *args, **kwargs: app,
            schedule=ProcessingSchedule(day_pace="max", night_pace="max"), storage_limit_gb=1,
            **settings)
        # A small byte allowance exercises the real boundary without allocating
        # gigabytes in a unit test. Public configuration still accepts whole GB.
        worker.storage_limit_bytes = allowance
        worker.storage["limitBytes"] = allowance
        return worker, app

    def fill(self):
        target = self.root / "indexes/saved-batch.bin"
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(b"retained-output" * 600)
        return target

    def test_measurement_counts_all_private_folders_without_reading_contents(self):
        for name, body in (("account.json", b"private account"), ("indexes/out.bin", b"saved output"),
                           ("launchers/old.py", b"preserved launcher"), ("runtime/model.bin", b"model")):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
        with patch.object(Path, "open", side_effect=AssertionError("Must not read private file contents")):
            result = measure_storage(self.root)
        self.assertEqual(result["usedBytes"], 50)
        self.assertEqual(result["files"], 4)
        self.assertNotIn("private account", json.dumps(result))

    def test_allowance_blocks_new_account_download_pc_check_and_lease(self):
        worker, app = self.worker()
        output = self.fill()
        original = output.read_bytes()
        self.assertEqual(worker.step(), worker.retry_seconds)
        self.assertEqual(worker.last_state, "waiting_for_space")
        self.assertEqual(app.mock_calls, [])
        self.assertFalse(worker.session.exists())
        self.assertEqual(output.read_bytes(), original)
        status = json.loads((self.root / "background-status.json").read_text())
        self.assertGreaterEqual(status["localStorage"]["usedBytes"], status["localStorage"]["limitBytes"])
        self.assertFalse(status["localStorage"]["hardQuota"])

    def test_restart_restores_same_account_and_recovers_delivery_under_pressure(self):
        worker, _ = self.worker()
        save_session(worker.session, url=worker.url, account_id=None, recovery_code="private-code-do-not-share")
        original = worker.session.read_bytes()
        output = self.fill()
        restarted, app = self.worker()
        app.resume_submissions.return_value = {"accepted": 3}
        restarted.step()
        app.connect.assert_called_once_with("private-code-do-not-share")
        app.resume_submissions.assert_called_once()
        app.prepare.assert_not_called()
        app.qualify.assert_not_called()
        app.indexer.assert_not_called()
        self.assertEqual(restarted.completed, 3)
        self.assertEqual(restarted.session.read_bytes(), original)
        self.assertTrue(output.exists())
        self.assertNotIn("private-code-do-not-share", (self.root / "background-status.json").read_text())

    def test_increasing_allowance_resumes_without_deleting_saved_files(self):
        first, _ = self.worker()
        output = self.fill()
        first.step()
        restarted, app = self.worker(allowance=32768)
        restarted.step()
        app.indexer.assert_called_once()
        self.assertTrue(output.exists())
        self.assertEqual(restarted.completed, 16)

    def test_runtime_download_growth_is_rechecked_before_creating_account(self):
        worker, app = self.worker()
        app.prepare.side_effect = self.fill
        worker.step()
        app.prepare.assert_called_once()
        app.connect.assert_not_called()
        app.qualify.assert_not_called()
        app.indexer.assert_not_called()
        self.assertEqual(worker.last_state, "waiting_for_space")

    def test_pc_check_growth_stops_before_claiming_new_batch(self):
        worker, app = self.worker()
        app.require_qualification.side_effect = DesktopError("pc_check_required")
        app.qualify.side_effect = self.fill
        worker.step()
        app.qualify.assert_called_once()
        app.indexer.assert_not_called()
        self.assertEqual(worker.last_state, "waiting_for_space")
        self.assertFalse(worker.paced_wait)

    def test_completed_batch_is_saved_before_next_batch_is_paused(self):
        worker, app = self.worker()
        def finish(**kwargs):
            self.fill()
            return {"batches": 1, "accepted": 16}
        app.indexer.side_effect = finish
        worker.step()
        worker.step()
        app.indexer.assert_called_once()
        self.assertEqual(worker.completed, 16)
        self.assertEqual(worker.last_state, "waiting_for_space")

    def test_unlimited_folder_setting_keeps_free_disk_guard_without_scanning(self):
        worker, app = self.worker(allowance=0)
        with patch("community.background.measure_storage") as scan, \
                patch("community.background.shutil.disk_usage", return_value=Mock(free=1024)):
            worker.step()
        scan.assert_not_called()
        app.indexer.assert_not_called()
        self.assertEqual(worker.last_state, "waiting_for_space")

    def test_scan_error_preserves_evidence_and_stops_instead_of_using_stale_usage(self):
        worker = BackgroundContributor(self.root, storage_limit_gb=1)
        worker.storage["usedBytes"] = 10
        with patch("community.background.os.scandir", side_effect=PermissionError("PRIVATE PATH")):
            worker.run(once=True)
        self.assertEqual(worker.last_state, "needs_attention")
        status = (self.root / "background-status.json").read_text()
        self.assertIsNone(json.loads(status)["localStorage"]["usedBytes"])
        self.assertNotIn("PRIVATE PATH", status)
        report = (self.root / "desktop-failure.json").read_text()
        self.assertEqual(json.loads(report)["code"], "storage_check_failed")
        self.assertNotIn("PRIVATE PATH", report)

    def test_links_entry_limit_and_scan_deadline_do_not_create_false_totals(self):
        (self.root / "file").write_bytes(b"retained")
        fake = Mock(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
        with patch.object(Path, "lstat", return_value=fake), self.assertRaisesRegex(DesktopError, "storage_check_failed"):
            measure_storage(self.root)
        with patch("community.background.MAX_STORAGE_ENTRIES", 0), self.assertRaises(DesktopError):
            measure_storage(self.root)
        with patch("community.background.time.monotonic", side_effect=[0, 11]), self.assertRaises(DesktopError):
            measure_storage(self.root)

    def test_invalid_allowance_fails_before_creating_private_folder(self):
        for value in (-1, 4097, True, 1.5, "20"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                BackgroundContributor(self.root / "never-created", storage_limit_gb=value)
        self.assertFalse((self.root / "never-created").exists())

    def test_actual_http_and_sqlite_saved_delivery_recovers_while_new_work_is_paused(self):
        calls = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass
            def send(self, value):
                body = json.dumps(value).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def do_GET(self):
                calls.append(("GET", self.path, None))
                self.send({"version": 1, "sceneContributions": {"model": "vision-four-view-v4", "ready": True,
                    "deviceQualificationRequired": True, "canaryLocations": 112}})
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                calls.append(("POST", self.path, body))
                self.send({"accepted": 0, "unitsEarned": 0, "pendingAudit": True} if self.path == "/api/submissions"
                          else {"accepted": 1, "unitsEarned": 1, "pendingAudit": False})
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = "http://127.0.0.1:" + str(server.server_port)
            lease, account = "b" * 32, "a" * 32
            old_client = DesktopClient(url)
            old_client.enable_outbox(self.root / "indexes", account)
            outputs = [{"locationId": 1, "embedding": "synthetic saved output"}]
            old_client.outbox.remember(lease, outputs)
            # A different app/client reopens the real durable journal after restart.
            app = DesktopApp(self.root, url=url)
            app.client = DesktopClient(url)
            app.client.enable_outbox(self.root / "indexes", account)
            worker = BackgroundContributor(self.root, url=url, app_factory=lambda *args, **kwargs: app,
                storage_limit_gb=1, schedule=ProcessingSchedule(day_pace="max", night_pace="max"))
            worker.storage_limit_bytes = 4096
            worker.storage["limitBytes"] = 4096
            output = self.fill()
            with patch.object(app, "prepare") as prepare, patch.object(app, "indexer") as indexer:
                worker.step()
            prepare.assert_not_called()
            indexer.assert_not_called()
            self.assertEqual(worker.last_state, "waiting_for_space")
            self.assertEqual(worker.completed, 1)
            self.assertEqual(app.client.outbox.count(), 0)
            self.assertEqual([p for m, p, _b in calls if m == "POST"], ["/api/submissions", "/api/scene-audits"])
            self.assertEqual(calls[1][2]["outputs"], outputs)
            self.assertTrue(output.exists())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
