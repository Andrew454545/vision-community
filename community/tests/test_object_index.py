import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from community.object_index import (
    CODEBOOK_SHA256,
    COMMON_MODEL_SHA256,
    GLOBAL_START,
    HOT_CONCEPTS,
    HOT_FLOORS,
    OBJECT_ARCHITECTURE,
    OBJECT_CLASSES,
    OBJECT_COVERAGE,
    OBJECT_FEATURE,
    OBJECT_GLOBAL_MODE,
    OBJECT_INDEX_MODEL,
    OBJECT_POSITION_POLICY,
    OBJECT_RANKING,
    RUNTIME_IDENTITY,
    VisionIndexError,
    class_file_name,
    encode_object_submission,
    global_id_record,
    hot_file_name,
    index_object_tsv,
    index_segment_arguments,
    object_tsv_lines,
    sha256_hex,
    storage_floor,
    validate_object_index,
    write_object_tsv,
)
from community.service import CommunityService, ServiceError


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).resolve().parents[1] / "demo_catalog.json"


def file_entry(name, payload, records, record_bytes):
    return {
        "file": name,
        "recordBytes": record_bytes,
        "records": records,
        "bytes": len(payload),
        "sha256": sha256_hex(payload),
    }


def contract_bundle(items, lease_id, source_path):
    ordered = sorted(items, key=lambda item: item["locationId"])
    tsv = ("\n".join(object_tsv_lines(ordered)) + "\n").encode()
    total = len(ordered)
    files = {
        "location-offsets.bin": b"\x00" * (8 * total),
        "location-metadata.bin": b"\x00" * (8 * total),
        "global-location-ids.bin": b"".join(global_id_record(index) for index in range(total)),
        "semantic-pq128.bin": b"\x00" * (144 * 16 * total),
    }
    classes = []
    for class_id, name in OBJECT_CLASSES:
        file_name = class_file_name(class_id, name)
        files[file_name] = b""
        classes.append({
            "id": class_id,
            "name": name,
            "file": file_name,
            "storageFloor": storage_floor(class_id),
            "records": 0,
            "bytes": 0,
            "sha256": sha256_hex(b""),
        })
    hot = []
    for concept_id, name in enumerate(HOT_CONCEPTS):
        file_name = hot_file_name(concept_id, name)
        files[file_name] = b""
        hot.append({
            "id": concept_id,
            "name": name,
            "file": file_name,
            "storageFloor": HOT_FLOORS[concept_id],
            "records": 0,
            "bytes": 0,
            "sha256": sha256_hex(b""),
        })
    countries = []
    for item in ordered:
        country = item.get("country") or ""
        if country and country not in countries:
            countries.append(country)
    manifest = {
        "version": 4,
        "feature": OBJECT_FEATURE,
        "architecture": OBJECT_ARCHITECTURE,
        "sourceId": f"community-{lease_id}",
        "sourceTsv": str(source_path),
        "sourceBytes": len(tsv),
        "sourceSha256": sha256_hex(tsv),
        "modelSha256": COMMON_MODEL_SHA256,
        "runtimeIdentity": RUNTIME_IDENTITY,
        "totalLocations": total,
        "indexedLocations": total,
        "globalStart": GLOBAL_START,
        "globalIdMode": OBJECT_GLOBAL_MODE,
        "minimumGlobalLocation": GLOBAL_START,
        "maximumGlobalLocation": GLOBAL_START + total - 1,
        "imageSize": 640,
        "tileGrid": 2,
        "tileOverlap": 0.2,
        "minimumRelativeClassScore": 0.25,
        "smallObjectRelativeClassScore": 0,
        "fullTileArtifactThreshold": 0.98,
        "rankingStrategy": OBJECT_RANKING,
        "viewStrategy": "six-face-cube",
        "viewCount": 6,
        "faceSize": 640,
        "faceFov": 90,
        "bandsPerFace": 3,
        "bandWidth": 600,
        "bandHeight": 280,
        "bandOffset": 24,
        "bandFov": 90,
        "recordBytes": 32,
        "positionPolicy": OBJECT_POSITION_POLICY,
        "coverage": OBJECT_COVERAGE,
        "contractVersions": {
            "manifest": 4,
            "checkpoint": 4,
            "commonRecord": 3,
            "hotRecord": 1,
            "semanticRecord": 1,
            "metadataRecord": 1,
            "offsets": 1,
            "globalIds": 1,
        },
        "offsets": file_entry("location-offsets.bin", files["location-offsets.bin"], total, 8),
        "metadata": file_entry("location-metadata.bin", files["location-metadata.bin"], total, 8),
        "globalIds": file_entry("global-location-ids.bin", files["global-location-ids.bin"], total, 12),
        "semantic": {
            **file_entry("semantic-pq128.bin", files["semantic-pq128.bin"], total * 16, 144),
            "codec": "PQ128",
            "codebookSha256": CODEBOOK_SHA256,
            "embeddingDimensions": 512,
            "proposalsPerLocation": 16,
        },
        "countries": countries or [""],
        "classes": classes,
        "hotConcepts": hot,
        "fetchErrors": 0,
        "inferenceErrors": 0,
        "permanentlyInvalidLocations": 0,
        "completed": True,
    }
    return manifest, files, tsv


class ObjectIndexTest(unittest.TestCase):
    def test_tsv_uses_the_vision_twelve_column_object_row(self):
        items = [{
            "locationId": 7,
            "mapId": "92b6110c-b604-47d6-937a-8b5b78453678",
            "sourceLocationId": 126295778,
            "lat": 39.411918644637325,
            "lng": 20.87079841805392,
            "heading": 257.38,
            "pitch": 0,
            "zoom": 0,
            "panoId": "ClPNSqYQCEm2Mow-ZQD6PA",
            "country": "Greece",
            "cameraGeneration": "gen4",
            "roadName": "no road name",
        }]
        line = object_tsv_lines(items)[0]
        self.assertEqual(len(line.split("\t")), 12)
        self.assertTrue(line.endswith("\t0"))
        self.assertIn("ClPNSqYQCEm2Mow-ZQD6PA", line)
        record = global_id_record(69545512)
        self.assertEqual(int.from_bytes(record[:8], "little"), 69545512)
        self.assertEqual(int.from_bytes(record[8:], "little"), 0x72D2D60E)

    def test_command_matches_the_vision_object_indexer(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            calls = []

            def runner(argv, _env, _cwd):
                calls.append(argv)
                if "index-segment" in argv:
                    output = Path(argv[argv.index("--output-dir") + 1])
                    output.mkdir(parents=True, exist_ok=True)
                    (output / "manifest.json").write_text(
                        json.dumps({"completed": True, "indexedLocations": 1}),
                        encoding="utf-8",
                    )
                    return 0, "", ""
                if "--full" in argv:
                    return 0, '{"valid": true, "indexVersion": 4, "full": true}\n', ""
                return 0, '{"valid": true, "indexVersion": 4}\n', ""

            index_object_tsv(
                root / "locations.tsv",
                output_dir=root / "index",
                source_id="community-" + "ab" * 8,
                total=1,
                pace="slow",
                binary=root / "vision-object",
                model_dir=root / "object-hybrid-v1",
                model_cache=root / "coreml-cache",
                runner=runner,
                use_nice=False,
            )
            segment = next(argv for argv in calls if "index-segment" in argv)
            expected = index_segment_arguments(
                model_dir=root / "object-hybrid-v1",
                source_tsv=root / "locations.tsv",
                output_dir=root / "index",
                source_id="community-" + "ab" * 8,
                total=1,
                global_start=0,
                model_cache=root / "coreml-cache",
            )
            self.assertEqual(segment[-len(expected):], expected)
            self.assertIn("--duty-cycle-percent", segment)
            self.assertEqual(segment[segment.index("--duty-cycle-percent") + 1], "25")
            self.assertEqual(segment[segment.index("--checkpoint-every") + 1], "10")
            self.assertTrue(segment[segment.index("--model") + 1].endswith("rfdetr-medium-576-b4.onnx"))
            self.assertTrue(segment[segment.index("--runtime-manifest") + 1].endswith("hybrid-object-runtime.json"))
            self.assertNotIn("object-hybrid-v1/coreml-cache", " ".join(segment))
            self.assertIn("verify-index", calls[-1])
            self.assertIn("--full", calls[-1])

    def test_refuses_the_live_object_index(self):
        with self.assertRaisesRegex(VisionIndexError, "refusing_live_vision_path"):
            write_object_tsv(
                [{
                    "locationId": 1,
                    "lat": 1,
                    "lng": 2,
                    "panoId": "abc",
                }],
                Path("/tmp/object-indexes/locations.tsv"),
            )

    def test_verified_object_index_earns_ten_units(self):
        with tempfile.TemporaryDirectory() as folder:
            service = CommunityService(Path(folder) / "community.sqlite", search_cost=100)
            service.import_synthetic(json.loads(FIXTURE.read_text(encoding="utf-8"))["locations"])
            with sqlite3.connect(service.database) as connection:
                connection.execute("UPDATE locations SET lat=1.25, lon=-2.5, country='Greece' WHERE lane='object'")
            account = service.create_account()["accountId"]
            lease = service.lease(account, "object", 1)
            source = Path(folder) / "locations.tsv"
            manifest, files, tsv = contract_bundle(lease["items"], lease["leaseId"], source)
            outputs = validate_object_index(
                manifest, files, tsv, lease["items"], lease_id=lease["leaseId"]
            )
            self.assertEqual(outputs[0]["model"], OBJECT_INDEX_MODEL)
            forged = json.loads(json.dumps(manifest))
            forged["runtimeIdentity"] = "0" * 64
            with self.assertRaisesRegex(VisionIndexError, "verification_failed"):
                validate_object_index(forged, files, tsv, lease["items"], lease_id=lease["leaseId"])
            wrong_size = json.loads(json.dumps(manifest))
            wrong_size["classes"][0]["recordBytes"] = 16
            with self.assertRaisesRegex(VisionIndexError, "verification_failed"):
                validate_object_index(wrong_size, files, tsv, lease["items"], lease_id=lease["leaseId"])
            result = service.submit(
                account,
                lease["leaseId"],
                outputs,
                object_index=encode_object_submission(manifest, files, tsv),
            )
            self.assertEqual(result["accepted"], 1)
            self.assertEqual(result["unitsEarned"], 10)
            self.assertEqual(service.status(account)["units"], 10)
            other = service.lease(account, "object", 1)
            with self.assertRaisesRegex(ServiceError, "object_index_required"):
                service.submit(account, other["leaseId"], [{
                    "locationId": other["items"][0]["locationId"],
                    "indexText": "not the object index",
                    "outputSha256": "ab" * 32,
                }])

    def test_site_and_worker_use_the_object_indexer(self):
        app = (ROOT / "community/web/app.js").read_text(encoding="utf-8")
        worker = (ROOT / "deploy/cloudflare/src/worker.js").read_text(encoding="utf-8")
        self.assertIn("community.object_index", app)
        self.assertNotIn("community.contribute", app)
        self.assertNotIn("processItem", app)
        contract = (ROOT / "deploy/cloudflare/src/objectIndex.js").read_text(encoding="utf-8")
        self.assertIn(RUNTIME_IDENTITY, contract)
        self.assertIn("vision-object-index-v4", contract)
        self.assertIn("object_index_required", worker)
        self.assertIn("validateObjectIndex", worker)
        self.assertIn("skip=skip", (ROOT / "community/object_index.py").read_text(encoding="utf-8"))
        self.assertIn('"--search"', app)
        self.assertIn("--confidence", app)
        self.assertIn("--import-cutoff", app)
        self.assertIn("--reject-road-names", app)
        self.assertIn("/api/object-indexes", worker)
        self.assertIn("objectIndexes", worker)

    def test_object_prompt_routes_like_vision(self):
        from community.object_index import query_plan

        car = query_plan("car")
        self.assertEqual(car["route"], "common")
        self.assertEqual(car["classIds"], [3])
        nest = query_plan("bird nest")
        self.assertEqual(nest["route"], "hot")
        self.assertEqual(nest["hotConceptId"], 0)
        clock = query_plan("clock")
        self.assertEqual(clock["route"], "hot")
        self.assertEqual(clock["hotConceptId"], 1)
        red = query_plan("red airplane")
        self.assertEqual(red["route"], "semantic")
        self.assertEqual(red["semanticText"], "red airplane")

    def test_object_search_uses_the_vision_binary(self):
        from community.object_index import discover_object_sources, search_object_indexes

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            index = root / "lease"
            index.mkdir()
            (index / "locations.tsv").write_text("header\n", encoding="utf-8")
            (index / "manifest.json").write_text(json.dumps({
                "completed": True,
                "sourceId": "abc",
                "globalStart": 0,
                "indexedLocations": 1,
            }), encoding="utf-8")
            sources = discover_object_sources(root)
            self.assertEqual(sources[0]["indexedLocations"], 1)

            def runner(argv, _env, _cwd):
                out = Path(argv[argv.index("--output") + 1])
                out.write_text(json.dumps({
                    "totalLocations": 1,
                    "queries": [{"hits": [{
                        "similarity": 0.9,
                        "location": {
                            "lat": 1, "lng": 2, "heading": 10, "pitch": 0, "zoom": 1,
                            "panoId": "ClPNSqYQCEm2Mow-ZQD6PA", "country": "Greece",
                        },
                        "object": {
                            "classId": 3, "className": "car", "lane": "common",
                            "heading": 40, "pitch": 5, "zoom": 2,
                            "confidence": 0.4, "supportCount": 2, "bboxArea": 0.02,
                        },
                    }]}],
                }), encoding="utf-8")
                return 0, "", ""

            document = search_object_indexes(
                sources,
                "car",
                output_dir=root / "search",
                confidence="highRecall",
                runner=runner,
                binary=root / "vision-object",
                model_dir=root / "model",
                model_cache=root / "cache",
            )
            hit = document["customCoordinates"][0]
            self.assertEqual(hit["heading"], 40)
            self.assertEqual(hit["pitch"], 5)
            self.assertEqual(hit["extra"]["visionModel"], "RF-DETR Medium 1.10.0")
            self.assertEqual(hit["extra"]["visionObjectClass"], "car")
            self.assertEqual(hit["extra"]["visionObjectLane"], "common")
            self.assertEqual(hit["extra"]["visionObjectClassId"], 3)
            self.assertEqual(hit["extra"]["visionObjectSupport"], 2)
            self.assertEqual(hit["extra"]["visionObjectBoxArea"], 0.02)
            self.assertEqual(hit["extra"]["visionObjectConfidence"], 0.4)
            self.assertEqual(hit["extra"]["visionMinScore"], 0.03)
            self.assertEqual(hit["extra"]["visionQueryMode"], "objects")
            self.assertEqual(hit["extra"]["tags"], ["Greece"])
            spec = json.loads((root / "search" / "object-search-input.json").read_text(encoding="utf-8"))
            self.assertEqual(spec["queries"][0]["minimumConfidence"], 0.03)
            self.assertEqual(spec["queries"][0]["route"], "common")
            self.assertEqual(spec["queries"][0]["rejectRoadNames"], False)
            self.assertNotIn("minimumGlobalLocation", spec["queries"][0])
            self.assertEqual(spec["cpu"], False)
            self.assertTrue(str(spec["modelCache"]).endswith("cache"))

    def test_paid_search_downloads_a_finished_object_index(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = CommunityService(root / "db.sqlite", artifacts=root / "artifacts", search_cost=4, operational=True)
            account = service.create_account()["accountId"]
            lease = "ab" * 16
            stored = root / "artifacts" / "object-index-v4" / lease
            stored.mkdir(parents=True)
            (stored / "manifest.json").write_bytes(b'{"completed":true}')
            (stored / "locations.tsv").write_bytes(b"header\n")
            with sqlite3.connect(service.database) as connection:
                connection.execute("UPDATE accounts SET units=4 WHERE id=?", (account,))
            paid = service.search(
                account,
                None,
                "object-search-1",
                lane="object",
                prompt="car",
                execute="local",
            )
            catalog = service.list_object_indexes(account, paid["searchId"])
            self.assertEqual(catalog["indexes"][0]["prefix"], f"object-index-v4/{lease}/")
            body = service.object_index_bytes(account, paid["searchId"], f"object-index-v4/{lease}/manifest.json")
            self.assertEqual(body, b'{"completed":true}')
            with self.assertRaisesRegex(ServiceError, "unknown_search"):
                service.list_object_indexes(account, "missing-search")
            self.assertGreaterEqual(service.status()["objectIndexes"], 0)

    def test_object_hits_keep_score_then_location_order(self):
        from community.object_index import map_from_object_search

        document = map_from_object_search(
            {
                "totalLocations": 2,
                "queries": [{"name": "cars", "hits": [
                    {
                        "similarity": 0.5,
                        "locationIndex": 2,
                        "location": {"lat": 1, "lng": 2, "panoId": "aaa", "country": "Greece"},
                        "object": {
                            "classId": 3, "className": "car", "lane": "common",
                            "confidence": 0.2, "supportCount": 1, "bboxArea": 0.01,
                            "heading": 1, "pitch": 0, "zoom": 1,
                        },
                    },
                    {
                        "similarity": 0.5,
                        "locationIndex": 1,
                        "location": {"lat": 3, "lng": 4, "panoId": "zzz", "country": "Italy"},
                        "object": {
                            "className": "clock", "lane": "hot",
                            "confidence": 0.3, "supportCount": 4, "bboxArea": 0.02,
                            "heading": 2, "pitch": 0, "zoom": 1,
                        },
                    },
                ]}],
            },
            prompt="car",
            output_name="",
            result_count=200,
            max_per_country=25,
            min_score=0.08,
        )
        rows = document["customCoordinates"]
        self.assertEqual([row["panoId"] for row in rows], ["zzz", "aaa"])
        self.assertEqual(rows[0]["extra"]["visionModel"], "YOLOE-26L 8.4.143")
        self.assertIsNone(rows[0]["extra"]["visionObjectClassId"])
        self.assertEqual(rows[1]["extra"]["visionModel"], "RF-DETR Medium 1.10.0")
        self.assertEqual(rows[0]["extra"]["visionRank"], 1)
        self.assertEqual(rows[1]["extra"]["visionRank"], 2)

    def test_running_indexer_binary_is_the_one_already_indexing(self):
        from community.object_index import running_indexer_executable

        lines = [
            "/tmp/vision-community/bin/vision-object index-segment --output-dir /tmp/out",
            "/opt/VISION/object-runtime-legacy-mixed-20260914/vision-object index-segment --duty 25",
        ]
        found = running_indexer_executable(lines)
        self.assertEqual(found.name, "vision-object")
        self.assertIn("object-runtime-legacy-mixed-20260914", str(found))

    def test_local_app_catalog_keeps_official_sources_and_restamps_ids(self):
        from community.object_index import (
            community_global_start,
            global_id_record,
            publish_local_object_indexes,
        )

        source_id = "community-" + ("ab" * 16)
        start = community_global_start(source_id, 1)
        self.assertEqual(json.loads(json.dumps(start)), start)
        self.assertLess(start, 2**53)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            index = root / "proof" / "index"
            index.mkdir(parents=True)
            (root / "proof" / "locations.tsv").write_text(
                "map\t1\t39.4\t20.8\t257\t0\t0\tpano\tGreece\tgen4\tno road name\t0\n",
                encoding="utf-8",
            )
            (index / "global-location-ids.bin").write_bytes(global_id_record(0))
            (index / "manifest.json").write_text(json.dumps({
                "completed": True,
                "version": 4,
                "sourceId": source_id,
                "globalStart": 0,
                "indexedLocations": 1,
                "modelSha256": "ab" * 32,
                "runtimeIdentity": "cd" * 32,
                "globalIds": {"file": "global-location-ids.bin", "records": 1, "bytes": 12, "recordBytes": 12, "sha256": "11" * 32},
            }), encoding="utf-8")
            registry = root / "current.json"
            registry.write_text(json.dumps({
                "version": 2,
                "feature": "vision-object-index",
                "runtimeIdentity": "cd" * 32,
                "sources": [{
                    "id": "official-segment",
                    "label": "Official",
                    "globalStart": 17300000,
                    "indexedLocations": 10,
                }],
            }), encoding="utf-8")
            registered = publish_local_object_indexes(
                [root / "proof"],
                registry_path=registry,
                destination=root / "staged",
            )
            self.assertEqual(registered, 1)
            catalog = json.loads(registry.read_text(encoding="utf-8"))
            self.assertEqual(catalog["runtimeIdentity"], "cd" * 32)
            self.assertEqual([source["id"] for source in catalog["sources"]], ["official-segment", source_id])
            community = catalog["sources"][1]
            self.assertEqual(community["globalStart"], start)
            self.assertEqual(community["capabilities"], [
                "common", "hot", "semantic", "exactAim", "fullSphere", "explicitGlobalIds",
            ])
            staged_tsv = Path(community["sourceTsv"]).read_text(encoding="utf-8")
            self.assertTrue(staged_tsv.rstrip("\n").endswith("\t" + str(start)))
            overlap = root / "overlap.json"
            overlap.write_text(json.dumps({
                "version": 2,
                "feature": "vision-object-index",
                "sources": [{
                    "id": "official-high",
                    "label": "Official",
                    "globalStart": start,
                    "indexedLocations": 1,
                }],
            }), encoding="utf-8")
            self.assertEqual(publish_local_object_indexes(
                [root / "proof"],
                registry_path=overlap,
                destination=root / "staged-again",
            ), 0)
            self.assertEqual(json.loads(overlap.read_text(encoding="utf-8"))["sources"][0]["id"], "official-high")
