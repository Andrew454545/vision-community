import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from community.contribute import contribute
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


if __name__ == "__main__":
    unittest.main()
