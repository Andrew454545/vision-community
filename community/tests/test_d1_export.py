from contextlib import closing
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from community import d1_export as export
from community.search_snapshot import CONFIRMED_STAGING_RESOURCE, digest, encoded

ROOT = Path(__file__).resolve().parents[2]
PRIVATE = "private café;\n'prompt\0reply Ω"


class D1ExportTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source.private.sql'
        self.provenance = self.root / 'provenance.private.json'
        self.out = self.root / 'converted'
        self.schema = (ROOT / 'deploy/cloudflare/fixtures/legacy-20261009.sql').read_text()
        # Preserve text after NUL through hex, plus exact 64-bit sequence values.
        self.dump = self.schema + """
BEGIN TRANSACTION;
INSERT INTO accounts(id,token_hash,recovery_hash,units) VALUES('owner','private-token','private-code',12);
INSERT INTO locations(id,asset_id,capture,lane,model,state,contributor_id) VALUES(1,'private-pano','c','scene','m','published','owner');
INSERT INTO leases(id,account_id,lane,state,expires_at) VALUES('unfinished','owner','scene','active',2000);
INSERT INTO lease_items VALUES('unfinished',1);
INSERT INTO published_index(location_id,index_text,output_sha256,published_at,embedding) VALUES(1,'','hash',100,X'00FF27');
INSERT INTO ledger(account_id,units,reason,reference) VALUES('owner',12,'verified_work','lease:earned');
INSERT INTO searches VALUES('paid','owner','private-paid-key',CAST(X'%s' AS TEXT),X'00FF27');
INSERT INTO locations(id,asset_id,capture,lane,model) VALUES(9007199254740993,'high-water','c','scene','m');
COMMIT;
CREATE TRIGGER retain_fence BEFORE UPDATE ON accounts
BEGIN SELECT RAISE(ABORT,'retained; fence'); END;
-- trailing comment; contains SQL-looking text: ATTACH 'not-a-file'
""" % PRIVATE.encode().hex()
        # A dump's sqlite_sequence restoration happens after its row inserts.
        self.dump += "DELETE FROM sqlite_sequence; INSERT INTO sqlite_sequence VALUES('locations',9007199254740993);"
        self.seal()

    def seal(self, dump=None, **provenance):
        raw = (self.dump if dump is None else dump).encode()
        self.source.write_bytes(raw)
        self.pin = digest(raw)
        document = {'version': 1, 'scope': 'private-cloudflare-d1-export',
                    'resource': dict(CONFIRMED_STAGING_RESOURCE), 'completeSchemaAndData': True,
                    'bookmark': 'independent-provider-bookmark', 'sha256': self.pin, 'bytes': len(raw)} | provenance
        raw = encoded(document)
        self.provenance.write_bytes(raw)
        self.provenance_pin = digest(raw)

    def convert(self, **options):
        return export.convert_export(self.source, self.pin, self.provenance, self.provenance_pin,
                                     self.out, environment='staging', **options)

    def failed(self, code=None):
        before = self.source.read_bytes(), self.provenance.read_bytes()
        with self.assertRaisesRegex(export.ExportError, code or '.'):
            self.convert()
        self.assertEqual(before, (self.source.read_bytes(), self.provenance.read_bytes()))
        self.assertFalse((self.out / 'conversion-report.private.json').exists())
        raw = (self.out / 'failure-report.private.json').read_bytes()
        self.assertFalse(json.loads(raw)['complete'])
        for private in ('private-token', 'private-code', 'private-pano', 'private-paid-key', PRIVATE, str(self.root)):
            self.assertNotIn(private, raw.decode())

    def test_complete_export_preserves_paid_bytes_blobs_constraints_triggers_and_large_integer_ids(self):
        before = self.source.read_bytes()
        report = self.convert()
        self.assertTrue(report['complete'])
        self.assertFalse(report['liveReady'])
        self.assertFalse(report['providerProvenanceVerified'])
        self.assertFalse(report['cloudResourcesAccessed'])
        self.assertEqual(report['resource'], CONFIRMED_STAGING_RESOURCE)
        self.assertEqual(before, self.source.read_bytes())
        self.assertEqual(before, (self.out / 'input.private.sql').read_bytes())
        self.assertEqual(report['databaseSha256'], digest((self.out / 'input.sqlite').read_bytes()))
        with closing(sqlite3.connect(self.out / 'input.sqlite')) as sql:
            sql.execute('PRAGMA foreign_keys=ON')
            self.assertEqual(sql.execute('SELECT query,result_json FROM searches').fetchone(), (PRIVATE, b'\0\xff\x27'))
            self.assertEqual(sql.execute('SELECT seq FROM sqlite_sequence WHERE name="locations"').fetchone()[0], 9007199254740993)
            self.assertEqual(sql.execute('SELECT state FROM leases').fetchone()[0], 'active')
            self.assertEqual(sql.execute('SELECT units,recovery_hash FROM accounts').fetchone(), (12, 'private-code'))
            with self.assertRaisesRegex(sqlite3.DatabaseError, 'retained; fence'):
                sql.execute("UPDATE accounts SET units=13")
            with self.assertRaises(sqlite3.IntegrityError):
                sql.execute("INSERT INTO lease_items VALUES('missing',1)")

    def test_parser_preserves_quotes_comments_same_line_statements_and_trigger_bodies(self):
        raw = b"-- ;\nSELECT ';it''s;'; /* ; */ SELECT 2; CREATE TRIGGER x AFTER INSERT ON a BEGIN SELECT 1; SELECT 2; END; -- tail;"
        actual = list(export.statements(io.BytesIO(raw), lambda: None))
        self.assertEqual(len(actual), 3)
        self.assertIn('SELECT 1; SELECT 2; END;', actual[-1])

    def test_unicode_crossing_a_stream_chunk_is_preserved(self):
        raw = (' ' * 65530 + "SELECT 'Ω中';").encode()
        self.assertEqual(list(export.statements(io.BytesIO(raw), lambda: None)), [raw.decode()])

    def test_export_without_wrappers_uses_one_owned_transaction_for_all_rows(self):
        self.seal(self.dump.replace('BEGIN TRANSACTION;', '').replace('COMMIT;', ''))
        seen = []
        connect = sqlite3.connect
        def tracked(*args, **kwargs):
            sql = connect(*args, **kwargs)
            sql.set_trace_callback(lambda query: seen.append(query.split()[0].upper()))
            return sql
        with patch.object(export.sqlite3, 'connect', side_effect=tracked):
            self.convert()
        self.assertEqual(seen.count('BEGIN'), 1)
        self.assertEqual(seen.count('COMMIT'), 1)

    def test_invalid_transaction_controls_are_refused(self):
        for index, tail in enumerate(('COMMIT;', 'BEGIN; BEGIN;', 'ROLLBACK;', 'SAVEPOINT bypass;')):
            with self.subTest(tail=tail):
                self.out = self.root / ('transaction-' + str(index))
                self.seal(self.dump + '\n' + tail)
                self.failed()

    def test_wrong_export_and_provenance_pins_fail_without_a_completed_database(self):
        self.pin = '0' * 64
        self.failed('export_provenance_pin_mismatch')

    def test_wrong_provenance_checksum_is_rejected(self):
        self.provenance_pin = '0' * 64
        self.failed()

    def test_mixed_resource_or_partial_export_authority_is_refused(self):
        for index, change in enumerate(({'resource': dict(CONFIRMED_STAGING_RESOURCE, bucket='other')},
                                       {'completeSchemaAndData': False}, {'bytes': True},
                                       {'bookmark': ''}, {'version': True})):
            with self.subTest(change=change):
                self.out = self.root / ('failed-' + str(index))
                self.seal(**change)
                self.failed('invalid_export_provenance')

    def test_export_size_and_statement_bounds_are_enforced(self):
        with patch.object(export, 'MAX_EXPORT', 10):
            self.failed('invalid_export_provenance')
        self.out = self.root / 'statement-bound'
        with patch.object(export, 'MAX_STATEMENT', 80):
            self.failed()

    def test_truncated_statement_and_unclosed_transaction_are_refused(self):
        for index, tail in enumerate(("INSERT INTO accounts VALUES('truncated", 'BEGIN TRANSACTION;')):
            with self.subTest(tail=tail):
                self.out = self.root / ('truncated-' + str(index))
                self.seal(self.dump + '\n' + tail)
                self.failed('export_statement_incomplete' if index == 0 else 'export_transaction_incomplete')

    def test_forbidden_sql_cannot_write_another_file_or_rewrite_restored_history(self):
        target = self.root / 'unrelated.sqlite'
        attacks = ["ATTACH DATABASE '%s' AS extra;" % str(target).replace("'", "''"),
                   'PRAGMA writable_schema=ON;', 'PRAGMA trusted_schema=ON;',
                   "SELECT load_extension('not-a-library');", "VACUUM INTO '%s';" % target.as_posix(),
                   'CREATE VIRTUAL TABLE evil USING fts5(value);',
                   'CREATE TABLE unknown(value);', 'DROP TABLE searches;',
                   "UPDATE accounts SET token_hash='changed';",
                   "CREATE TRIGGER rewrite AFTER INSERT ON accounts BEGIN UPDATE searches SET query='changed'; END; INSERT INTO accounts(id,token_hash) VALUES('second','token');"]
        for index, tail in enumerate(attacks):
            with self.subTest(tail=tail):
                self.out = self.root / ('attack-' + str(index))
                self.seal(self.dump + '\n' + tail)
                self.failed()
                self.assertFalse(target.exists())

    def test_dangling_foreign_keys_are_refused(self):
        self.seal(self.dump + "\nINSERT INTO lease_items VALUES('missing',1);")
        self.failed('export_integrity_failure')

    def test_missing_application_tables_are_refused(self):
        self.seal('CREATE TABLE accounts(id TEXT);')
        self.failed('unsupported_export_schema')

    def test_existing_output_is_preserved(self):
        self.convert()
        receipt = (self.out / 'conversion-report.private.json').read_bytes()
        with self.assertRaises(FileExistsError):
            self.convert()
        self.assertEqual(receipt, (self.out / 'conversion-report.private.json').read_bytes())

    def test_duplicate_provenance_keys_and_invalid_utf8_are_refused(self):
        raw = self.provenance.read_bytes().replace(b'"version":1', b'"version":1,"version":1')
        self.provenance.write_bytes(raw)
        self.provenance_pin = digest(raw)
        self.failed()
        self.out = self.root / 'invalid-utf8'
        self.seal()
        raw = self.source.read_bytes() + b'\xff'
        self.source.write_bytes(raw)
        self.pin = digest(raw)
        doc = json.loads(self.provenance.read_bytes()) | {'sha256': self.pin, 'bytes': len(raw)}
        self.provenance.write_bytes(encoded(doc))
        self.provenance_pin = digest(self.provenance.read_bytes())
        self.failed()

    def test_timeout_preserves_a_redacted_failure(self):
        with patch.object(export, 'MAX_SECONDS', 0):
            self.failed('export_conversion_timeout')


if __name__ == '__main__':
    unittest.main()
