"""Convert a pinned private D1 SQL export for offline recovery rehearsals.

No provider access or live writes. The operator must independently authenticate
the export and its provenance; a checksum does not establish backup authority.
Partial inputs, databases and redacted failures are retained on failure.
"""
from __future__ import annotations

import argparse
import codecs
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time

from .native_scene_search import plain_path, strict_json
from .search_snapshot import HEX, encoded, file_digest, pinned_read, resource_for_environment, write_file

MAX_EXPORT = 512 * 1024**2
MAX_STATEMENT = 16 * 1024**2
MAX_SECONDS = 300
TABLES = frozenset((
    'accounts', 'locations', 'leases', 'lease_items', 'published_index', 'ledger',
    'searches', 'pose_catalog', 'index_shards', 'object_coverage',
    'scene_qualifications', 'scene_candidates', 'account_artifact_writes',
    'account_deletion_receipts', 'account_cleanup', 'account_deletion_archives',
    'community_schema_revision', 'd1_migrations',
))
REQUIRED = frozenset(('accounts', 'locations', 'leases', 'lease_items',
                      'published_index', 'ledger', 'searches', 'pose_catalog', 'index_shards'))
SYSTEM = frozenset(('sqlite_master', 'sqlite_schema', 'sqlite_sequence'))
FUNCTIONS = frozenset(('hex', 'quote', 'char', 'typeof', 'length', 'raise',
                       'replace', 'lower', 'strftime', 'ifnull', 'coalesce'))


class ExportError(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise ExportError(code)


def authorize(action, first, second, database, trigger):
    """SQLite's parser enforces the sandbox, including nested statements.

    A dump can create only known application tables/indexes/triggers and insert
    their contents. It cannot attach another file, load code, change SQLite's
    safety settings, create virtual tables, or run a trigger that rewrites data.
    """
    if database not in (None, 'main'):
        return sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_PRAGMA:
        return sqlite3.SQLITE_OK if first in ('foreign_keys', 'defer_foreign_keys') \
            and second is not None and second.lower() in ('0', '1', 'on', 'off', 'true', 'false') else sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_FUNCTION:
        return sqlite3.SQLITE_OK if second in FUNCTIONS else sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_CREATE_TABLE:
        return sqlite3.SQLITE_OK if first in TABLES or first == 'sqlite_sequence' else sqlite3.SQLITE_DENY
    if action in (sqlite3.SQLITE_CREATE_INDEX, sqlite3.SQLITE_CREATE_TRIGGER):
        return sqlite3.SQLITE_OK if second in TABLES else sqlite3.SQLITE_DENY
    if action in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_READ):
        return sqlite3.SQLITE_OK if first in TABLES | SYSTEM and not (trigger and action == sqlite3.SQLITE_INSERT) else sqlite3.SQLITE_DENY
    if action in (sqlite3.SQLITE_DELETE, sqlite3.SQLITE_UPDATE):
        return sqlite3.SQLITE_OK if first in SYSTEM and not trigger else sqlite3.SQLITE_DENY
    if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_REINDEX):
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def provenance_document(path, pin, environment):
    document = strict_json(pinned_read(plain_path(path), pin, 65536))
    require(isinstance(document, dict) and type(document.get('version')) is int and document['version'] == 1
            and document.get('scope') == 'private-cloudflare-d1-export'
            and document.get('resource') == resource_for_environment(environment)
            and document.get('completeSchemaAndData') is True
            and isinstance(document.get('bookmark'), str) and 0 < len(document['bookmark']) <= 256
            and all(32 <= ord(c) <= 126 for c in document['bookmark'])
            and type(document.get('bytes')) is int and 0 < document['bytes'] <= MAX_EXPORT
            and isinstance(document.get('sha256'), str) and HEX.fullmatch(document['sha256']),
            'invalid_export_provenance')
    return document


def statements(stream, deadline):
    decoder = codecs.getincrementaldecoder('utf-8-sig')(errors='strict')
    parts, size = [], 0
    while True:
        raw = stream.read(65536)
        text = decoder.decode(raw, final=not raw)
        offset = 0
        while offset < len(text):
            deadline()
            semicolon = text.find(';', offset)
            end = len(text) if semicolon < 0 else semicolon + 1
            fragment = text[offset:end]
            parts.append(fragment)
            size += len(fragment.encode('utf-8'))
            require(size <= MAX_STATEMENT, 'export_statement_too_large')
            if semicolon >= 0:
                statement = ''.join(parts)
                # SQLite understands quotes, comments and a trigger's BEGIN/END.
                if sqlite3.complete_statement(statement):
                    yield statement
                    parts, size = [], 0
            offset = end
        if not raw:
            break
    tail = ''.join(parts)
    require(re.fullmatch(r'(?:\s|--[^\r\n]*(?:\r?\n|$)|/\*[\s\S]*?\*/)*', tail) is not None,
            'export_statement_incomplete')


def transaction_boundary(statement):
    # Only complete, ordinary dump BEGIN/COMMIT wrappers are handled here. All
    # other transaction controls (including SAVEPOINT) are denied by SQLite.
    leading = re.match(r'(?:\s|--[^\r\n]*(?:\r?\n|$)|/\*[\s\S]*?\*/)*', statement)
    value = statement[leading.end():].strip()
    if re.fullmatch(r'BEGIN(?:\s+TRANSACTION)?\s*;', value, re.IGNORECASE):
        return 'begin'
    if re.fullmatch(r'COMMIT(?:\s+TRANSACTION)?\s*;', value, re.IGNORECASE):
        return 'commit'
    return None


def convert_export(source, source_sha256, provenance, provenance_sha256, out, *, environment='production'):
    destination = Path(out).absolute()
    plain_path(destination.parent, directory=True)
    destination.mkdir(mode=0o700, exist_ok=False)
    plain_path(destination, directory=True)
    started = time.monotonic()
    sql = None

    def deadline():
        require(time.monotonic() - started < MAX_SECONDS, 'export_conversion_timeout')

    try:
        require(isinstance(source_sha256, str) and HEX.fullmatch(source_sha256), 'invalid_checksum_pin')
        document = provenance_document(provenance, provenance_sha256, environment)
        require(document['sha256'] == source_sha256, 'export_provenance_pin_mismatch')
        source = plain_path(source)
        retained = destination / 'input.private.sql'
        total, checksum = 0, hashlib.sha256()
        with source.open('rb') as stream, retained.open('xb') as output:
            for raw in iter(lambda: stream.read(1024**2), b''):
                deadline()
                total += len(raw)
                require(total <= MAX_EXPORT, 'export_too_large')
                checksum.update(raw)
                output.write(raw)
        require(total == document['bytes'] and checksum.hexdigest() == source_sha256,
                'export_checksum_mismatch')
        database = destination / 'input.sqlite'
        sql = sqlite3.connect(database, isolation_level=None)
        sql.enable_load_extension(False)
        sql.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, MAX_STATEMENT)
        sql.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_STATEMENT)
        sql.setlimit(sqlite3.SQLITE_LIMIT_ATTACHED, 0)
        sql.execute('PRAGMA trusted_schema=OFF')
        sql.execute('PRAGMA cache_size=-8192')
        sql.execute('PRAGMA mmap_size=0')
        sql.execute(f'PRAGMA max_page_count={MAX_EXPORT // sql.execute("PRAGMA page_size").fetchone()[0]}')
        sql.execute('PRAGMA foreign_keys=ON')
        sql.execute('BEGIN IMMEDIATE')
        sql.execute('PRAGMA defer_foreign_keys=ON')
        sql.set_authorizer(authorize)
        sql.set_progress_handler(lambda: int(time.monotonic() - started >= MAX_SECONDS), 1000)
        declared_transaction = False
        with retained.open('rb') as stream:
            for statement in statements(stream, deadline):
                boundary = transaction_boundary(statement)
                if boundary:
                    require(declared_transaction is (boundary == 'commit'), 'export_transaction_invalid')
                    declared_transaction = boundary == 'begin'
                    continue
                # executescript silently commits an open transaction first.
                # Keep the entire conversion in one owned transaction: D1 SQL
                # dumps omit wrappers, and per-row disk commits are too slow.
                sql.execute(statement)
        require(not declared_transaction, 'export_transaction_incomplete')
        sql.set_authorizer(None)
        tables = {row[0] for row in sql.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        require(REQUIRED <= tables and tables <= TABLES | {'sqlite_sequence'}, 'unsupported_export_schema')
        require(all(row[0] == 'ok' for row in sql.execute('PRAGMA integrity_check'))
                and not sql.execute('PRAGMA foreign_key_check').fetchone(), 'export_integrity_failure')
        rows = {table: sql.execute('SELECT COUNT(*) FROM "' + table + '"').fetchone()[0]
                for table in sorted(tables - {'sqlite_sequence'})}
        sql.execute('COMMIT')
        sql.close()
        sql = None
        deadline()
        require(file_digest(plain_path(source)) == source_sha256
                and provenance_document(provenance, provenance_sha256, environment) == document,
                'export_input_changed')
        require(not any(Path(str(database) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')),
                'export_database_not_closed')
        report = {'version': 1, 'scope': 'offline-d1-export-conversion', 'complete': True,
                  'liveReady': False, 'providerProvenanceVerified': False,
                  'resource': document['resource'], 'exportSha256': source_sha256,
                  'provenanceSha256': provenance_sha256, 'databaseSha256': file_digest(database),
                  'tables': rows, 'foreignKeysChecked': True, 'cloudResourcesAccessed': False}
        write_file(destination / 'conversion-report.private.json', encoded(report))
        return report
    except (Exception, KeyboardInterrupt) as error:
        if sql is not None:
            sql.close()
        code = str(error) if isinstance(error, ExportError) else (
            'export_conversion_timeout' if time.monotonic() - started >= MAX_SECONDS else 'export_conversion_failed')
        write_file(destination / 'failure-report.private.json', encoded({
            'complete': False, 'liveReady': False, 'error': code, 'cloudResourcesAccessed': False}))
        raise ExportError(code) from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sql-export', required=True)
    parser.add_argument('--sql-sha256', required=True)
    parser.add_argument('--provenance', required=True)
    parser.add_argument('--provenance-sha256', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--environment', choices=('production', 'staging'), default='production')
    args = parser.parse_args(argv)
    try:
        report = convert_export(args.sql_export, args.sql_sha256, args.provenance,
                                args.provenance_sha256, args.out, environment=args.environment)
        print(json.dumps({'complete': report['complete'], 'liveReady': False,
                          'tables': len(report['tables']), 'cloudResourcesAccessed': False}))
        return 0
    except (Exception, KeyboardInterrupt):
        print(json.dumps({'complete': False, 'liveReady': False, 'error': 'export_conversion_failed'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
