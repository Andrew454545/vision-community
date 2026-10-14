"""Read-only qualified Object cutoff identity; no repair, inference or authority grant."""
from __future__ import annotations

import base64
import hashlib
import json
import re

from .search_snapshot import encoded

SCOPE = 'qualified-object-recovery-cutoff-v1-20261014'
CONTRACT = 'qualified-object-publication-v1-20261014'
QUALIFICATION_CONTRACT = 'saved-object-qualification-v1-20261013'
# Both source schema arrays, including their complete indexes and SQL fences.
# The fixture exporter checks this pin against the actual installed definitions.
SCHEMA_SHA256 = 'a8c67f6b356e489d64b0d30200d250cd740eced395b05a22faa5f98dde4af980'
MAX_ROWS = 1_000_000
HEX = re.compile(r'[0-9a-f]{64}\Z')
TABLES = ('qualified_object_revision', 'qualified_object_policy', 'qualified_object_candidates',
          'qualified_object_acceptances', 'object_qualification_revision', 'object_qualification_controls',
          'object_qualification_requests', 'object_qualification_revocations')


class QualifiedObjectRestoreError(ValueError):
    pass


def require(value, code='invalid_qualified_object_recovery_state'):
    if not value:
        raise QualifiedObjectRestoreError(code)


def schema_identity(sql):
    rows = [[r[0], r[1], r[2], re.sub(r'[\s;]', '', re.sub(r'IF NOT EXISTS', '', r[3], flags=re.I)).lower()]
            for r in sql.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE sql IS NOT NULL "
                                 "AND (name GLOB 'qualified_object_*' OR name GLOB 'object_qualification_*') ORDER BY name")]
    return hashlib.sha256(json.dumps(rows, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def qualified_object_state(sql):
    # The registry can legitimately predate this optional publication namespace.
    if not sql.execute("SELECT 1 FROM sqlite_master WHERE name GLOB 'qualified_object_*' LIMIT 1").fetchone():
        return None
    require(schema_identity(sql) == SCHEMA_SHA256, 'qualified_object_recovery_schema_mismatch')
    require([tuple(r) for r in sql.execute('SELECT * FROM qualified_object_revision')] == [(1, CONTRACT)]
            and [tuple(r) for r in sql.execute('SELECT * FROM object_qualification_revision')] == [(1, QUALIFICATION_CONTRACT)],
            'qualified_object_recovery_schema_mismatch')
    retained = sql.execute('SELECT COUNT(*) FROM qualified_object_candidates').fetchone()[0]
    require(not retained or sql.execute('SELECT 1 FROM qualified_object_policy WHERE slot=1').fetchone(),
            'qualified_object_policy_recovery_required')
    h = hashlib.sha256()
    count = 0

    def capture(label, query):
        nonlocal count
        cursor = sql.execute(query)
        names = [c[0] for c in cursor.description]
        h.update(encoded({'section': label, 'columns': names}))
        for values in cursor:
            count += 1
            require(count <= MAX_ROWS, 'qualified_object_recovery_row_limit')
            row = []
            for value in values:
                require(value is None or type(value) in (int, float, str, bytes))
                require(not isinstance(value, (str, bytes)) or len(value) <= 4 * 1024**2,
                        'qualified_object_recovery_value_limit')
                row.append({'blobBase64': base64.b64encode(value).decode()} if isinstance(value, bytes) else value)
            h.update(encoded(row))

    for table in TABLES:
        capture(table, f'SELECT * FROM {table} ORDER BY ' +
                ('account_id,authority_sha256,profile_id' if table == 'object_qualification_controls' else
                 'lease_id' if table in ('qualified_object_candidates', 'qualified_object_acceptances') else
                 'slot' if table.endswith(('_revision', '_policy')) else 'id'))
    membership = 'SELECT lease_id FROM qualified_object_candidates'
    capture('leases', f'SELECT * FROM leases WHERE id IN ({membership}) ORDER BY id')
    capture('lease_items', f'SELECT * FROM lease_items WHERE lease_id IN ({membership}) ORDER BY lease_id,location_id')
    locations = f'SELECT location_id FROM lease_items WHERE lease_id IN ({membership})'
    capture('locations', f'SELECT * FROM locations WHERE id IN ({locations}) ORDER BY id')
    capture('coverage', f'SELECT * FROM object_coverage WHERE location_id IN ({locations}) ORDER BY location_id')
    capture('publications', f'SELECT * FROM published_index WHERE location_id IN ({locations}) ORDER BY location_id')
    capture('artifact_writes', f'SELECT * FROM account_artifact_writes WHERE lease_id IN ({membership}) ORDER BY artifact_key')
    acceptances = 0
    for a in sql.execute('SELECT * FROM qualified_object_acceptances ORDER BY lease_id'):
        a = dict(a)
        c = sql.execute('SELECT * FROM qualified_object_candidates WHERE lease_id=?', (a['lease_id'],)).fetchone()
        require(c and c['state'] == 'published' and c['account_id'] == a['account_id']
                and c['qualification_id'] == a['qualification_id'] and c['location_count'] == a['location_count']
                and c['assignment_sha256'] == a['assignment_sha256'] and c['source_sha256'] == a['source_sha256']
                and c['submission_sha256'] == a['submission_sha256'] and a['units'] == a['location_count'] * 10)
        ledger = sql.execute('SELECT account_id,units,reason FROM ledger WHERE reference=?', ('lease:' + a['lease_id'],)).fetchone()
        require(ledger and tuple(ledger) == (a['account_id'], a['units'], 'qualified_device_work'),
                'qualified_object_recovery_award_mismatch')
        rows = sql.execute('SELECT l.*,p.object_index_key,p.object_index_sha256,p.output_sha256 AS published_sha256 '
                           'FROM lease_items i JOIN locations l ON l.id=i.location_id LEFT JOIN published_index p ON p.location_id=l.id '
                           'WHERE i.lease_id=? ORDER BY l.id', (a['lease_id'],)).fetchall()
        require(len(rows) == a['location_count'] and all(r['lane'] == 'object' and r['state'] == 'published'
                and r['contributor_id'] == a['account_id'] and r['object_index_key'] == f"object-index-v4/{a['lease_id']}/"
                and r['object_index_sha256'] == a['source_sha256'] and r['output_sha256'] == r['published_sha256'] for r in rows),
                'qualified_object_recovery_publication_mismatch')
        acceptances += 1
    require(sql.execute("SELECT COUNT(*) FROM qualified_object_candidates WHERE state='published'").fetchone()[0] == acceptances)
    result = {'scope': SCOPE, 'schemaSha256': SCHEMA_SHA256, 'stateSha256': h.hexdigest(),
              'capturedRows': count, 'candidates': retained, 'acceptances': acceptances}
    validate_qualified_object_snapshot(result)
    return result


def validate_qualified_object_snapshot(value):
    require(isinstance(value, dict) and set(value) == {'scope', 'schemaSha256', 'stateSha256', 'capturedRows', 'candidates', 'acceptances'}
            and value['scope'] == SCOPE and value['schemaSha256'] == SCHEMA_SHA256
            and isinstance(value['stateSha256'], str) and HEX.fullmatch(value['stateSha256'])
            and all(type(value[k]) is int and 0 <= value[k] <= MAX_ROWS for k in ('capturedRows', 'candidates', 'acceptances'))
            and value['acceptances'] <= value['candidates'] <= value['capturedRows'],
            'invalid_qualified_object_recovery_snapshot')
