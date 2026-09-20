import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from community.contribute import DEFAULT_URL, contribute
from community.server import handler_for
from community.service import CommunityService


PROTOTYPE = Path(__file__).resolve().parents[1] / "prototype_catalog.json"


class ContributeCliTest(unittest.TestCase):
    def test_local_cli_processes_one_scene_batch(self):
        with tempfile.TemporaryDirectory() as folder:
            service = CommunityService(
                Path(folder) / "db.sqlite",
                search_cost=4,
                artifacts=Path(folder) / "artifacts",
                segment_capacity=50,
            )
            service.import_jobs(json.loads(PROTOTYPE.read_text(encoding="utf-8")))
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(service))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host, port = server.server_address
                report = contribute(
                    url=f"http://{host}:{port}",
                    lane="scene",
                    pace="slow",
                    count=4,
                    batches=1,
                )
            finally:
                server.shutdown()
                server.server_close()
            self.assertTrue(report["ok"])
            self.assertEqual(report["batches"], 1)
            self.assertEqual(report["accepted"], 4)
            self.assertEqual(report["unitsEarned"], 4)
            self.assertTrue(report["recoveryCode"])

    def test_cli_does_not_fetch_views_through_the_site(self):
        with tempfile.TemporaryDirectory() as folder:
            service = CommunityService(
                Path(folder) / "db.sqlite",
                search_cost=4,
                artifacts=Path(folder) / "artifacts",
                segment_capacity=50,
            )
            service.import_jobs(json.loads(PROTOTYPE.read_text(encoding="utf-8")))
            inner = handler_for(service)
            views = {"n": 0}

            class Counting(inner):
                def do_GET(self):
                    if self.path.startswith("/api/views"):
                        views["n"] += 1
                    return super().do_GET()

            server = ThreadingHTTPServer(("127.0.0.1", 0), Counting)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host, port = server.server_address
                report = contribute(
                    url=f"http://{host}:{port}",
                    lane="scene",
                    pace="slow",
                    count=4,
                    batches=1,
                )
            finally:
                server.shutdown()
                server.server_close()
            self.assertEqual(report["accepted"], 4)
            self.assertEqual(views["n"], 0)

    def test_cli_saves_and_reuses_recovery_session(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = CommunityService(
                root / "db.sqlite",
                search_cost=4,
                artifacts=root / "artifacts",
                segment_capacity=50,
            )
            service.import_jobs(json.loads(PROTOTYPE.read_text(encoding="utf-8")))
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(service))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host, port = server.server_address
                url = f"http://{host}:{port}"
                session_path = root / "session.json"
                first = contribute(
                    url=url,
                    lane="scene",
                    pace="slow",
                    count=4,
                    batches=1,
                    session_path=session_path,
                    persist_session=True,
                )
                self.assertTrue(session_path.is_file())
                stored = json.loads(session_path.read_text(encoding="utf-8"))
                self.assertEqual(stored["recoveryCode"], first["recoveryCode"])
                second = contribute(
                    url=url,
                    lane="scene",
                    pace="slow",
                    count=4,
                    batches=1,
                    session_path=session_path,
                    persist_session=True,
                )
            finally:
                server.shutdown()
                server.server_close()
            self.assertNotIn("recoveryCode", second)
            self.assertEqual(second["units"], 8)
            self.assertEqual(second["unitsRemainingToSearch"], 0)
            self.assertEqual(second["searchesAvailable"], 2)

    def test_cli_defaults_to_the_hosted_worker(self):
        self.assertEqual(DEFAULT_URL, "https://vision-community.visioncommunity.workers.dev")


if __name__ == "__main__":
    unittest.main()
