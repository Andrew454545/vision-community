// Offline operator preflight. Never imports Cloudflare credentials or changes a DB.
import { readFileSync, existsSync, lstatSync, realpathSync } from 'node:fs';
import { DatabaseSync } from 'node:sqlite';
import { pathToFileURL } from 'node:url';

export function checkSearchQueue(sql) {
  const expected = new DatabaseSync(':memory:');
  try {
    expected.exec(readFileSync(new URL('../schema.sql', import.meta.url), 'utf8'));
    expected.exec(readFileSync(new URL('../search-queue.sql', import.meta.url), 'utf8'));
    const objects = expected.prepare(`SELECT type,name,tbl_name,sql FROM sqlite_master
      WHERE name LIKE 'search_jobs%' OR name='search_queue_revision' ORDER BY name`).all();
    const actual = sql.prepare(`SELECT type,name,tbl_name,sql FROM sqlite_master
      WHERE name LIKE 'search_jobs%' OR name='search_queue_revision' ORDER BY name`).all();
    const normalized = rows => rows.map(value => ({ ...value, sql: value.sql?.replace(/\s+/g, ' ').trim() }));
    if (JSON.stringify(normalized(actual)) !== JSON.stringify(normalized(objects))) throw Error('search_queue_schema_mismatch');
    const revision = sql.prepare('SELECT * FROM search_queue_revision').all();
    if (JSON.stringify(revision) !== JSON.stringify(expected.prepare('SELECT * FROM search_queue_revision').all()))
      throw Error('search_queue_schema_mismatch');
    const counts = sql.prepare(`SELECT COUNT(*) AS jobs,SUM(CASE WHEN state IN ('queued','claimed') THEN 1 ELSE 0 END) AS active
      FROM search_jobs`).get();
    if (counts.jobs > 512 || counts.active > 128) throw Error('search_queue_state_invalid');
    if (sql.prepare(`SELECT 1 FROM search_jobs j LEFT JOIN accounts a ON a.id=j.account_id
      WHERE a.id IS NULL OR a.deleted_at IS NOT NULL
      OR (j.state IN ('queued','claimed') AND j.query_json IS NULL)
      OR (j.state NOT IN ('queued','claimed') AND j.query_json IS NOT NULL)
      OR (j.state='claimed' AND (j.claim_token IS NULL OR j.claim_until IS NULL)) LIMIT 1`).get())
      throw Error('search_queue_state_invalid');
    if (sql.prepare(`SELECT 1 FROM search_jobs j JOIN accounts a ON a.id=j.account_id
      WHERE j.state IN ('queued','claimed') GROUP BY j.account_id
      HAVING COUNT(*)>3 OR SUM(j.cost_units)>a.units LIMIT 1`).get()) throw Error('search_queue_state_invalid');
    return { passed: true, revision: 1, jobs: counts.jobs, active: counts.active || 0, offline: true, liveReady: false };
  } finally { expected.close(); }
}

function main() {
  let sql;
  try {
    if (process.argv.length !== 4 || process.argv[2] !== '--database') throw Error('invalid_arguments');
    const path = process.argv[3];
    if (!lstatSync(path).isFile() || lstatSync(path).isSymbolicLink()
        || ['-wal', '-shm', '-journal'].some(suffix => existsSync(path + suffix))) throw Error('closed_database_required');
    sql = new DatabaseSync(realpathSync(path), { readOnly: true });
    sql.exec('PRAGMA query_only=ON');
    process.stdout.write(JSON.stringify(checkSearchQueue(sql)) + '\n');
  } catch {
    process.stdout.write(JSON.stringify({ passed: false, error: 'search_queue_preflight_failed', offline: true, liveReady: false }) + '\n');
    process.exitCode = 1;
  } finally { sql?.close(); }
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main();
