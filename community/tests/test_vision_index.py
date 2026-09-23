import base64
import hashlib
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from community.four_view import BYTES_PER_LOCATION, VISION_FOUR_VIEW_MODEL, valid_four_view_record
from community.mma import SCENE_MODEL_NAME
from community.server import handler_for
from community.service import CommunityService
from community.vision_index import (
    VisionIndexError,
    finish_scene_coordinates,
    index_from_queue,
    index_locations_tsv,
    location_tsv_line,
    search_indexes,
    search_input,
    write_locations_tsv,
)


ROOT = Path(__file__).resolve().parents[2]
PROTOTYPE = Path(__file__).resolve().parents[1] / "prototype_catalog.json"
LAYOUT = {
    "bytesPerLocation": 3080,
    "completeViewMask": 15,
    "feature": "four-view-index",
    "version": 4,
    "viewsPerLocation": 4,
}


def sample_record(fill: int = 7) -> bytes:
    view = bytes([0x00, 0x3C]) + bytes([fill]) * 768
    return view * 4


def fake_runner(argv, _env, _cwd):
    if "index-layout" in argv:
        return 0, json.dumps(LAYOUT), ""
    if "index-four-views" in argv:
        tsv = Path(argv[argv.index("--locations-tsv") + 1])
        index_dir = Path(argv[argv.index("--index-dir") + 1])
        rows = [line for line in tsv.read_text(encoding="utf-8").splitlines() if line.strip()]
        index_dir.mkdir(parents=True, exist_ok=True)
        blob = b"".join(sample_record(index + 1) for index in range(len(rows)))
        (index_dir / "shard-000000.i8").write_bytes(blob)
        (index_dir / "manifest.json").write_text(
            json.dumps({"indexedLocations": len(rows), "bytesPerLocation": 3080, "version": 4}),
            encoding="utf-8",
        )
        return 0, "", ""
    if "search-four-view-index" in argv:
        output = Path(argv[argv.index("--output") + 1])
        output.write_text(
            json.dumps({"queries": [{"name": "VISION Community", "hits": [{"locationIndex": 0, "similarity": 0.42, "viewOffset": 1}]}]}),
            encoding="utf-8",
        )
        return 0, "", ""
    return 1, "", "unexpected"


class FourViewRecordTest(unittest.TestCase):
    def test_record_shape_matches_vision_layout(self):
        record = sample_record()
        self.assertEqual(len(record), BYTES_PER_LOCATION)
        self.assertTrue(valid_four_view_record(record))
        self.assertFalse(valid_four_view_record(record[:96]))
        zero = bytearray(record)
        zero[0] = 0
        zero[1] = 0
        self.assertFalse(valid_four_view_record(bytes(zero)))
        worker = (ROOT / "deploy/cloudflare/src/worker.js").read_text(encoding="utf-8")
        self.assertIn('const FOUR_VIEW_MODEL = "vision-four-view-v4"', worker)
        self.assertIn("const FOUR_VIEW_BYTES = 3080", worker)
        self.assertIn("function validFourViewRecord", worker)

    def test_tsv_line_uses_eleven_vision_columns(self):
        line = location_tsv_line(
            {
                "locationId": 12,
                "lat": 39.411918644637325,
                "lng": 20.87079841805392,
                "heading": 257.38,
                "pitch": 0,
                "zoom": 0,
                "panoId": "ClPNSqYQCEm2Mow-ZQD6PA",
                "country": "Greece",
                "cameraGeneration": "gen4",
            }
        )
        parts = line.split("\t")
        self.assertEqual(len(parts), 11)
        self.assertEqual(parts[4], "257.38")
        self.assertEqual(parts[7], "ClPNSqYQCEm2Mow-ZQD6PA")
        self.assertEqual(parts[10], "no road name")


class VisionIndexCommandTest(unittest.TestCase):
    def test_refuses_to_touch_the_live_vision_job(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            tsv = root / "locations.tsv"
            write_locations_tsv(
                [{"locationId": 1, "lat": 1, "lng": 2, "panoId": "abc"}],
                tsv,
            )
            live = root / "four-view-remainder-work" / "index"
            with self.assertRaises(VisionIndexError) as caught:
                index_locations_tsv(
                    tsv,
                    index_dir=live,
                    checkpoint=root / "checkpoint.json",
                    output=root / "output.json",
                    runner=fake_runner,
                    use_nice=False,
                )
            self.assertEqual(caught.exception.code, "refusing_live_vision_path")

    def test_invokes_the_four_view_binary_contract(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            tsv = root / "locations.tsv"
            write_locations_tsv(
                [{"locationId": 7, "lat": 10.5, "lng": 20, "heading": 90, "panoId": "pano"}],
                tsv,
            )
            seen = []

            def runner(argv, env, cwd):
                seen.append(argv)
                return fake_runner(argv, env, cwd)

            report = index_locations_tsv(
                tsv,
                index_dir=root / "index",
                checkpoint=root / "checkpoint.json",
                output=root / "output.json",
                model_dir=root / "model",
                binary=root / "mma-vision",
                pace="slow",
                runner=runner,
                use_nice=False,
            )
            self.assertTrue(report["ok"])
            self.assertEqual(report["bytesPerLocation"], 3080)
            index_call = next(argv for argv in seen if "index-four-views" in argv)
            self.assertIn("--model-dir", index_call)
            self.assertIn("--locations-tsv", index_call)
            self.assertIn("--index-dir", index_call)
            self.assertIn("--checkpoint", index_call)
            self.assertEqual(index_call[index_call.index("--locations-tsv") + 1], str(tsv))
            self.assertNotIn("four-view-remainder-work", " ".join(index_call))
            spec = json.loads((root / "input.json").read_text(encoding="utf-8"))
            self.assertEqual(spec["embeddingBatchSize"], 16)
            self.assertEqual(spec["imageEncoderSessions"], 1)
            self.assertEqual(spec["shardLocations"], 50000)
            self.assertEqual(seen[0][0], str(root / "mma-vision"))
            self.assertIn("index-layout", seen[0])
            record = (root / "index" / "shard-000000.i8").read_bytes()
            self.assertEqual(len(record), 3080)
            self.assertTrue(valid_four_view_record(record))

    def test_queue_submission_stores_the_vision_record_not_visual_v1(self):
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
                report = index_from_queue(
                    url=f"http://{host}:{port}",
                    pace="slow",
                    batches=1,
                    count=1,
                    work_dir=root / "work",
                    persist_session=False,
                    runner=fake_runner,
                    use_nice=False,
                    binary=root / "mma-vision",
                    model_dir=root / "model",
                )
            finally:
                server.shutdown()
                server.server_close()
            self.assertTrue(report["ok"])
            self.assertEqual(report["accepted"], 1)
            self.assertEqual(report["unitsEarned"], 1)
            self.assertEqual(report["model"], VISION_FOUR_VIEW_MODEL)
            with service._connection() as connection:
                row = connection.execute(
                    "SELECT embedding, four_view_sha256, four_view_key FROM published_index"
                ).fetchone()
            self.assertIsNone(row["embedding"])
            self.assertEqual(len(row["four_view_sha256"]), 64)
            stored = (root / "artifacts" / row["four_view_key"]).read_bytes()
            self.assertEqual(len(stored), 3080)
            self.assertEqual(hashlib.sha256(stored).hexdigest(), row["four_view_sha256"])
            self.assertTrue(valid_four_view_record(stored))

    def test_bad_record_earns_nothing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = CommunityService(root / "db.sqlite", search_cost=4, artifacts=root / "artifacts")
            service.import_jobs(json.loads(PROTOTYPE.read_text(encoding="utf-8")))
            account = service.create_account()
            lease = service.lease(account["accountId"], "scene", 1, pace="slow", client="cli")
            item = lease["items"][0]
            with self.assertRaises(Exception):
                service.submit(
                    account["accountId"],
                    lease["leaseId"],
                    [
                        {
                            "locationId": item["locationId"],
                            "outputSha256": hashlib.sha256(b"nope").hexdigest(),
                            "embedding": base64.b64encode(b"nope").decode("ascii"),
                            "model": VISION_FOUR_VIEW_MODEL,
                        }
                    ],
                )
            self.assertEqual(service.status(account["accountId"])["units"], 0)

    def test_search_reads_the_four_view_index(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            run = root / "run"
            write_locations_tsv(
                [
                    {
                        "locationId": 3,
                        "lat": 41.89,
                        "lng": 12.49,
                        "heading": 10,
                        "panoId": "pano",
                        "country": "Italy",
                        "cameraGeneration": "gen4",
                    }
                ],
                run / "locations.tsv",
            )
            index = run / "index"
            index.mkdir()
            (index / "manifest.json").write_text("{}", encoding="utf-8")
            (index / "shard-000000.i8").write_bytes(sample_record())
            result = search_indexes(root, "a red door", runner=fake_runner, use_nice=False, binary=root / "mma-vision", model_dir=root / "model")
            self.assertEqual(result["indexes"], 1)
            hit = result["map"]["customCoordinates"][0]
            self.assertEqual(hit["panoId"], "pano")
            self.assertEqual(hit["extra"]["visionModel"], SCENE_MODEL_NAME)
            self.assertEqual(hit["extra"]["visionMinScore"], 0.01)
            self.assertEqual(hit["extra"]["visionSourceIndex"], 0)
            self.assertEqual(hit["extra"]["visionHeadingOffset"], 90)
            self.assertEqual(hit["extra"]["visionProcessedLocations"], 1)
            self.assertIsNone(hit["extra"]["visionObjectLane"])
            self.assertIsNone(hit["extra"]["visionObjectClass"])
            self.assertEqual(hit["extra"]["tags"], ["Italy"])
            self.assertEqual(hit["heading"], 100)

    def test_site_command_uses_the_vision_indexer_for_places(self):
        app = (ROOT / "community/web/app.js").read_text(encoding="utf-8")
        html = (ROOT / "community/web/index.html").read_text(encoding="utf-8")
        self.assertIn("community.vision_index", app)
        self.assertIn("community.object_index", app)
        self.assertIn('lane === "scene"', app)
        self.assertIn("same indexer as VISION", html)
        self.assertIn("same object indexer as VISION", html)
        self.assertIn("community.vision_index", html)
        self.assertIn("vision-community-indexing", app)
        self.assertIn("keeps going until you stop it", html)
        self.assertIn("copyComputerSearch", app)
        self.assertIn("community.object_index", app)
        self.assertIn('"--search"', app)
        self.assertIn("--confidence", app)
        self.assertIn('? "python" : "python3"', app)
        self.assertIn("-m community.vision_index", app)
        self.assertIn("--max-per-country", app)
        self.assertIn("--reject-road-names", app)
        self.assertIn("--import-cutoff", app)
        self.assertNotIn("Road names are not in the object index yet.", app)
        self.assertIn("map-making.app/keys", html)

    def test_four_view_search_keeps_the_chosen_direction_and_countries(self):
        spec = search_input(
            "red barn",
            view_direction="right",
            result_count=10,
            country_mode="include",
            countries=["Italy"],
        )
        query = spec["queries"][0]
        self.assertEqual(query["viewOffsets"], [1])
        self.assertEqual(query["includeCountries"], ["Italy"])
        self.assertEqual(query["mode"], "textOnly")
        self.assertEqual(spec["topK"], 10)
        blended = search_input(
            "red barn",
            result_count=200,
            max_per_country=25,
            description_weight=50,
            examples=[{"panoId": "abc", "heading": 0, "pitch": 0, "zoom": 0}],
            excluding=True,
        )
        blended_query = blended["queries"][0]
        self.assertEqual(blended_query["mode"], "title50Contrastive50")
        self.assertEqual(blended_query["minSimilarity"], 0.6531793)
        self.assertEqual(blended_query["examples"][0]["panoId"], "abc")
        self.assertEqual(blended["topK"], 800)

    def test_scene_results_keep_the_country_cap_and_skip_nearby_places(self):
        hits = [
            {"lat": 1, "lng": 1, "panoId": "a", "extra": {"tags": ["Italy"], "visionScore": 0.9}},
            {"lat": 1.0001, "lng": 1, "panoId": "b", "extra": {"tags": ["Italy"], "visionScore": 0.8}},
            {"lat": 40, "lng": 10, "panoId": "c", "extra": {"tags": ["France"], "visionScore": 0.7}},
        ]
        capped = finish_scene_coordinates(hits, result_count=10, max_per_country=1, prompt="barn")
        self.assertEqual([item["panoId"] for item in capped["customCoordinates"]], ["a", "c"])
        excluded = finish_scene_coordinates(
            hits,
            result_count=10,
            max_per_country=25,
            prompt="barn",
            exclude_map={"customCoordinates": [{"lat": 1, "lng": 1, "panoId": "old"}]},
        )
        self.assertEqual([item["panoId"] for item in excluded["customCoordinates"]], ["c"])

    def test_scene_ties_follow_location_index(self):
        hits = [
            {"lat": 1, "lng": 1, "panoId": "later", "extra": {"tags": ["Italy"], "visionScore": 0.5, "visionSourceIndex": 4}},
            {"lat": 2, "lng": 2, "panoId": "earlier", "extra": {"tags": ["France"], "visionScore": 0.5, "visionSourceIndex": 1}},
        ]
        ordered = finish_scene_coordinates(hits, result_count=10, max_per_country=25, prompt="barn")
        self.assertEqual([item["panoId"] for item in ordered["customCoordinates"]], ["earlier", "later"])

    def test_import_cutoff_skips_earlier_scene_indexes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            searched = []

            def runner(argv, _env, _cwd):
                if "search-four-view-index" not in argv:
                    return 1, "", "unexpected"
                tsv = Path(argv[argv.index("--locations-tsv") + 1])
                searched.append(tsv.parent.name)
                output = Path(argv[argv.index("--output") + 1])
                output.write_text(json.dumps({
                    "queries": [{"name": "VISION Community", "hits": [{"locationIndex": 0, "similarity": 0.2, "viewOffset": 0}]}],
                }), encoding="utf-8")
                return 0, "", ""

            for name, pano in (("a-early", "pano-a"), ("b-later", "pano-b")):
                run = root / name
                write_locations_tsv(
                    [{
                        "locationId": 1,
                        "lat": 41.89,
                        "lng": 12.49,
                        "heading": 10,
                        "panoId": pano,
                        "country": "Italy",
                        "cameraGeneration": "gen4",
                    }],
                    run / "locations.tsv",
                )
                index = run / "index"
                index.mkdir()
                (index / "manifest.json").write_text("{}", encoding="utf-8")
            result = search_indexes(
                root,
                "a red door",
                runner=runner,
                use_nice=False,
                binary=root / "mma-vision",
                model_dir=root / "model",
                import_cutoff=1,
            )
            self.assertEqual(searched, ["b-later"])
            self.assertEqual(result["indexes"], 1)
            self.assertEqual(result["map"]["customCoordinates"][0]["panoId"], "pano-b")

    def test_indexer_resumes_after_a_clean_pause(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            tsv = root / "locations.tsv"
            write_locations_tsv(
                [{"locationId": 7, "lat": 10.5, "lng": 20, "heading": 90, "panoId": "pano"}],
                tsv,
            )
            calls = {"index": 0}

            def runner(argv, env, cwd):
                if "index-four-views" in argv:
                    calls["index"] += 1
                    checkpoint = Path(argv[argv.index("--checkpoint") + 1])
                    if calls["index"] == 1:
                        checkpoint.write_text(
                            json.dumps({"completed": False, "nextLocationIndex": 0, "incompleteLocations": 1}),
                            encoding="utf-8",
                        )
                        return 0, "", ""
                    result = fake_runner(argv, env, cwd)
                    checkpoint.write_text(
                        json.dumps({"completed": True, "nextLocationIndex": 1, "incompleteLocations": 0}),
                        encoding="utf-8",
                    )
                    return result
                return fake_runner(argv, env, cwd)

            report = index_locations_tsv(
                tsv,
                index_dir=root / "index",
                checkpoint=root / "checkpoint.json",
                output=root / "output.json",
                model_dir=root / "model",
                binary=root / "mma-vision",
                pace="max",
                runner=runner,
                use_nice=False,
            )
            self.assertTrue(report["ok"])
            self.assertEqual(calls["index"], 2)
            self.assertEqual((root / "index" / "shard-000000.i8").stat().st_size, 3080)

    def test_queue_indexing_continues_until_the_queue_is_empty(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            document = json.loads(PROTOTYPE.read_text(encoding="utf-8"))
            document["locations"] = document["locations"][:2]
            service = CommunityService(root / "db.sqlite", search_cost=4, artifacts=root / "artifacts")
            service.import_jobs(document)
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(service))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host, port = server.server_address
                report = index_from_queue(
                    url=f"http://{host}:{port}",
                    pace="slow",
                    count=1,
                    work_dir=root / "work",
                    persist_session=False,
                    runner=fake_runner,
                    use_nice=False,
                    binary=root / "mma-vision",
                    model_dir=root / "model",
                )
            finally:
                server.shutdown()
                server.server_close()
            self.assertEqual(report["batches"], 2)
            self.assertEqual(report["accepted"], 2)

    def test_skipped_place_is_not_leased_again(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            document = json.loads(PROTOTYPE.read_text(encoding="utf-8"))
            document["locations"] = [document["locations"][0]]
            service = CommunityService(root / "db.sqlite", search_cost=4, artifacts=root / "artifacts")
            service.import_jobs(document)
            account = service.create_account()
            lease = service.lease(account["accountId"], "scene", 1, pace="slow", client="cli", now=1000)
            self.assertEqual(lease["expiresAt"], 1000 + 6 * 60 * 60)
            released = service.release_lease(account["accountId"], lease["leaseId"], skip=True)
            self.assertTrue(released["skipped"])
            with self.assertRaises(Exception) as caught:
                service.lease(account["accountId"], "scene", 1, pace="slow", client="cli")
            self.assertEqual(caught.exception.code, "no_available_work")

    def test_paid_scene_records_rebuild_a_searchable_shard(self):
        from community.vision_index import discover_indexes, import_published_scenes

        lease = "cd" * 16
        record = sample_record()
        location = {
            "locationId": 7,
            "lat": 41.0,
            "lng": 12.0,
            "heading": 15,
            "pitch": 0,
            "zoom": 1,
            "panoId": "ClPNSqYQCEm2Mow-ZQD6PA",
            "country": "Italy",
            "cameraGeneration": "gen4",
        }

        class Session:
            def scene_index_catalog(self, _search_id):
                return {"indexes": [{"key": f"four-view-v4/{lease}.i8", "locations": [location]}]}

            def scene_index_file(self, _search_id, _key):
                return record

        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder)
            imported = import_published_scenes(Session(), "search", destination)
            self.assertEqual(imported, 1)
            runs = discover_indexes(destination)
            self.assertEqual(len(runs), 1)
            shard = (runs[0] / "index" / "shard-000000.i8").read_bytes()
            self.assertEqual(shard, record)
            line = (runs[0] / "locations.tsv").read_text(encoding="utf-8").split("\t")
            self.assertEqual(line[7], "ClPNSqYQCEm2Mow-ZQD6PA")
            self.assertEqual(line[8], "Italy")
