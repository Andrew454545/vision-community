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


if __name__ == "__main__":
    unittest.main()
