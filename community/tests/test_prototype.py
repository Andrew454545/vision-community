"""Prototype catalog, capture-resolved search, and HTTP search loop."""

from __future__ import annotations

import base64
import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from community.features import MODEL_ID, embedding_for, render_faces, sha256_hex
from community.server import handler_for
from community.service import CommunityService, ServiceError
from community.worker import ProcessingWorker


ROOT = Path(__file__).resolve().parents[1]
PROTOTYPE = ROOT / "prototype_catalog.json"
SAMPLE = ROOT / "web" / "sample-query.json"


class PrototypeLoopTest(unittest.TestCase):
    def test_prototype_catalog_search_ranks_reference_first(self):
        with tempfile.TemporaryDirectory() as folder:
            service = CommunityService(
                Path(folder) / "db.sqlite",
                search_cost=4,
                artifacts=Path(folder) / "artifacts",
                segment_capacity=50,
            )
            catalog = json.loads(PROTOTYPE.read_text(encoding="utf-8"))
            self.assertEqual(service.import_jobs(catalog), 28)
            account = service.create_account()
            lease = service.lease(account["accountId"], "scene", 4)
            self.assertNotIn("faces", lease["items"][0])
            service.submit(
                account["accountId"], lease["leaseId"], ProcessingWorker().process_lease(lease)
            )
            sample = json.loads(SAMPLE.read_text(encoding="utf-8"))
            result = service.search(
                account["accountId"], None, "proto-search-001", query_map=sample
            )
            first = result["map"]["customCoordinates"][0]
            self.assertEqual(first["panoId"], "PrototypeBerkeleyCA000001")
            self.assertEqual(first["extra"]["visionRank"], 1)
            self.assertGreater(first["extra"]["visionScore"], 0.99)
            self.assertEqual(service.status(account["accountId"])["units"], 0)

    def test_query_without_pano_date_still_matches_indexed_capture(self):
        with tempfile.TemporaryDirectory() as folder:
            service = CommunityService(
                Path(folder) / "db.sqlite",
                search_cost=4,
                artifacts=Path(folder) / "artifacts",
                segment_capacity=50,
            )
            service.import_jobs(json.loads(PROTOTYPE.read_text(encoding="utf-8")))
            account = service.create_account()
            lease = service.lease(account["accountId"], "scene", 4)
            service.submit(
                account["accountId"], lease["leaseId"], ProcessingWorker().process_lease(lease)
            )
            bare = {
                "name": "Bare pano",
                "customCoordinates": [
                    {
                        "lat": 37.869085,
                        "lng": -122.254775,
                        "heading": 270,
                        "pitch": 0,
                        "zoom": 0,
                        "panoId": "PrototypeBerkeleyCA000001",
                    }
                ],
            }
            result = service.search(
                account["accountId"], None, "proto-bare-001", query_map=bare
            )
            self.assertEqual(result["map"]["customCoordinates"][0]["panoId"], "PrototypeBerkeleyCA000001")
            self.assertGreater(result["map"]["customCoordinates"][0]["extra"]["visionScore"], 0.99)


class PrototypeRankingFilterTest(unittest.TestCase):
    def test_highest_score_country_generation_and_per_country_cap(self):
        with tempfile.TemporaryDirectory() as folder:
            service = CommunityService(
                Path(folder) / "db.sqlite",
                search_cost=1,
                artifacts=Path(folder) / "artifacts",
                segment_capacity=50,
            )
            service.import_jobs(json.loads(PROTOTYPE.read_text(encoding="utf-8")))
            status = service.status()
            self.assertIn("Japan", status["countries"])
            self.assertIn("USA", status["countries"])
            self.assertEqual(status["cameraGenerations"], ["gen3", "gen4"])
            account = service.create_account()
            lease = service.lease(account["accountId"], "scene", 12)
            service.submit(
                account["accountId"], lease["leaseId"], ProcessingWorker().process_lease(lease)
            )
            sample = json.loads(SAMPLE.read_text(encoding="utf-8"))

            ranked = service.search(
                account["accountId"],
                None,
                "rank-all-001",
                query_map=sample,
                result_count=200,
                max_per_country=25,
            )
            hits = ranked["map"]["customCoordinates"]
            self.assertEqual(len(hits), 12)
            self.assertEqual(hits[0]["panoId"], "PrototypeBerkeleyCA000001")
            scores = [hit["extra"]["visionScore"] for hit in hits]
            self.assertEqual(scores, sorted(scores, reverse=True))
            self.assertEqual([hit["extra"]["visionRank"] for hit in hits], list(range(1, 13)))

            japan = service.search(
                account["accountId"],
                None,
                "rank-japan-001",
                query_map=sample,
                country_filter_mode="include",
                countries=["Japan"],
            )
            japan_hits = japan["map"]["customCoordinates"]
            self.assertTrue(japan_hits)
            self.assertTrue(all(hit["extra"]["tags"][0] == "Japan" for hit in japan_hits))
            self.assertEqual(japan_hits[0]["panoId"], "PrototypeShibuyaJP000004")

            no_us = service.search(
                account["accountId"],
                None,
                "rank-exclude-us-001",
                query_map=sample,
                country_filter_mode="exclude",
                countries=["United States"],
            )
            self.assertTrue(no_us["map"]["customCoordinates"])
            self.assertTrue(
                all(hit["extra"]["tags"][0] != "USA" for hit in no_us["map"]["customCoordinates"])
            )

            gen3 = service.search(
                account["accountId"],
                None,
                "rank-gen3-001",
                query_map=sample,
                camera_generations=["gen3"],
            )
            gen3_hits = gen3["map"]["customCoordinates"]
            self.assertTrue(gen3_hits)
            self.assertTrue(all(hit["extra"]["visionCameraGeneration"] == "gen3" for hit in gen3_hits))
            self.assertEqual(
                {hit["panoId"] for hit in gen3_hits},
                {"PrototypeCapeTownZA00005", "PrototypeRioBR00000010"},
            )

            capped = service.search(
                account["accountId"],
                None,
                "rank-cap-001",
                query_map=sample,
                result_count=8,
                max_per_country=1,
            )
            countries = [hit["extra"]["tags"][0] for hit in capped["map"]["customCoordinates"]]
            self.assertEqual(len(countries), len(set(countries)))
            self.assertEqual(len(countries), 8)
            self.assertEqual(countries[0], "USA")

            with self.assertRaisesRegex(ServiceError, "invalid_country_filter"):
                service.search(
                    account["accountId"],
                    None,
                    "rank-empty-include-001",
                    query_map=sample,
                    country_filter_mode="include",
                    countries=[],
                )


class PrototypeHttpTest(unittest.TestCase):
    def test_http_prototype_search_loop(self):
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
                origin = f"http://{host}:{port}"
                conn = http.client.HTTPConnection(host, port, timeout=20)

                def request(method, path, body=None, cookie=None):
                    headers = {"Origin": origin, "Host": f"{host}:{port}"}
                    payload = None
                    if body is not None:
                        headers["Content-Type"] = "application/json"
                        payload = json.dumps(body)
                    if cookie:
                        headers["Cookie"] = cookie
                    conn.request(method, path, payload, headers)
                    response = conn.getresponse()
                    raw = response.read()
                    data = json.loads(raw.decode("utf-8")) if raw else {}
                    return response, data

                sample, body = request("GET", "/sample-query.json")
                self.assertEqual(sample.status, 200)
                self.assertEqual(body["customCoordinates"][0]["panoId"], "PrototypeBerkeleyCA000001")

                created, account = request("POST", "/api/accounts", {})
                self.assertEqual(created.status, 201)
                cookie = created.getheader("Set-Cookie").split(";")[0]
                leased, lease = request(
                    "POST", "/api/leases", {"lane": "scene", "count": 4, "pace": "slow"}, cookie
                )
                self.assertEqual(leased.status, 200)
                outputs = ProcessingWorker("slow").process_lease(lease)
                encoded = []
                for item in outputs:
                    encoded.append(
                        {
                            "locationId": item["locationId"],
                            "model": item["model"],
                            "embeddingSha256": item["embeddingSha256"],
                            "outputSha256": item["outputSha256"],
                            "embedding": base64.b64encode(item["embedding"]).decode("ascii"),
                        }
                    )
                submitted, accepted = request(
                    "POST",
                    "/api/submissions",
                    {"leaseId": lease["leaseId"], "outputs": encoded},
                    cookie,
                )
                self.assertEqual(submitted.status, 200)
                self.assertEqual(accepted["unitsEarned"], 4)
                searched, result = request(
                    "POST",
                    "/api/searches",
                    {
                        "idempotencyKey": "http-proto-search-001",
                        "lane": "scene",
                        "queryMap": body,
                        "resultCount": 25,
                        "maxPerCountry": 25,
                    },
                    cookie,
                )
                self.assertEqual(searched.status, 200)
                self.assertEqual(result["map"]["customCoordinates"][0]["panoId"], "PrototypeBerkeleyCA000001")
                self.assertGreater(result["map"]["customCoordinates"][0]["extra"]["visionScore"], 0.99)
            finally:
                server.shutdown()
                server.server_close()


class ExtractorParityTest(unittest.TestCase):
    def test_python_berkeley_embedding_is_stable(self):
        faces = render_faces("PrototypeBerkeleyCA000001", "2019-06", "scene", MODEL_ID)
        embedding = embedding_for("scene", faces)
        self.assertEqual(len(embedding), 96)
        self.assertEqual(
            sha256_hex(embedding),
            "184d8147b3d5024f41578daa88e27aba6439e5ba0d371b4921f54602775091df",
        )

    def test_worker_model_matches_python(self):
        import shutil
        import subprocess

        if shutil.which("node") is None:
            self.skipTest("node")
        script = Path(__file__).resolve().parents[2] / "deploy" / "cloudflare" / "src" / "parity.mjs"
        faces = render_faces("PrototypeBerkeleyCA000001", "2019-06", "scene", MODEL_ID)
        expected = sha256_hex(embedding_for("scene", faces))
        completed = subprocess.run(
            ["node", str(script), "PrototypeBerkeleyCA000001", "2019-06", "scene"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.stdout.strip(), expected)


if __name__ == "__main__":
    unittest.main()
