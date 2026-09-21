import tempfile
import unittest
from pathlib import Path

from community.all_locations_full import (
    EXPECTED_ROWS,
    KEY_PREFIX,
    SHARD_ID_START,
    build_catalog,
    camera_for_location,
    catalog_sql,
    country_from_tags,
    decode_metadata,
    format_indexer_line,
    location_is_badcam,
)
from community.catalog import parse_indexer_line


class AllLocationsFullCatalogTest(unittest.TestCase):
    def test_metadata_byte_exposes_generation_and_road_state(self):
        camera, road = decode_metadata(20)
        self.assertEqual(camera, "gen4")
        self.assertEqual(road, "no road name")
        camera, road = decode_metadata(28)
        self.assertEqual(camera, "gen4")
        self.assertEqual(road, "has road name")
        camera, road = decode_metadata(22)
        self.assertEqual(camera, "badcam")
        bitset = bytes([0b0000_0010])
        self.assertTrue(location_is_badcam(bitset, 1))
        self.assertFalse(location_is_badcam(bitset, 0))
        camera, road = camera_for_location(21, 1, bitset)
        self.assertEqual(camera, "badcam")
        self.assertEqual(road, "no road name")

    def test_indexer_line_keeps_saved_pan_and_generation(self):
        line = format_indexer_line(
            location_id=126295778,
            lat=39.411918644637325,
            lng=20.87079841805392,
            heading=257.38,
            pitch=0,
            zoom=0,
            pano_id="ClPNSqYQCEm2Mow-ZQD6PA",
            country="Greece",
            camera_generation="gen4",
            road_name_state="no road name",
        )
        job = parse_indexer_line(line, lane="scene")
        self.assertEqual(job["assetId"], "ClPNSqYQCEm2Mow-ZQD6PA")
        self.assertEqual(job["cameraGeneration"], "gen4")
        self.assertEqual(job["country"], "Greece")
        self.assertAlmostEqual(job["heading"], 257.38, places=5)
        self.assertAlmostEqual(job["pitch"], 0)
        self.assertEqual(job["lon"], job["lon"])
        self.assertIn("\tgen4\t", line)
        self.assertTrue(line.endswith("no road name\n"))

    def test_united_states_tag_becomes_usa(self):
        names = {1: "USA"}
        self.assertEqual(country_from_tags([1], names), "USA")
        line = format_indexer_line(
            location_id=1,
            lat=1,
            lng=2,
            heading=90,
            pitch=3.5,
            zoom=1,
            pano_id="SavedPanPano000000000001",
            country="United States",
            camera_generation="gen3",
            road_name_state="has road name",
        )
        job = parse_indexer_line(line)
        self.assertEqual(job["country"], "USA")
        self.assertEqual(job["cameraGeneration"], "gen3")
        self.assertAlmostEqual(job["heading"], 90)
        self.assertAlmostEqual(job["pitch"], 3.5)

    def test_build_writes_pose_shards_without_embeddings(self):
        line = format_indexer_line(
            location_id=7,
            lat=41.9,
            lng=12.5,
            heading=90,
            pitch=-2,
            zoom=0,
            pano_id="FullCorpusPano0000000001",
            country="Italy",
            camera_generation="trekker",
            road_name_state="has road name",
        )
        with tempfile.TemporaryDirectory() as folder:
            dest = Path(folder) / "out"
            manifest = build_catalog(
                dest,
                lines=[line],
                rows_per_shard=10,
                shard_id_start=SHARD_ID_START,
            )
            self.assertFalse(manifest["embeddingsCopied"])
            self.assertFalse(manifest["imageryCopied"])
            self.assertFalse(manifest["liveSourceRewritten"])
            self.assertEqual(manifest["totalRows"], 1)
            self.assertEqual(manifest["shards"][0]["shardId"], SHARD_ID_START)
            self.assertTrue(manifest["shards"][0]["key"].startswith(KEY_PREFIX))
            text = (dest / manifest["shards"][0]["file"]).read_text(encoding="utf-8")
            self.assertNotIn(".i8", text)
            self.assertIn("FullCorpusPano0000000001", text)
            self.assertIn("trekker", text)
            job = parse_indexer_line(text)
            self.assertAlmostEqual(job["heading"], 90)
            self.assertAlmostEqual(job["pitch"], -2)
            sql = catalog_sql(manifest)
            self.assertIn("INSERT OR IGNORE INTO pose_catalog", sql)
            self.assertIn("'scene'", sql)
            self.assertIn("'object'", sql)
            self.assertEqual(EXPECTED_ROWS, 206_722_636)

    def test_lease_keeps_generation_and_saved_pan_for_four_view(self):
        from community.pano import view_plan
        from community.service import CommunityService

        line = format_indexer_line(
            location_id=126295778,
            lat=39.411918644637325,
            lng=20.87079841805392,
            heading=257.38,
            pitch=8,
            zoom=1,
            pano_id="ClPNSqYQCEm2Mow-ZQD6PA",
            country="Greece",
            camera_generation="gen4",
            road_name_state="no road name",
        )
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            dest = root / "shards"
            manifest = build_catalog(dest, lines=[line], rows_per_shard=10)
            service = CommunityService(root / "db.sqlite", search_cost=4, artifacts=root / "artifacts", operational=True)
            service.append_pose_catalog(manifest, source_dir=dest, lanes=("scene",))
            account = service.create_account()["accountId"]
            item = service.lease(account, "scene", 1)["items"][0]
            self.assertEqual(item["cameraGeneration"], "gen4")
            self.assertEqual(item["country"], "Greece")
            self.assertAlmostEqual(item["heading"], 257.38, places=5)
            self.assertAlmostEqual(item["pitch"], 8)
            plan = view_plan("scene", item["heading"], item["pitch"], item["zoom"])
            self.assertAlmostEqual(plan[0]["yaw"], 257.38, places=5)
            self.assertAlmostEqual(plan[1]["yaw"], 347.38, places=5)
            self.assertTrue(all(view["pitch"] == 8.0 for view in plan[:4]))


if __name__ == "__main__":
    unittest.main()
