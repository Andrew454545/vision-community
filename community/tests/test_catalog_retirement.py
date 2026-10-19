"""Retired allocation cannot re-enter either local assignment path."""
import tempfile
import unittest
from pathlib import Path

from community.all_locations_tail import split_shards
from community.parts import RETIRED_PREFIXES, available_catalog_sql, available_location_sql
from community.service import CommunityService, ServiceError
from community.tests.catalog_fixture import remaining_fixture
from community.tests.test_parts import catalog_line
from community.tests.test_scene_quality import references_from_fixture_lines


class CatalogRetirementTests(unittest.TestCase):
    def make_service(self, root):
        line=catalog_line(1,'aaaaaaaaaaaaaaaaaaaaaa')
        source=root/'input.tsv';source.write_text(line+'\n')
        shards=root/'shards'
        manifest=remaining_fixture(split_shards(source,shards,rows_per_shard=1,row_start=0))
        service=CommunityService(root/'db.sqlite',artifacts=root/'artifacts',operational=True)
        service.append_pose_catalog(manifest,source_dir=shards,lanes=('scene',))
        service.scene_references=references_from_fixture_lines([line])
        account=service.create_account()['accountId']
        return service,account

    def test_retired_catalog_is_refused_even_with_a_cleared_hold(self):
        for prefix in RETIRED_PREFIXES:
            with self.subTest(prefix=prefix),tempfile.TemporaryDirectory() as folder:
                service,account=self.make_service(Path(folder))
                with service._connection() as db:
                    db.execute('UPDATE pose_catalog SET r2_key=?,held=0',(prefix+'absent.tsv',))
                with self.assertRaisesRegex(ServiceError,'no_available_work'):
                    service.lease(account,'scene',1)
                with service._connection() as db:
                    self.assertEqual(db.execute('SELECT next_row FROM pose_catalog').fetchone()[0],0)
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM locations').fetchone()[0],0)
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM leases').fetchone()[0],0)

    def test_pending_fallback_cannot_revive_held_retired_or_missing_catalog(self):
        for change in ('held','retired','missing'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as folder:
                service,account=self.make_service(Path(folder))
                lease=service.lease(account,'scene',1)
                service.release_lease(account,lease['leaseId'])
                with service._connection() as db:
                    if change=='held':db.execute('UPDATE pose_catalog SET held=1')
                    if change=='retired':db.execute('UPDATE pose_catalog SET r2_key=?',(RETIRED_PREFIXES[0]+'old.tsv',))
                    if change=='missing':db.execute('DELETE FROM pose_catalog')
                with self.assertRaisesRegex(ServiceError,'no_available_work'):
                    service.lease(account,'scene',1)
                with service._connection() as db:
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM leases').fetchone()[0],1)
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM ledger').fetchone()[0],0)

    def test_existing_lease_resumes_after_its_catalog_is_retired(self):
        with tempfile.TemporaryDirectory() as folder:
            service,account=self.make_service(Path(folder))
            lease=service.lease(account,'scene',1)
            with service._connection() as db:
                db.execute('UPDATE pose_catalog SET r2_key=?,held=1',(RETIRED_PREFIXES[0]+'old.tsv',))
            resumed=service.lease(account,'scene',1)
            self.assertEqual(resumed['leaseId'],lease['leaseId'])
            self.assertTrue(resumed['resumed'])
            self.assertEqual(resumed['items'],lease['items'])

    def test_aliases_are_internal_identifiers(self):
        for function in (available_catalog_sql,available_location_sql):
            with self.assertRaisesRegex(ValueError,'invalid_sql_alias'):
                function('locations; DROP TABLE accounts')
