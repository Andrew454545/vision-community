"""Read-only, bounded recovery identity for optional queued searches.

Preserve durable holds, claims, terminal tombstones and exact private payloads.
This never expires jobs, repairs balances, executes a query or contacts a service.
"""
from __future__ import annotations

import hashlib
from contextlib import closing
from pathlib import Path
import re
import sqlite3

from .native_scene_search import strict_json
from .search_snapshot import digest, encoded

SCOPE = 'queued-search-financial-cutoff-v1-20261012'
HEX = re.compile(r'[0-9a-f]{64}\Z')
ID = re.compile(r'[0-9a-f]{32}\Z')
SAFE = 2**53 - 1
STATES = {'queued', 'claimed', 'settled', 'failed', 'cancelled', 'expired'}
FIELDS = {'id', 'account_id', 'idempotency_key', 'query_digest', 'query_json', 'lane', 'binding_json',
          'cost_units', 'state', 'created_at', 'expires_at', 'claim_token', 'claim_until', 'attempts',
          'completion_nonce', 'error_code'}


class QueueRestoreError(ValueError):
    pass


def require(value, code='invalid_queued_financial_state'):
    if not value:
        raise QueueRestoreError(code)


def integer(value, low=0, high=SAFE):
    return type(value) is int and low <= value <= high


def hex_value(value, pattern=HEX):
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def schema_rows(sql):
    return [(r[0], r[1], r[2], re.sub(r'\s+', ' ', r[3]).strip() if r[3] else None)
            for r in sql.execute("SELECT type,name,tbl_name,sql FROM sqlite_master "
                                 "WHERE name LIKE 'search_jobs%' OR name='search_queue_revision' ORDER BY name")]


def expected_schema():
    root = Path(__file__).resolve().parents[1] / 'deploy' / 'cloudflare'
    with closing(sqlite3.connect(':memory:')) as sql:
        sql.executescript((root / 'schema.sql').read_text(encoding='utf-8'))
        sql.executescript((root / 'search-queue.sql').read_text(encoding='utf-8'))
        return schema_rows(sql)


def queue_state(sql):
    """None means this is genuinely an older database without the queue.

    Presence is significant even when there are zero jobs: restoring an empty
    table without its reservation/deletion guards is not equivalent recovery.
    """
    schema = schema_rows(sql)
    if not schema:
        return None
    require(schema == expected_schema(), 'queued_financial_schema_mismatch')
    require([tuple(r) for r in sql.execute('SELECT * FROM search_queue_revision')] ==
            [(1, 1, 'vision-search-queue-v1-20261012')], 'queued_financial_schema_mismatch')
    require(sql.execute('SELECT COUNT(*) FROM search_jobs').fetchone()[0] <= 512)
    names = [r[1] for r in sql.execute('PRAGMA table_info(search_jobs)')]
    require(set(names) == FIELDS, 'queued_financial_schema_mismatch')
    rows_hash = hashlib.sha256()
    held, active, claimed, settled = {}, 0, 0, 0
    count = 0
    for values in sql.execute('SELECT * FROM search_jobs ORDER BY id'):
        row = dict(zip(names, values))
        require(hex_value(row['id'], ID) and isinstance(row['account_id'], str)
                and isinstance(row['idempotency_key'], str) and 8 <= len(row['idempotency_key']) <= 100
                and isinstance(row['query_digest'], str) and row['query_digest'].startswith('sha256:')
                and hex_value(row['query_digest'][7:]) and row['lane'] in {'scene', 'object'}
                and row['state'] in STATES and integer(row['cost_units'], 1)
                and integer(row['created_at']) and integer(row['expires_at'])
                and row['expires_at'] - row['created_at'] == 3600 and integer(row['attempts'], 0, 3))
        owner = sql.execute('SELECT units,deleted_at FROM accounts WHERE id=?', (row['account_id'],)).fetchone()
        require(owner is not None and owner[1] is None and integer(owner[0]))
        require(isinstance(row['binding_json'], str) and len(row['binding_json'].encode('utf-8')) <= 2048)
        try:
            pin = strict_json(row['binding_json'].encode('utf-8'))
        except ValueError:
            raise QueueRestoreError('invalid_queued_financial_state') from None
        require(isinstance(pin, dict) and set(pin) == {'contractVersion', 'policyId', 'runtimeSha256', 'snapshotSha256'}
                and type(pin['contractVersion']) is int and pin['contractVersion'] == 2
                and isinstance(pin['policyId'], str) and 1 <= len(pin['policyId']) <= 200
                and hex_value(pin['runtimeSha256']) and hex_value(pin['snapshotSha256']))
        is_active = row['state'] in {'queued', 'claimed'}
        if is_active:
            require(isinstance(row['query_json'], str) and len(row['query_json'].encode('utf-8')) <= 65536
                    and digest(row['query_json'].encode('utf-8')) == row['query_digest'][7:]
                    and row['completion_nonce'] is None and row['error_code'] is None)
            try:
                query = strict_json(row['query_json'].encode('utf-8'))
            except ValueError:
                raise QueueRestoreError('invalid_queued_financial_state') from None
            require(isinstance(query, dict) and query.get('lane') == row['lane'])
            number, units = held.get(row['account_id'], (0, 0))
            held[row['account_id']] = number + 1, units + row['cost_units']
            require(number + 1 <= 3 and units + row['cost_units'] <= owner[0])
            active += 1
        else:
            require(row['query_json'] is None and row['claim_token'] is None and row['claim_until'] is None)
        if row['state'] == 'claimed':
            require(hex_value(row['claim_token']) and integer(row['claim_until'], row['created_at'] + 1, row['expires_at'])
                    and 1 <= row['attempts'] <= 3)
            claimed += 1
        elif row['state'] == 'queued':
            require(row['claim_token'] is None and row['claim_until'] is None and row['attempts'] == 0)
        saved = sql.execute('SELECT id,query,result_json FROM searches WHERE account_id=? AND idempotency_key=?',
                            (row['account_id'], row['idempotency_key'])).fetchone()
        debit = sql.execute("SELECT account_id,units FROM ledger WHERE reason='search' AND reference=?",
                            ('search:' + row['id'],)).fetchall()
        if row['state'] == 'settled':
            require(1 <= row['attempts'] <= 3 and hex_value(row['completion_nonce']) and row['error_code'] is None and saved is not None
                    and saved[0] == row['id'] and saved[1] == row['query_digest']
                    and [tuple(r) for r in debit] == [(row['account_id'], -row['cost_units'])])
            try:
                result = strict_json(saved[2].encode('utf-8'))
            except (ValueError, AttributeError):
                raise QueueRestoreError('invalid_queued_financial_state') from None
            require(isinstance(result, dict) and result.get('searchId') == row['id']
                    and type(result.get('costUnits')) is int and result['costUnits'] == row['cost_units'])
            settled += 1
        else:
            require(row['completion_nonce'] is None and saved is None and not debit)
            expected_error = {'failed': 'search_failed', 'cancelled': 'search_cancelled', 'expired': 'search_expired'}.get(row['state'])
            require(row['error_code'] == expected_error)
        rows_hash.update(encoded(row))
        count += 1
    require(active <= 128)
    reserved = sum(units for _, units in held.values())
    require(integer(reserved))
    return {'scope': SCOPE, 'schemaSha256': digest(encoded(schema)), 'jobs': count, 'active': active,
            'claimed': claimed, 'settled': settled, 'reservedUnits': reserved, 'jobsSha256': rows_hash.hexdigest()}


def validate_queue_snapshot(value):
    require(isinstance(value, dict) and set(value) == {'scope', 'schemaSha256', 'jobs', 'active', 'claimed',
                'settled', 'reservedUnits', 'jobsSha256'} and value['scope'] == SCOPE
            and hex_value(value['schemaSha256']) and hex_value(value['jobsSha256'])
            and integer(value['jobs'], 0, 512) and integer(value['active'], 0, min(128, value['jobs']))
            and integer(value['claimed'], 0, value['active']) and integer(value['settled'], 0, value['jobs'] - value['active'])
            and integer(value['reservedUnits'])
            and (value['active'] > 0 or value['reservedUnits'] == 0)
            and value['reservedUnits'] >= value['active'], 'invalid_queued_financial_snapshot')
