import json
import tempfile
import unittest
from pathlib import Path

from community.catalog import parse_indexer_line
from community.indexed_local import (
    EXPECTED_ROWS,
    KEY_PREFIX,
    SHARD_ID_START,
    build_catalog,
    catalog_sql,
    normalize_indexer_line,
)


class IndexedLocalCatalogTest(unittest.TestCase):
    def test_nine_column_legacy_rows_become_indexer_tsv(self):
        line = normalize_indexer_line(
            "-1\t42\t41.9\t12.5\t90\t0\t0\tCommunityPano000000000001\tUnited States\n"
        )
        self.assertIsNotNone(line)
        job = parse_indexer_line(line, lane="scene")
        self.assertEqual(job["assetId"], "CommunityPano000000000001")
        self.assertEqual(job["country"], "USA")
        self.assertEqual(job["lat"], 41.9)

    def test_eleven_column_rows_keep_camera_generation(self):
        line = normalize_indexer_line(
            "map\t7\t1\t2\t90\t0\t0\tCommunityPano000000000002\tItaly\tgen4\tno road name\n"
        )
        job = parse_indexer_line(line, lane="scene")
        self.assertEqual(job["cameraGeneration"], "gen4")
        self.assertEqual(job["country"], "Italy")

    def test_build_writes_pose_shards_without_embeddings(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            nine = root / "legacy.tsv"
            eleven = root / "one-view.tsv"
            nine.write_text(
                "-1\t1\t10\t20\t0\t0\t0\tLegacyPano000000000001\tJapan\n",
                encoding="utf-8",
            )
            eleven.write_text(
                "map\t2\t11\t21\t90\t0\t0\tOneViewPano00000000002\tItaly\tgen3\tno road name\n",
                encoding="utf-8",
            )
            dest = root / "out"
            manifest = build_catalog(dest, sources=[nine, eleven])
            self.assertFalse(manifest["embeddingsCopied"])
            self.assertEqual(manifest["sourceFiles"], ["legacy-four-view", "one-view-checkpoint", "four-view-no-road-sealed"])
            self.assertEqual(manifest["totalRows"], 2)
            self.assertEqual(manifest["shards"][0]["shardId"], SHARD_ID_START)
            self.assertTrue(manifest["shards"][0]["key"].startswith(KEY_PREFIX))
            shard = dest / manifest["shards"][0]["file"]
            text = shard.read_text(encoding="utf-8")
            self.assertNotIn(".i8", text)
            self.assertIn("LegacyPano000000000001", text)
            self.assertIn("OneViewPano00000000002", text)
            sql = catalog_sql(manifest)
            self.assertIn("INSERT OR IGNORE INTO pose_catalog", sql)
            self.assertIn("'scene'", sql)
            self.assertIn("'object'", sql)
            self.assertEqual(EXPECTED_ROWS, 20_955_444)


if __name__ == "__main__":
    unittest.main()
