import json
import tempfile
import unittest
from pathlib import Path

from community.catalog import load_jobs, parse_tsv
from community.features import MODEL_ID
from community.mma import dump_map, location_record, parse_map
from community.object_index import encode_object_submission, validate_object_index
from community.service import CommunityService
from community.tests.test_object_index import contract_bundle
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


class MMAMapParseTest(unittest.TestCase):
    def test_samples_unique_views_like_local_vision(self):
        rows = [
            {"panoId": f"Pano{index:03d}", "heading": index, "pitch": 0, "zoom": 0, "lat": 0, "lng": 0}
            for index in range(150)
        ]
        parsed = parse_map({"name": "Wide", "customCoordinates": rows})
        self.assertEqual(len(parsed["examples"]), 100)
        self.assertEqual(parsed["examples"][0]["panoId"], "Pano000")
        self.assertEqual(parsed["examples"][-1]["panoId"], "Pano149")

    def test_accepts_locations_key_and_skips_duplicate_views(self):
        parsed = parse_map({
            "locations": [
                {"pano": "SamePano", "heading": 10, "pitch": 0, "zoom": 0},
                {"panoId": "SamePano", "heading": 10, "pitch": 0, "zoom": 0},
                {"pano_id": "OtherPano", "heading": 20},
            ]
        })
        self.assertEqual([item["panoId"] for item in parsed["examples"]], ["SamePano", "OtherPano"])


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
            self.assertEqual(first["extra"]["tags"], ["Italy"])
            self.assertEqual(first["extra"]["visionPruneMeters"], 100)
            self.assertEqual(first["extra"]["visionQueryMode"], "scene")
            self.assertEqual(service.status()["persistImagery"], False)
            pose = result["results"][0]["pose"]
            self.assertEqual(pose["panoId"], "CommunityPano000000000001")
            self.assertAlmostEqual(pose["lat"], 41.9, places=4)
            extra = service.lease(account["accountId"], "object", 1)
            manifest, files, tsv = contract_bundle(
                extra["items"], extra["leaseId"], Path(folder) / "locations.tsv"
            )
            object_outputs = validate_object_index(
                manifest, files, tsv, extra["items"], lease_id=extra["leaseId"]
            )
            service.submit(
                account["accountId"],
                extra["leaseId"],
                object_outputs,
                object_index=encode_object_submission(manifest, files, tsv),
            )
            capped = service.search(
                account["accountId"],
                None,
                "mma-search-cap",
                query_map=query_map,
                result_count=2,
                max_per_country=1,
            )
            countries = [hit["extra"]["tags"][0] for hit in capped["map"]["customCoordinates"]]
            self.assertEqual(len(countries), len(set(countries)))
            self.assertLessEqual(len(countries), 2)


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


class VisionCountryTagTest(unittest.TestCase):
    def test_each_location_is_tagged_with_the_country_name(self):
        record = location_record(
            lat=41.9,
            lng=12.5,
            heading=90,
            pitch=0,
            zoom=0,
            pano_id="CommunityPano000000000001",
            rank=1,
            score=0.12,
            query_name="Example search",
            lane="scene",
            country="United States",
        )
        self.assertEqual(record["extra"]["tags"], ["USA"])
        self.assertNotIn("visionObjectClass", record["extra"])
        dumped = dump_map({"name": "Example search", "customCoordinates": [record]})
        parsed = json.loads(dumped)
        self.assertEqual(parsed["customCoordinates"][0]["extra"]["tags"], ["USA"])
        self.assertLess(dumped.index('"customCoordinates"'), dumped.index('"name"'))
        empty = location_record(
            lat=0,
            lng=0,
            heading=0,
            pitch=0,
            zoom=0,
            pano_id="CommunityPano000000000002",
            rank=2,
            score=0.01,
            query_name="Example search",
            lane="object",
            country="",
        )
        self.assertEqual(empty["extra"]["tags"], [""])
        self.assertEqual(empty["extra"]["visionObjectLane"], "object")


if __name__ == "__main__":
    unittest.main()

