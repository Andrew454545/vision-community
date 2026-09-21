import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from community.contribute import contribute
from community.local_search import local_search
from community.server import handler_for
from community.service import CommunityService


PROTOTYPE = Path(__file__).resolve().parents[1] / "prototype_catalog.json"
QUERY = Path(__file__).resolve().parents[1] / "web" / "prototype-query.json"


class LocalSearchTest(unittest.TestCase):
    def test_search_runs_on_this_computer_and_tags_country(self):
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
                indexed = contribute(
                    url=url,
                    lane="scene",
                    pace="slow",
                    count=4,
                    batches=1,
                )
                output = root / "result.json"
                report = local_search(
                    url=url,
                    query_map=json.loads(QUERY.read_text(encoding="utf-8")),
                    lane="scene",
                    recovery_code=indexed["recoveryCode"],
                    persist_session=False,
                    output=output,
                )
            finally:
                server.shutdown()
                server.server_close()
            self.assertTrue(report["ok"])
            self.assertTrue(report["local"])
            self.assertGreaterEqual(report["scanned"], 4)
            self.assertGreaterEqual(report["results"], 1)
            document = json.loads(output.read_text(encoding="utf-8"))
            first = document["customCoordinates"][0]
            self.assertEqual(len(first["extra"]["tags"]), 1)
            self.assertTrue(first["extra"]["tags"][0])
            self.assertIn(first["extra"]["tags"][0], {"USA", "Italy", "Japan", "South Africa"})


if __name__ == "__main__":
    unittest.main()
