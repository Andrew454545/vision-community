import json
import tempfile
import unittest
from pathlib import Path

from community.all_locations_tail import (
    copy_tail,
    copy_tail_window,
    insert_sql,
    jobs_from_tail,
    pose_catalog_insert_sql,
    reservation,
    split_shards,
    sql_literal,
    write_sql_files,
)


def _tsv(rows: list[str]) -> str:
    lines = []
    for index, pano in enumerate(rows):
        lines.append(
            "\t".join(
                (
                    "map",
                    str(index),
                    "1.0",
                    "2.0",
                    "90",
                    "0",
                    "0",
                    pano,
                    "Italy",
                    "gen4",
                    "no road name",
                )
            )
        )
    return "\n".join(lines) + "\n"


class AllLocationsTailTest(unittest.TestCase):
    def test_copy_tail_keeps_source_and_last_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.tsv"
            dest = Path(folder) / "tail.tsv"
            source.write_text(_tsv(["FrontPano000000000001", "MidPano00000000000002", "TailPano000000000003", "TailPano000000000004"]))
            before = source.read_bytes()
            copied = copy_tail(source, dest, 2)
            self.assertEqual(source.read_bytes(), before)
            self.assertEqual(copied["rows"], 2)
            self.assertEqual(copied["firstPanoId"], "TailPano000000000003")
            self.assertEqual(copied["lastPanoId"], "TailPano000000000004")
            window = copy_tail_window(source, Path(folder) / "window.tsv", tail_rows=3, skip_last=1)
            self.assertEqual(source.read_bytes(), before)
            self.assertEqual(window["rows"], 2)
            self.assertEqual(window["firstPanoId"], "MidPano00000000000002")
            self.assertEqual(window["lastPanoId"], "TailPano000000000003")
            jobs = list(jobs_from_tail(dest))
            self.assertEqual([job["assetId"] for job in jobs], ["TailPano000000000003", "TailPano000000000004"])
            self.assertEqual(jobs[0]["lane"], "scene")

    def test_reservation_rejects_overlap_with_local_cursor(self):
        tail = {
            "path": "/tmp/tail.tsv",
            "rows": 10,
            "bytes": 100,
            "sha256": "abc",
            "firstPanoId": "A",
            "lastPanoId": "B",
        }
        with self.assertRaises(ValueError):
            reservation(
                source_tsv=Path("/tmp/source.tsv"),
                source_rows=100,
                source_bytes=1000,
                local_next_location_index=95,
                tail=tail,
            )
        document = reservation(
            source_tsv=Path("/tmp/source.tsv"),
            source_rows=100,
            source_bytes=1000,
            local_next_location_index=20,
            tail=tail,
        )
        self.assertEqual(document["reservedFromLocationIndex"], 90)
        self.assertFalse(document["liveSourceRewritten"])

    def test_insert_sql_skips_known_panos_and_escapes(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "tail.tsv"
            source.write_text(_tsv(["KeepPano000000000001", "SkipPano000000000001", "O'BrienPano00000001"]))
            jobs = list(jobs_from_tail(source, skip_asset_ids={"SkipPano000000000001"}))
            statements = insert_sql(jobs, values_per_statement=10)
            self.assertEqual(len(statements), 1)
            self.assertIn("KeepPano000000000001", statements[0])
            self.assertNotIn("SkipPano000000000001", statements[0])
            self.assertIn("O''BrienPano00000001", statements[0])
            files = write_sql_files(jobs, Path(folder) / "sql", rows_per_file=1)
            self.assertEqual(len(files), 2)
        self.assertEqual(sql_literal("a'b"), "'a''b'")

    def test_split_shards_does_not_rewrite_source(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.tsv"
            dest = Path(folder) / "shards"
            panos = [f"TailPano{index:016d}" for index in range(5)]
            source.write_text(_tsv(panos))
            before = source.read_bytes()
            manifest = split_shards(source, dest, rows_per_shard=2, limit=4, row_start=100)
            self.assertEqual(source.read_bytes(), before)
            self.assertEqual(manifest["totalRows"], 4)
            self.assertEqual(len(manifest["shards"]), 2)
            self.assertEqual(manifest["shards"][0]["rows"], 2)
            self.assertEqual(manifest["shards"][1]["rows"], 2)
            self.assertEqual(manifest["shards"][0]["rowStart"], 100)
            self.assertEqual(manifest["shards"][1]["rowStart"], 102)
            later = split_shards(source, Path(folder) / "more", rows_per_shard=2, shard_id_start=19, limit=2)
            self.assertEqual(later["shards"][0]["shardId"], 19)
            self.assertEqual(later["shards"][0]["file"], "shard-00019.tsv")
            sql = pose_catalog_insert_sql(later, lanes=("scene", "object"))
            self.assertIn("'scene'", sql)
            self.assertIn("'object'", sql)
            self.assertIn("shard-00019.tsv", sql)
            self.assertTrue((dest / "manifest.json").is_file())


if __name__ == "__main__":
    unittest.main()
