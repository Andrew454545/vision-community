import json
import sqlite3
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from community.server import handler_for
from community.service import CommunityService, ServiceError
from community.worker import ProcessingWorker


ROOT = Path(__file__).resolve().parents[1]
PROTOTYPE = ROOT / "prototype_catalog.json"
QUERY = ROOT / "web" / "prototype-query.json"


class SearchContributionGateTest(unittest.TestCase):
    def test_index_and_snapshot_require_a_paid_search(self):
        with tempfile.TemporaryDirectory() as folder:
            service = CommunityService(
                Path(folder) / "db.sqlite",
                search_cost=4,
                artifacts=Path(folder) / "artifacts",
                segment_capacity=50,
            )
            service.import_jobs(json.loads(PROTOTYPE.read_text(encoding="utf-8")))
            unpaid = service.create_account()["accountId"]
            query = json.loads(QUERY.read_text(encoding="utf-8"))
            with self.assertRaisesRegex(ServiceError, "insufficient_credit"):
                service.search(unpaid, None, "unpaid-search-001", query_map=query, execute="local")
            with self.assertRaisesRegex(ServiceError, "unknown_search"):
                service.published_snapshot(unpaid, search_id="missing")
            with self.assertRaisesRegex(ServiceError, "unknown_search"):
                service.index_manifest(unpaid, search_id="missing")

            paid = service.create_account()["accountId"]
            lease = service.lease(paid, "scene", 4)
            service.submit(paid, lease["leaseId"], ProcessingWorker().process_lease(lease))
            authorized = service.search(paid, None, "paid-search-001", query_map=query, execute="local")
            snapshot = service.published_snapshot(paid, search_id=authorized["searchId"])
            self.assertGreaterEqual(len(snapshot["locations"]), 4)
            self.assertTrue(snapshot["locations"][0]["embedding"])
            with self.assertRaisesRegex(ServiceError, "unknown_search"):
                service.published_snapshot(unpaid, search_id=authorized["searchId"])
            with sqlite3.connect(service.database) as connection:
                connection.execute("DELETE FROM ledger WHERE reference=?", (f"search:{authorized['searchId']}",))
            with self.assertRaisesRegex(ServiceError, "unknown_search"):
                service.published_snapshot(paid, search_id=authorized["searchId"])

    def test_http_search_without_an_account_is_unauthorized(self):
        import http.client

        with tempfile.TemporaryDirectory() as folder:
            service = CommunityService(
                Path(folder) / "db.sqlite",
                search_cost=4,
                artifacts=Path(folder) / "artifacts",
            )
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(service))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host, port = server.server_address
                origin = f"http://{host}:{port}"
                conn = http.client.HTTPConnection(host, port, timeout=10)
                headers = {"Content-Type": "application/json", "Origin": origin}
                conn.request(
                    "POST",
                    "/api/searches",
                    json.dumps(
                        {
                            "idempotencyKey": "no-account-search-01",
                            "queryMap": json.loads(QUERY.read_text(encoding="utf-8")),
                        }
                    ),
                    headers,
                )
                response = conn.getresponse()
                payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 401)
                self.assertEqual(payload["error"], "unauthorized")
                conn.request("GET", "/api/published-snapshot?searchId=nope", headers=headers)
                snapshot = conn.getresponse()
                self.assertEqual(snapshot.status, 401)
                snapshot.read()
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
