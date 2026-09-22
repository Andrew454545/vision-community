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
