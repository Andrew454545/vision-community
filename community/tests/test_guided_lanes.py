import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from community.desktop import DesktopApp, DesktopClient, DesktopError
from community.background import BackgroundContributor, ProcessingSchedule


class GuidedLanesTests(unittest.TestCase):
    def app(self, root, *, scene=None, objects=None):
        app = DesktopApp(Path(root), indexer=scene or Mock(return_value={"batches": 1}),
                         object_indexer=objects or Mock(return_value={"batches": 1}),
                         profile_matches=lambda *args, **kwargs: True,
                         object_profile_matches=lambda *args, **kwargs: True,
                         object_canary=lambda *args, **kwargs: {})
        app.client = SimpleNamespace(profile_id=None, object_profile_id=None, pending=0, undelivered=0)
        app.canary_report = {"runtimeProfile": {"sha256": "a" * 64}}
        app.object_canary_report = {"runtimeProfile": {"sha256": "b" * 64}}
        app.update(ready=True, savedCode=True)
        return app

    def approve(self, app, lane):
        profile = ("a" if lane == "scene" else "b") * 64
        result = {"qualified": True, "lane": lane, "profileId": profile, "expiresAt": time.time() + 3600}
        return app.set_qualification(result) if lane == "scene" else app.set_object_qualification(result)

    def test_scene_approval_does_not_approve_objects_or_both(self):
        with tempfile.TemporaryDirectory() as root:
            app = self.app(root)
            app.work_plan.select("both")
            self.assertTrue(self.approve(app, "scene"))
            self.assertFalse(app.snapshot()["qualified"])
            with self.assertRaisesRegex(DesktopError, "object_pc_check_required"):
                app.run_batch()
            app.indexer.assert_not_called()
            app.object_indexer.assert_not_called()
            self.assertTrue(self.approve(app, "object"))
            self.assertTrue(app.snapshot()["qualified"])

    def test_both_serializes_different_assets_and_recovers_the_interrupted_lane_before_rotating(self):
        with tempfile.TemporaryDirectory() as root:
            app = self.app(root)
            app.work_plan.select("both")
            self.approve(app, "scene"); self.approve(app, "object")
            app.run_batch()
            self.assertEqual(app.indexer.call_args.kwargs["count"], 16)
            self.assertEqual(app.work_plan.next_lane, "object")
            app.object_indexer.side_effect = DesktopError("indexer_timeout")
            with self.assertRaises(DesktopError):
                app.run_batch()
            recovered = self.app(root)
            self.approve(recovered, "scene"); self.approve(recovered, "object")
            recovered.run_batch()
            recovered.indexer.assert_not_called()
            self.assertEqual(recovered.object_indexer.call_args.kwargs["count"], 1)
            self.assertEqual(recovered.object_indexer.call_args.kwargs["work_dir"], Path(root).resolve() / "object-indexes")
            self.assertEqual(recovered.object_indexer.call_args.kwargs["model_dir"], recovered.object_assets["model_dir"])
            self.assertEqual(recovered.work_plan.next_lane, "scene")

    def test_concurrent_batch_cannot_open_another_native_writer(self):
        with tempfile.TemporaryDirectory() as root:
            entered, finish = threading.Event(), threading.Event()
            def native(**kwargs):
                entered.set(); finish.wait(5)
                return {"batches": 1}
            app = self.app(root, scene=native)
            self.approve(app, "scene")
            thread = threading.Thread(target=app.run_batch)
            thread.start()
            try:
                self.assertTrue(entered.wait(5))
                with self.assertRaisesRegex(DesktopError, "busy"):
                    app.run_batch()
            finally:
                finish.set(); thread.join(5)
            self.assertFalse(thread.is_alive())

    def test_unavailable_object_service_does_not_create_account_or_borrow_scene_capabilities(self):
        with tempfile.TemporaryDirectory() as root:
            app = self.app(root)
            app.work_plan.select("object")
            client = Mock()
            client.request.return_value = (200, {"version": 1, "sceneContributions": {
                "model": "vision-four-view-v4", "ready": True, "deviceQualificationRequired": True,
                "canaryLocations": 112}}, None)
            app.client_factory = lambda *args: client
            with self.assertRaisesRegex(DesktopError, "object_verification_unavailable"):
                app.connect(create=True)
            client.create_account.assert_not_called()

    def test_object_setup_refuses_missing_released_provider_before_large_downloads(self):
        with tempfile.TemporaryDirectory() as root:
            client = Mock()
            client.request.return_value = (200, {"version":1,"objectContributions":{
                "model":"vision-object-index-v4","ready":True,"deviceQualificationRequired":True,
                "officialGen4Required":True}}, None)
            app = DesktopApp(Path(root),client_factory=lambda *args: client)
            app.select_work("object")
            with patch("community.desktop.runtime_platform",return_value="windows-x86_64"), \
                    patch("community.desktop.install_runtime") as install:
                with self.assertRaisesRegex(DesktopError,"object_verification_unavailable"):
                    app.prepare()
                install.assert_not_called()
            client.create_account.assert_not_called()

    def test_choice_change_is_refused_while_setup_or_processing_runs_and_other_files_are_kept(self):
        with tempfile.TemporaryDirectory() as root:
            app = self.app(root)
            app.operation.acquire()
            try:
                with self.assertRaisesRegex(DesktopError, "busy"):
                    app.select_work("both")
            finally:
                app.operation.release()
            app.select_work("object")
            self.assertEqual(app.snapshot()["workType"], "object")
            self.assertFalse(app.snapshot()["ready"])
            self.assertIsNotNone(app.client)

    def test_expired_or_nonfinite_approval_cannot_start_either_lane(self):
        with tempfile.TemporaryDirectory() as root:
            app = self.app(root)
            app.work_plan.select("both")
            for expiry in (time.time() - 1, float("inf"), float("nan"), True):
                for lane in ("scene", "object"):
                    self.approve(app, "scene"); self.approve(app, "object")
                    value = {"qualified": True, "lane": lane, "profileId": ("a" if lane == "scene" else "b") * 64,
                             "expiresAt": expiry}
                    setter = app.set_qualification if lane == "scene" else app.set_object_qualification
                    self.assertFalse(setter(value))
                    with self.assertRaises(DesktopError): app.run_batch()
            app.indexer.assert_not_called()
            app.object_indexer.assert_not_called()

    def test_each_lease_uses_only_its_own_approved_profile(self):
        client = DesktopClient("https://community.test")
        client.profile_id = "a" * 64
        with patch("community.delivery.DurableCommunityClient.request", return_value=(200, {}, None)) as send:
            with self.assertRaisesRegex(DesktopError, "object_pc_check_required"):
                client.request("POST", "/api/leases", {"lane": "object", "profileId": "a" * 64})
            send.assert_not_called()
            client.object_profile_id = "b" * 64
            client.request("POST", "/api/leases", {"lane": "object"})
            self.assertEqual(send.call_args.args[2]["profileId"], "b" * 64)
            client.request("POST", "/api/leases", {"lane": "scene"})
            self.assertEqual(send.call_args.args[2]["profileId"], "a" * 64)

    def test_background_both_checks_other_queue_promptly_and_waits_after_both_are_empty(self):
        with tempfile.TemporaryDirectory() as root:
            app = self.app(root, scene=Mock(return_value={"batches": 0}), objects=Mock(return_value={"batches": 0}))
            app.work_plan.select("both")
            self.approve(app, "scene"); self.approve(app, "object")
            app.resume_submissions = lambda: {"accepted": 0}
            app.capabilities = lambda *args: None
            worker = BackgroundContributor(root, app_factory=lambda *args, **kwargs: app,
                prevent_sleep=False, schedule=ProcessingSchedule(day_pace="max", night_pace="max"))
            worker.prepared = True
            with patch.object(worker, "space_available", return_value=True):
                self.assertEqual(worker.step(), 1)
                self.assertEqual(app.work_plan.next_lane, "object")
                self.assertEqual(worker.step(), worker.retry_seconds)
                self.assertEqual(worker.last_state, "waiting_for_work")
                self.assertEqual(app.work_plan.next_lane, "scene")
            app.indexer.assert_called_once()
            app.object_indexer.assert_called_once()


if __name__ == "__main__":
    unittest.main()
