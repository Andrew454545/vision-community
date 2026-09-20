import json
import tempfile
import unittest
from pathlib import Path

from community.service import CommunityService
from community.vision_handoff import INDEXER_COLUMNS, export_from_database
from community.worker import ProcessingWorker


ROOT = Path(__file__).resolve().parents[1]
PROTOTYPE = ROOT / "prototype_catalog.json"


class VisionHandoffTest(unittest.TestCase):
    def test_published_locations_export_as_vision_indexer_tsv(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = CommunityService(
                root / "db.sqlite",
                search_cost=4,
                artifacts=root / "artifacts",
                segment_capacity=50,
            )
            catalog = json.loads(PROTOTYPE.read_text(encoding="utf-8"))
            service.import_jobs(catalog)
            account = service.create_account()
            lease = service.lease(account["accountId"], "scene", 4)
            service.submit(account["accountId"], lease["leaseId"], ProcessingWorker().process_lease(lease))
            destination = root / "handoff"
            report = export_from_database(root / "db.sqlite", destination)
            self.assertFalse(report["productionReady"])
            self.assertFalse(report["searchableByVisionApp"])
            self.assertEqual(report["counts"]["scene"], 4)
            self.assertEqual(report["counts"]["object"], 0)
            tsv = (destination / "scene-published.tsv").read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(tsv), 4)
            first = tsv[0].split("\t")
            self.assertEqual(len(first), 11)
            self.assertEqual(len(INDEXER_COLUMNS), 11)
            self.assertEqual(first[0], "vision-community")
            self.assertEqual(first[1], "1")
            self.assertIn("PrototypeBerkeleyCA000001", [line.split("\t")[7] for line in tsv])
            self.assertNotIn("United States", (destination / "scene-published.tsv").read_text(encoding="utf-8"))
            mma = json.loads((destination / "scene-published.json").read_text(encoding="utf-8"))
            self.assertEqual(mma["customCoordinates"][0]["extra"]["tags"], ["USA"])
            self.assertTrue((destination / "manifest.json").is_file())

    def test_indexer_tsv_reimports_as_community_catalog(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = CommunityService(
                root / "db.sqlite",
                search_cost=4,
                artifacts=root / "artifacts",
                segment_capacity=50,
            )
            catalog = json.loads(PROTOTYPE.read_text(encoding="utf-8"))
            service.import_jobs(catalog)
            account = service.create_account()
            lease = service.lease(account["accountId"], "scene", 4)
            service.submit(account["accountId"], lease["leaseId"], ProcessingWorker().process_lease(lease))
            destination = root / "handoff"
            export_from_database(root / "db.sqlite", destination)
            other = CommunityService(
                root / "other.sqlite",
                search_cost=4,
                artifacts=root / "other-artifacts",
            )
            imported = other.import_shard(destination / "scene-published.tsv")
            self.assertEqual(imported["imported"], 4)
            self.assertFalse(imported["skipped"])

    def test_d1_json_export_writes_indexer_tsv(self):
        from community.vision_handoff import export_vision, records_from_d1_document

        document = [
            {
                "results": [
                    {
                        "id": 1,
                        "asset_id": "PrototypeBerkeleyCA000001",
                        "capture": "2019-06",
                        "lane": "scene",
                        "lat": 37.869085,
                        "lon": -122.254775,
                        "heading": 270,
                        "pitch": 0,
                        "zoom": 0,
                        "country": "USA",
                        "camera_generation": "gen4",
                    }
                ]
            }
        ]
        with tempfile.TemporaryDirectory() as folder:
            report = export_vision(
                records_from_d1_document(document),
                Path(folder),
                source="d1:test",
            )
            self.assertEqual(report["counts"]["scene"], 1)
            line = (Path(folder) / "scene-published.tsv").read_text(encoding="utf-8").splitlines()[0]
            self.assertIn("PrototypeBerkeleyCA000001", line)


class AdminD1ExportTest(unittest.TestCase):
    def test_wrangler_log_prefix_is_stripped(self):
        from community.admin import _parse_wrangler_json

        document = _parse_wrangler_json('wrangler 4.0\n[{"results":[{"id":1,"asset_id":"x"}]}]')
        self.assertEqual(document[0]["results"][0]["id"], 1)


if __name__ == "__main__":
    unittest.main()
