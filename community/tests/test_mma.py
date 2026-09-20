import json
import tempfile
import unittest
from pathlib import Path

from community.catalog import load_jobs, parse_tsv
from community.features import MODEL_ID
from community.mma import parse_map
from community.service import CommunityService
from community.source import SourceError
from community.worker import ProcessingWorker


STREET = Path(__file__).resolve().parents[1] / "street_catalog.json"


class MetadataCatalogTest(unittest.TestCase):
    def test_rejects_stored_imagery_and_tile_urls(self):
        with self.assertRaises(SourceError):
            load_jobs({
                "source": "street-metadata",
                "persistImagery": True,
                "locations": [{"panoId": "Abcdefghijklmnopqr0123", "lat": 1, "lng": 2}],
            })
        with self.assertRaises(SourceError):
            load_jobs({
                "source": "street-metadata",
                "persistImagery": False,
                "locations": [{
                    "panoId": "Abcdefghijklmnopqr0123",
                    "lat": 1,
                    "lng": 2,
                    "url": "https://maps.googleapis.com/maps/api/streetview",
                }],
            })

    def test_tsv_metadata_import(self):
        text = (
            "lat\tlng\tpano_id\tcapture_year\tcapture_month\tcountry\tcamera_generation\theading\tpitch\tzoom\n"
            "10\t20\tCommunityPanoTSV000000001\t2020\t06\tItaly\tgen4\t90\t0\t0\n"
        )
        jobs = load_jobs(parse_tsv(text))
        self.assertEqual(jobs[0]["assetId"], "CommunityPanoTSV000000001")
        self.assertEqual(jobs[0]["capture"], "2020-06")
        self.assertEqual(jobs[0]["rights"], "metadata-only-no-imagery")


class MMASearchOutputTest(unittest.TestCase):
    def test_search_returns_map_making_json(self):
        with tempfile.TemporaryDirectory() as folder:
            service = CommunityService(
                Path(folder) / "db.sqlite",
                search_cost=4,
                artifacts=Path(folder) / "artifacts",
                segment_capacity=20,
            )
            catalog = json.loads(STREET.read_text(encoding="utf-8"))
            self.assertEqual(service.import_jobs(catalog), 5)
            account = service.create_account()
            lease = service.lease(account["accountId"], "scene", 4)
            self.assertFalse(lease["items"][0].get("persistImagery", True))
            self.assertEqual(lease["items"][0]["panoId"], "CommunityPano000000000001")
            self.assertNotIn("faces", lease["items"][0])
            self.assertIn("facesSha256", lease["items"][0])
            service.submit(account["accountId"], lease["leaseId"], ProcessingWorker().process_lease(lease))
            query_map = {
                "name": "Reference",
                "customCoordinates": [
                    {
                        "lat": 41.9,
                        "lng": 12.5,
                        "heading": 90,
                        "pitch": 0,
                        "zoom": 0,
                        "panoId": "CommunityPano000000000001",
                        "extra": {"panoDate": "2020-06", "tags": ["Italy"]},
                    }
                ],
            }
            parsed = parse_map(query_map)
            self.assertEqual(parsed["examples"][0]["panoId"], "CommunityPano000000000001")
            result = service.search(
                account["accountId"],
                None,
                "mma-search-001",
                query_map=query_map,
            )
            self.assertFalse(result["persistImagery"])
            self.assertEqual(result["map"]["name"], "Reference")
            first = result["map"]["customCoordinates"][0]
            self.assertEqual(first["panoId"], "CommunityPano000000000001")
            self.assertEqual(first["extra"]["visionRank"], 1)
            self.assertGreater(first["extra"]["visionScore"], 0.99)
            self.assertEqual(service.status()["persistImagery"], False)
            pose = result["results"][0]["pose"]
            self.assertEqual(pose["panoId"], "CommunityPano000000000001")
            self.assertAlmostEqual(pose["lat"], 41.9, places=4)


class ShardImportAndHttpTest(unittest.TestCase):
    def test_streaming_tsv_shard_is_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            tsv = root / "shard.tsv"
            header = "lat\tlng\tpano_id\tcapture_year\tcapture_month\tcountry\tcamera_generation\theading\tpitch\tzoom\n"
            rows = [
                f"{10 + index * 0.01}\t{20 + index * 0.01}\tShardPano{index:012d}\t2020\t06\tItaly\tgen4\t90\t0\t0\n"
                for index in range(250)
            ]
            rows.append("10.0\t20.0\tShardPanoNearFirst000\t2020\t06\tItaly\tgen4\t90\t0\t0\n")
            tsv.write_text(header + "".join(rows), encoding="utf-8")
            service = CommunityService(root / "db.sqlite", artifacts=root / "artifacts", search_cost=4)
            first = service.import_shard(tsv, batch_size=40)
            self.assertEqual(first["imported"], 251)
            self.assertFalse(first["skipped"])
            second = service.import_shard(tsv)
            self.assertTrue(second["skipped"])
            self.assertEqual(second["imported"], 0)
            import sqlite3

            with sqlite3.connect(service.database) as connection:
                pending = connection.execute(
                    "SELECT COUNT(*) FROM locations WHERE queue_state='pending'"
                ).fetchone()[0]
                deferred = connection.execute(
                    "SELECT COUNT(*) FROM locations WHERE queue_state='deferred'"
                ).fetchone()[0]
            self.assertEqual(pending, 250)
            self.assertEqual(deferred, 1)

    def test_http_lease_omits_image_bytes(self):
        import http.client
        import json as json_lib
        import threading
        from http.server import ThreadingHTTPServer

        from community.server import handler_for

        with tempfile.TemporaryDirectory() as folder:
            service = CommunityService(
                Path(folder) / "db.sqlite",
                search_cost=4,
                artifacts=Path(folder) / "artifacts",
                segment_capacity=20,
            )
            service.import_jobs(json.loads(STREET.read_text(encoding="utf-8")))
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(service))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host, port = server.server_address
                origin = f"http://{host}:{port}"
                conn = http.client.HTTPConnection(host, port, timeout=10)

                def post(path, body, cookie=None):
                    headers = {
                        "Content-Type": "application/json",
                        "Origin": origin,
                        "Host": f"{host}:{port}",
                    }
                    if cookie:
                        headers["Cookie"] = cookie
                    conn.request("POST", path, json_lib.dumps(body), headers)
                    response = conn.getresponse()
                    payload = json_lib.loads(response.read().decode("utf-8"))
                    return response, payload

                created, payload = post("/api/accounts", {})
                self.assertEqual(created.status, 201)
                cookie = created.getheader("Set-Cookie").split(";")[0]
                self.assertIn("vision_session=", cookie)
                leased, lease = post("/api/leases", {"lane": "scene", "count": 1, "pace": "slow"}, cookie)
                self.assertEqual(leased.status, 200)
                self.assertNotIn("faces", lease["items"][0])
                self.assertTrue(lease["items"][0]["facesSha256"])
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
