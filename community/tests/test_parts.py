import tempfile
import unittest
from pathlib import Path

from community.all_locations_full import KEY_PREFIX as FULL_PREFIX
from community.all_locations_full import format_indexer_line, build_catalog
from community.all_locations_tail import split_shards
from community.parts import family_for_key, parse_part
from community.service import CommunityService, ServiceError


def write_lines(path: Path, rows: list[str]) -> None:
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def catalog_line(index: int, pano: str, heading: float = 90, country: str = "Italy", generation: str = "gen4") -> str:
    return format_indexer_line(
        location_id=index,
        lat=10 + index / 100,
        lng=20,
        heading=heading,
        pitch=0,
        zoom=0,
        pano_id=pano,
        country=country,
        camera_generation=generation,
        road_name_state="no road name",
    ).rstrip("\n")


class CorpusPartHelpersTest(unittest.TestCase):
    def test_tail_is_preferred_over_full_corpus(self):
        self.assertEqual(family_for_key("catalog/all-locations-tail-v1/shard-19.tsv"), "new-places")
        self.assertEqual(family_for_key("catalog/all-locations-full-v1/shard--20000.tsv"), "whole-map")
        self.assertEqual(parse_part("12"), 12)
        with self.assertRaises(ValueError):
            parse_part(0)


class ExclusiveCatalogPartsTest(unittest.TestCase):
    def test_two_accounts_keep_separate_shards(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "tail.tsv"
            write_lines(
                source,
                [
                    catalog_line(1, "PartPanoAAAAAAAAAAAAAA"),
                    catalog_line(2, "PartPanoBBBBBBBBBBBBBB"),
                    catalog_line(3, "PartPanoCCCCCCCCCCCCCC"),
                    catalog_line(4, "PartPanoDDDDDDDDDDDDDD"),
                ],
            )
            shards = root / "shards"
            manifest = split_shards(source, shards, rows_per_shard=2, row_start=0)
            service = CommunityService(root / "db.sqlite", search_cost=4, artifacts=root / "artifacts", operational=True)
            service.append_pose_catalog(manifest, source_dir=shards, lanes=("scene",))
            first = service.create_account()["accountId"]
            second = service.create_account()["accountId"]
            a = service.lease(first, "scene", 1)
            b = service.lease(second, "scene", 1)
            self.assertEqual(a["work"]["part"], 1)
            self.assertEqual(b["work"]["part"], 2)
            self.assertNotEqual(a["items"][0]["assetId"], b["items"][0]["assetId"])
            self.assertIn("Other people have different batches", a["work"]["summary"])
            status = service.status(first)
            self.assertEqual(status["work"]["part"], 1)
            self.assertEqual(status["workByLane"]["scene"]["part"], 1)
            self.assertIsNone(status["workByLane"]["object"])
            service.release_lease(second, b["leaseId"])
            with self.assertRaisesRegex(ServiceError, "part_taken"):
                service.lease(second, "scene", 1, part=1)

    def test_requested_part_and_saved_pan_stay_on_that_batch(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            dest = root / "shards"
            line = catalog_line(9, "ClPNSqYQCEm2Mow-ZQD6PA", heading=257.38, country="Greece")
            manifest = build_catalog(dest, lines=[line + "\n"], rows_per_shard=10)
            self.assertTrue(manifest["shards"][0]["key"].startswith(FULL_PREFIX))
            service = CommunityService(root / "db.sqlite", search_cost=4, artifacts=root / "artifacts", operational=True)
            service.append_pose_catalog(manifest, source_dir=dest, lanes=("scene",))
            account = service.create_account()["accountId"]
            lease = service.lease(account, "scene", 1, part=1)
            item = lease["items"][0]
            self.assertEqual(lease["work"]["family"], "whole-map")
            self.assertEqual(item["cameraGeneration"], "gen4")
            self.assertAlmostEqual(item["heading"], 257.38, places=5)
            self.assertEqual(item["country"], "Greece")


class ObjectAndSceneProcessingTest(unittest.TestCase):
    def test_object_and_scene_keep_separate_batches(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "tail.tsv"
            write_lines(
                source,
                [
                    catalog_line(1, "PartPanoAAAAAAAAAAAAAA"),
                    catalog_line(2, "PartPanoBBBBBBBBBBBBBB"),
                ],
            )
            shards = root / "shards"
            manifest = split_shards(source, shards, rows_per_shard=2, row_start=0)
            service = CommunityService(root / "db.sqlite", search_cost=4, artifacts=root / "artifacts", operational=True)
            service.append_pose_catalog(manifest, source_dir=shards, lanes=("scene", "object"))
            account = service.create_account()["accountId"]
            scene = service.lease(account, "scene", 1)
            objects = service.lease(account, "object", 1)
            self.assertEqual(scene["items"][0]["lane"], "scene")
            self.assertEqual(objects["items"][0]["lane"], "object")
            self.assertEqual(scene["items"][0]["assetId"], objects["items"][0]["assetId"])
            self.assertIn("same places", scene["work"]["summary"])
            self.assertIn("same objects", objects["work"]["summary"])
            status = service.status(account)
            self.assertEqual(status["workByLane"]["scene"]["lane"], "scene")
            self.assertEqual(status["workByLane"]["object"]["lane"], "object")


if __name__ == "__main__":
    unittest.main()
