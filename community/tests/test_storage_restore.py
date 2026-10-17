from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from community.object_index import global_id_record
from community.object_snapshot import VALIDATOR, cache_directory
from community.search_snapshot import (CONFIRMED_STAGING_RESOURCE, cache_file, digest, encoded)
from community.storage_restore import (StorageRestoreError, catalog_cache_file, check_storage_restore)
from community.tests.test_object_index import contract_bundle
from community.tests.test_search_snapshot import record

ROOT = Path(__file__).resolve().parents[2]


class StorageRestoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repaired = self.root / "repaired"
        self.cache = self.root / "cache"
        self.repaired.mkdir()
        self.cache.mkdir()
        self.database = self.repaired / "restored.sqlite"
        self.scene_key = "four-view-v4/" + "d" * 32 + ".i8"
        self.object_key = "object-index-v4/" + "e" * 32 + "/"
        self.catalog_key = "catalog/all-locations-tail-v1/scene-0000.tsv"
        self.account = "a" * 32
        self.report = {"version": 1, "scope": "offline-privacy-repaired-community-copy",
                       "resource": dict(CONFIRMED_STAGING_RESOURCE), "liveReady": False}
        sql = sqlite3.connect(self.database)
        try:
            sql.executescript((ROOT / "deploy/cloudflare/schema.sql").read_text())
            # Deleted contributors' accepted indexes remain retained. Their
            # old credentials/searches/credits must not be restored.
            sql.execute("INSERT INTO accounts (id,token_hash,units,deleted_at) VALUES (?, ?, 0, 10)",
                        (self.account, "private-credential"))
            for number, value in ((1, 7), (2, 9)):
                output = digest(record(value))
                sql.execute("""INSERT INTO locations
                  (id,asset_id,capture,lane,model,state,contributor_id,output_sha256,lat,lon)
                  VALUES (?,?,'2026-09','scene','input-model','published',?,?,?,20)""",
                            (number, f"synthetic-{number}", self.account, output, number))
                sql.execute("""INSERT INTO published_index
                  (location_id,index_text,output_sha256,published_at,four_view_sha256,four_view_key)
                  VALUES (?, '', ?, 1, ?, ?)""", (number, output, output, self.scene_key))
            items = [{"locationId": 3, "panoId": "synthetic-3", "lat": 3, "lng": 20,
                      "heading": 90, "country": "Italy", "cameraGeneration": "gen4"}]
            manifest, files, source = contract_bundle(items, "e" * 32, self.root / "private-source.tsv")
            folder = cache_directory(self.cache, self.object_key)
            folder.mkdir()
            (folder / "manifest.json").write_bytes(encoded(manifest))
            (folder / "locations.tsv").write_bytes(source)
            for name, raw in files.items():
                (folder / name).write_bytes(raw)
            output = digest(global_id_record(0))
            sql.execute("""INSERT INTO locations
              (id,asset_id,capture,lane,model,state,contributor_id,output_sha256,lat,lon,heading,country,camera_generation)
              VALUES (3,'synthetic-3','2026-09','object','input-model','published',?,?,3,20,90,'Italy','gen4')""",
                        (self.account, output))
            sql.execute("INSERT INTO object_coverage VALUES (3, ?, ?, 1)", (VALIDATOR, "b" * 64))
            sql.execute("""INSERT INTO published_index
              (location_id,index_text,output_sha256,published_at,object_index_sha256,object_index_key)
              VALUES (3, '', ?, 1, ?, ?)""", (output, digest(source), self.object_key))
            catalog = b"synthetic private queue metadata\n"
            sql.execute("""INSERT INTO pose_catalog
              (lane,shard_id,r2_key,row_start,row_count,bytes,sha256) VALUES ('scene',0,?,0,1,?,?)""",
                        (self.catalog_key, len(catalog), digest(catalog)))
            catalog_cache_file(self.cache, self.catalog_key).write_bytes(catalog)
            sql.commit()
        finally:
            sql.close()
        cache_file(self.cache, self.scene_key).write_bytes(record(7) + record(9))
        self.seal_report()

    def seal_report(self):
        self.report["databaseSha256"] = digest(self.database.read_bytes())
        raw = encoded(self.report)
        (self.repaired / "restore-report.json").write_bytes(raw)
        self.report_pin = digest(raw)

    def mutate_database(self, statement, parameters=()):
        with closing(sqlite3.connect(self.database)) as sql, sql:
            sql.execute(statement, parameters)
        self.seal_report()

    def check(self, out="checked", **kwargs):
        return check_storage_restore(self.repaired, self.report_pin, self.cache,
                                     self.root / out, environment=kwargs.pop("environment", "staging"), **kwargs)

    def assert_failed(self, reason=None):
        with self.assertRaises(Exception if reason is None else StorageRestoreError) as raised:
            self.check()
        if reason is not None:
            self.assertEqual(str(raised.exception), reason)
        self.assertFalse((self.root / "checked/storage-report.json").exists())
        raw = (self.root / "checked/failure-report.json").read_bytes()
        self.assertFalse(json.loads(raw)["complete"])
        for private in (self.account, "private-credential", "synthetic-3", str(self.root), self.object_key):
            self.assertNotIn(private.encode(), raw)

    def test_complete_scene_object_and_catalog_copy_preserves_inputs_without_live_approval(self):
        before = self.database.read_bytes()
        report = self.check()
        self.assertTrue(report["complete"])
        self.assertFalse(report["liveReady"])
        self.assertFalse(report["inferenceApproved"])
        self.assertFalse(report["creditRecoveryVerified"])
        self.assertEqual((report["publishedLocations"], report["sceneLocations"], report["objectLocations"],
                          report["sceneArtifacts"], report["objectBundles"], report["catalogShards"]), (3, 2, 1, 1, 1, 1))
        self.assertEqual(before, self.database.read_bytes())
        inventory = (self.root / "checked/checked-files.private.json").read_bytes()
        self.assertEqual(digest(inventory), report["checkedInventorySha256"])
        for private in (self.account, "private-credential", self.scene_key, self.object_key, str(self.root)):
            self.assertNotIn(private.encode(), encoded(report) + inventory)
        with self.assertRaises(FileExistsError):
            self.check()

    def test_wrong_environment_and_mixed_resource_report_fail_closed(self):
        with self.assertRaisesRegex(StorageRestoreError, "invalid_repaired_copy_report"):
            self.check("wrong", environment="production")
        self.report["resource"]["bucket"] = "geonections-images"
        self.seal_report()
        self.assert_failed("invalid_repaired_copy_report")

    @unittest.skipUnless(sys.platform == "win32", "Windows short-path aliases")
    def test_windows_short_folder_names_use_the_same_cache_identity(self):
        import ctypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetShortPathNameW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
        kernel.GetShortPathNameW.restype = ctypes.c_uint32
        def short(path):
            buffer = ctypes.create_unicode_buffer(32768)
            if not kernel.GetShortPathNameW(str(path), buffer, len(buffer)):
                self.skipTest("Filesystem does not supply Windows short-path aliases")
            return Path(buffer.value)
        if short(self.root) == self.root:
            self.skipTest("Filesystem has no distinct short-path alias for this folder")
        result = check_storage_restore(short(self.repaired), self.report_pin, short(self.cache),
                                       short(self.root) / "short-path-check", environment="staging")
        self.assertTrue(result["complete"])
        self.assertEqual(result["publishedLocations"], 3)

    def test_changed_database_pin_preserves_failure(self):
        with closing(sqlite3.connect(self.database)) as sql, sql:
            sql.execute("UPDATE locations SET label='private modified label' WHERE id=1")
        self.assert_failed("database_checksum_mismatch")

    def test_open_database_sidecar_is_refused(self):
        Path(str(self.database) + "-wal").write_bytes(b"private pending journal")
        self.assert_failed("backup_not_closed")

    def test_missing_scene_file_is_a_redacted_failure(self):
        cache_file(self.cache, self.scene_key).unlink()
        self.assert_failed()

    def test_corrupted_scene_record_and_extra_records_are_refused(self):
        path = cache_file(self.cache, self.scene_key)
        path.write_bytes(record(7) + record(8))
        self.assert_failed("scene_artifact_membership_mismatch")
        path.write_bytes(record(7) + record(9) + record(9))
        with self.assertRaisesRegex(StorageRestoreError, "scene_artifact_membership_mismatch"):
            self.check("extra")

    def test_missing_published_row_cannot_be_hidden_by_join(self):
        self.mutate_database("DELETE FROM published_index WHERE location_id=1")
        self.assert_failed("published_location_missing_index")

    def test_distinct_database_digest_columns_cannot_mask_a_mismatch(self):
        self.mutate_database("UPDATE published_index SET output_sha256=? WHERE location_id=1", ("c" * 64,))
        self.assert_failed("invalid_contributed_publication")

    def test_absent_contributor_cannot_be_treated_as_an_index(self):
        self.mutate_database("UPDATE locations SET contributor_id=NULL WHERE id=1")
        self.assert_failed("invalid_contributed_publication")

    def test_duplicate_record_hashes_preserve_record_multiplicity(self):
        self.mutate_database("UPDATE locations SET output_sha256=? WHERE id=2", (digest(record(7)),))
        self.mutate_database("UPDATE published_index SET output_sha256=?,four_view_sha256=? WHERE location_id=2",
                             (digest(record(7)), digest(record(7))))
        cache_file(self.cache, self.scene_key).write_bytes(record(7) + record(7))
        self.assertTrue(self.check()["complete"])

    def test_objects_still_require_generation4_and_complete_coverage_receipts(self):
        self.mutate_database("UPDATE locations SET camera_generation='gen3' WHERE id=3")
        self.assert_failed()
        self.mutate_database("UPDATE locations SET camera_generation='gen4' WHERE id=3")
        self.mutate_database("DELETE FROM object_coverage WHERE location_id=3")
        with self.assertRaises(Exception):
            self.check("receipt-missing")

    def test_corrupted_object_feature_cannot_be_reported_as_restored(self):
        folder = cache_directory(self.cache, self.object_key)
        path = next(folder.glob("*.bin"))
        path.write_bytes(path.read_bytes() + b"corrupt")
        self.assert_failed()

    def test_catalog_checksum_and_ambiguous_keys_are_refused(self):
        catalog_cache_file(self.cache, self.catalog_key).write_bytes(b"different private data")
        self.assert_failed("catalog_checksum_mismatch")
        for key in ("catalog/../escape.tsv", "catalog//escape.tsv", "../escape.tsv", "catalog/a\\b.tsv"):
            with self.assertRaisesRegex(StorageRestoreError, "invalid_catalog_key"):
                catalog_cache_file(self.cache, key)

    def test_missing_catalog_is_not_silently_discarded(self):
        catalog_cache_file(self.cache, self.catalog_key).unlink()
        self.assert_failed()

    def test_linked_cache_file_is_not_followed(self):
        path = cache_file(self.cache, self.scene_key)
        elsewhere = self.root / "elsewhere.i8"
        elsewhere.write_bytes(path.read_bytes())
        path.unlink()
        try:
            path.symlink_to(elsewhere)
        except (OSError, NotImplementedError):
            self.skipTest("Filesystem does not permit unprivileged symlinks")
        self.assert_failed()

    def test_bounded_storage_checks_cannot_seal_an_oversized_attempt(self):
        with patch("community.storage_restore.MAX_TOTAL_BYTES", 1):
            self.assert_failed("storage_check_limit_exceeded")

    def test_output_cannot_be_created_inside_a_pinned_input_directory(self):
        with self.assertRaisesRegex(StorageRestoreError, "output_overlaps_input"):
            check_storage_restore(self.repaired, self.report_pin, self.cache,
                                  self.cache / "out", environment="staging")

    def test_deleted_searches_cannot_be_restored(self):
        self.mutate_database("INSERT INTO searches VALUES ('private',?,'key','private search','{}')", (self.account,))
        self.assert_failed("invalid_deleted_account")

    def test_changed_cache_during_object_validation_cannot_seal_pass(self):
        from community.storage_restore import load_bundle
        def change_after_read(*args):
            result = load_bundle(*args)
            cache_file(self.cache, self.scene_key).write_bytes(record(7) + record(8))
            return result
        with patch("community.storage_restore.load_bundle", side_effect=change_after_read):
            self.assert_failed("artifact_changed_during_check")

    def test_interruption_preserves_a_redacted_failure_and_no_completion(self):
        with patch("community.storage_restore.load_bundle", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.check()
        self.assertFalse((self.root / "checked/storage-report.json").exists())
        self.assertEqual(json.loads((self.root / "checked/failure-report.json").read_bytes()),
                         {"complete": False, "liveReady": False, "error": "interrupted"})

    def test_deleted_credentials_or_searches_cannot_be_restored(self):
        self.mutate_database("UPDATE accounts SET recovery_hash='private recovery key' WHERE id=?", (self.account,))
        self.assert_failed("invalid_deleted_account")

    def test_cli_failure_emits_no_path_or_provider_secrets(self):
        completed = subprocess.run([sys.executable, "-B", "-m", "community.storage_restore",
                                    "--repaired-dir", str(self.repaired), "--report-sha256", "f" * 64,
                                    "--artifact-cache", str(self.cache), "--out", str(self.root / "cli"),
                                    "--environment", "staging"], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(completed.returncode, 1)
        self.assertNotIn(str(self.root), completed.stdout + completed.stderr)
        self.assertFalse(json.loads(completed.stdout)["complete"])


if __name__ == "__main__":
    unittest.main()
