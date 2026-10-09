// Offline, read-only operator check. Does not replay SQL or change balances.
import { createHash } from 'node:crypto';
import { DatabaseSync } from 'node:sqlite';
import { lstatSync, existsSync, openSync, readSync, closeSync, mkdirSync,
  writeFileSync, fsyncSync, readFileSync } from 'node:fs';
import { resolve, join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { parseArgs } from 'node:util';
import { RESOURCE_PROFILES } from './account-restore.mjs';
import { UNITS } from '../src/model.js';

export class CreditRecoveryError extends Error {}
const fail = code => { throw new CreditRecoveryError(code); };
const requireTrue = (value, code) => { if (!value) fail(code); };
const HEX = /^[a-f0-9]{64}$/;
const MAX_BYTES = 512 * 1024 * 1024, MAX_ROWS = 1000000, MAX_PUBLICATIONS = 100000;
const integer = value => Number.isSafeInteger(value);
const digest = value => createHash('sha256').update(value).digest('hex');
const rowDigest = row => digest(JSON.stringify(Object.keys(row).sort().map(k => [k, row[k]])));
function rows(db, query, args = [], limit = MAX_ROWS) {
  const output = new Map();
  for (const row of db.prepare(query).iterate(...args)) {
    requireTrue(output.size < limit, 'snapshot_row_limit');
    requireTrue(!output.has(row.id), 'duplicate_snapshot_identity');
    output.set(row.id, row);
  }
  return output;
}
function schema(db) {
  const required = { accounts: ['id','token_hash','recovery_hash','units','deleted_at'],
    ledger: ['id','account_id','units','reason','reference'],
    searches: ['id','account_id','idempotency_key','query','result_json'],
    leases: ['id','account_id','lane','state'], lease_items: ['lease_id','location_id'],
    locations: ['id','asset_id','capture','lane','model','state','contributor_id','output_sha256'],
    published_index: ['location_id','output_sha256'],
    account_deletion_receipts: ['account_id','request_key','deleted_at','units_forfeited'] };
  for (const [table, columns] of Object.entries(required)) {
    const actual = new Set(db.prepare(`PRAGMA table_info(${table})`).all().map(r => r.name));
    requireTrue(columns.every(c => actual.has(c)), 'unsupported_accounting_schema');
  }
  requireTrue(db.prepare('PRAGMA quick_check').all().every(r => r.quick_check === 'ok'), 'damaged_accounting_snapshot');
  requireTrue(db.prepare('PRAGMA foreign_key_check').all().length === 0, 'accounting_foreign_key_failure');
}
function collect(db) {
  schema(db);
  const accounts = rows(db, 'SELECT id,token_hash,recovery_hash,units,deleted_at FROM accounts ORDER BY id');
  const ledger = rows(db, 'SELECT id,account_id,units,reason,reference FROM ledger ORDER BY id');
  const searches = rows(db, 'SELECT * FROM searches ORDER BY id');
  const receipts = rows(db, 'SELECT account_id AS id,request_key,deleted_at,units_forfeited FROM account_deletion_receipts ORDER BY account_id');
  const publications = new Map(), leases = new Map(), refs = new Set(), sums = new Map(), granted = new Set(), searchDebits = new Map();
  for (const row of db.prepare(`SELECT i.*,l.lane AS _lane,l.state AS _state,l.contributor_id AS _contributor,
    l.output_sha256 AS _location_digest,l.asset_id AS _asset,l.capture AS _capture,l.model AS _model
    FROM published_index i LEFT JOIN locations l ON l.id=i.location_id ORDER BY i.location_id`).iterate()) {
    requireTrue(publications.size < MAX_PUBLICATIONS && integer(row.location_id), 'publication_row_limit');
    requireTrue(row._state === 'published' && accounts.has(row._contributor)
      && row._location_digest === row.output_sha256 && typeof row.output_sha256 === 'string'
      && row.output_sha256.length > 0 && Object.hasOwn(UNITS, row._lane), 'publication_accounting_mismatch');
    publications.set(row.location_id, { digest: rowDigest(row), contributor: row._contributor, lane: row._lane });
  }
  for (const [id, a] of accounts) {
    requireTrue(typeof id === 'string' && id.length > 0 && integer(a.units) && a.units >= 0,
      'invalid_account_balance');
    requireTrue(a.deleted_at === null || (integer(a.deleted_at) && a.deleted_at >= 0
      && a.units === 0 && a.recovery_hash === null && receipts.get(id)?.deleted_at === a.deleted_at),
    'deleted_account_state_mismatch');
    sums.set(id, 0n);
  }
  for (const [id, receipt] of receipts) requireTrue(accounts.get(id)?.deleted_at === receipt.deleted_at
    && integer(receipt.units_forfeited) && receipt.units_forfeited >= 0
    && typeof receipt.request_key === 'string' && HEX.test(receipt.request_key), 'invalid_account_deletion_receipt');
  for (const row of ledger.values()) {
    requireTrue(integer(row.id) && row.id > 0 && accounts.has(row.account_id) && integer(row.units)
      && typeof row.reference === 'string' && row.reference.length > 0 && !refs.has(row.reference),
    'invalid_or_duplicate_ledger_entry');
    refs.add(row.reference);
    const a = accounts.get(row.account_id);
    if (row.reason === 'verified_work') {
      requireTrue(row.units > 0 && row.reference.startsWith('lease:'), 'unsupported_work_credit');
      const leaseId = row.reference.slice(6), lease = db.prepare('SELECT * FROM leases WHERE id=?').get(leaseId);
      requireTrue(lease?.account_id === row.account_id && lease.state === 'submitted'
        && Object.hasOwn(UNITS, lease.lane), 'credited_lease_mismatch');
      const items = db.prepare('SELECT location_id FROM lease_items WHERE lease_id=? ORDER BY location_id LIMIT ?')
        .all(leaseId, MAX_PUBLICATIONS + 1);
      requireTrue(items.length > 0 && items.length <= MAX_PUBLICATIONS
        && row.units === items.length * UNITS[lease.lane], 'credited_publication_count_mismatch');
      for (const item of items) {
        const p = publications.get(item.location_id);
        requireTrue(p?.contributor === row.account_id && p.lane === lease.lane
          && !granted.has(item.location_id), 'missing_or_double_credited_publication');
        granted.add(item.location_id);
      }
      leases.set(leaseId, { digest: rowDigest(lease), itemsDigest: digest(JSON.stringify(items)) });
    } else if (row.reason === 'search') {
      requireTrue(row.units < 0 && row.reference.startsWith('search:'), 'invalid_search_debit');
      const saved = searches.get(row.reference.slice(7));
      requireTrue(a.deleted_at === null ? saved?.account_id === row.account_id : !saved,
        'missing_or_deleted_paid_search');
      searchDebits.set(row.reference.slice(7), row.account_id);
    } else if (row.reason === 'account_deleted') {
      requireTrue(a.deleted_at !== null && row.reference === `account-delete:${row.account_id}`
        && row.units === -receipts.get(row.account_id)?.units_forfeited, 'deletion_debit_mismatch');
    } else if (row.reason === 'account_restore_deleted') {
      requireTrue(a.deleted_at !== null && row.units < 0
        && row.reference === `account-restore-delete:${row.account_id}`, 'restore_deletion_debit_mismatch');
    } else fail('unsupported_credit_reason');
    const sum = sums.get(row.account_id) + BigInt(row.units);
    requireTrue(sum >= 0n && sum <= BigInt(Number.MAX_SAFE_INTEGER), 'invalid_ledger_running_balance');
    sums.set(row.account_id, sum);
  }
  requireTrue(granted.size === publications.size, 'uncredited_publication');
  for (const [id, a] of accounts) requireTrue(BigInt(a.units) === sums.get(id), 'balance_ledger_mismatch');
  const searchKeys = new Set();
  for (const s of searches.values()) {
    const a = accounts.get(s.account_id), key = JSON.stringify([s.account_id,s.idempotency_key]);
    requireTrue(a?.deleted_at === null && typeof s.idempotency_key === 'string' && s.idempotency_key.length > 0
      && typeof s.query === 'string' && s.query.length > 0 && !searchKeys.has(key), 'invalid_saved_search');
    searchKeys.add(key);
    let result;
    try { result = JSON.parse(s.result_json); } catch { fail('invalid_saved_search_result'); }
    requireTrue(result?.searchId === s.id, 'saved_search_identity_mismatch');
    requireTrue(searchDebits.get(s.id) === s.account_id, 'unpaid_saved_search');
  }
  return { accounts,ledger,searches,receipts,publications,leases };
}
function same(left, right, code) {
  requireTrue(left.size === right.size, code);
  for (const [key,row] of left) requireTrue(right.has(key) && rowDigest(row) === rowDigest(right.get(key)), code);
}
function history(backup, current) {
  for (const [key,row] of backup.ledger) requireTrue(current.ledger.has(key)
    && rowDigest(row) === rowDigest(current.ledger.get(key)), 'backup_ledger_history_changed');
  let high = 0;
  for (const key of backup.ledger.keys()) high = Math.max(high, key);
  for (const key of current.ledger.keys()) requireTrue(backup.ledger.has(key) || key > high, 'backdated_ledger_entry');
  for (const [id,a] of backup.accounts) {
    const now = current.accounts.get(id);
    requireTrue(now && (a.deleted_at === null || a.deleted_at === now.deleted_at), 'backup_account_history_missing');
  }
  for (const [id,s] of backup.searches) requireTrue(current.searches.has(id)
    ? rowDigest(s) === rowDigest(current.searches.get(id))
    : current.accounts.get(s.account_id)?.deleted_at !== null && current.receipts.has(s.account_id),
  'backup_saved_search_history_changed');
  for (const field of ['receipts','publications','leases']) for (const [id,row] of backup[field]) {
    requireTrue(current[field].has(id) && rowDigest(row) === rowDigest(current[field].get(id)), 'backup_publication_or_deletion_history_changed');
  }
}
export function verifyCreditRecovery(backupDb, currentDb, recoveredDb) {
  const backup = collect(backupDb), current = collect(currentDb), recovered = collect(recoveredDb);
  history(backup, current);
  for (const field of ['accounts','ledger','searches','receipts','publications','leases']) {
    same(current[field], recovered[field], `recovered_${field}_mismatch`);
  }
  const extra = [...current.ledger.values()].filter(r => !backup.ledger.has(r.id));
  const total = reason => extra.filter(r => r.reason === reason).reduce((n,r) => n + BigInt(r.units), 0n).toString();
  return { accountingCopyVerified: true, liveReady: false, productionQualified: false,
    creditRecoveryVerified: false, providerRecoveryVerified: false,
    accounts: current.accounts.size, ledgerEntries: current.ledger.size,
    savedPaidSearches: current.searches.size, creditedPublications: current.publications.size,
    deletedAccounts: current.receipts.size, postBackupLedgerEntries: extra.length,
    postBackupEarnedUnits: total('verified_work'), postBackupSearchUnits: total('search'),
    postBackupDeletionUnits: (BigInt(total('account_deleted')) + BigInt(total('account_restore_deleted'))).toString() };
}
function pinFile(path, pin, maximum = MAX_BYTES) {
  requireTrue(HEX.test(pin || ''), 'invalid_checksum_pin');
  const stat = lstatSync(path);
  requireTrue(stat.isFile() && !stat.isSymbolicLink() && stat.size <= maximum, 'invalid_or_oversized_input');
  requireTrue(!['-wal','-shm','-journal'].some(s => existsSync(path+s)), 'snapshot_has_sidecars');
  const fd = openSync(path, 'r'), hash = createHash('sha256'), buffer = Buffer.alloc(1024*1024);
  let bytes = 0;
  try { for (let n; (n = readSync(fd,buffer,0,buffer.length,null));) {
    bytes += n; requireTrue(bytes <= maximum, 'input_changed_or_oversized'); hash.update(buffer.subarray(0,n));
  } } finally { closeSync(fd); }
  requireTrue(hash.digest('hex') === pin, 'input_checksum_mismatch');
}
export function checkCreditRecovery({ backup, current, recovered, authority, authoritySha256,
  recoveredSha256, authorityNotBefore, out, environment = 'production', now = Math.floor(Date.now()/1000) }) {
  const destination = resolve(out), paths = [backup,current,recovered,authority].map(p => resolve(p));
  requireTrue(new Set(paths).size === 4, 'snapshot_paths_must_be_distinct');
  // mkdir with no recursive flag refuses existing destinations and missing parents.
  mkdirSync(destination, { mode: 0o700 });
  try {
    pinFile(paths[3],authoritySha256,64*1024);
    const document = JSON.parse(readFileSync(paths[3], 'utf8'));
    const expected = RESOURCE_PROFILES[environment];
    requireTrue(expected && document?.version === 1 && document.scope === 'vision-community-credit-recovery'
      && document.writersStopped === true && integer(authorityNotBefore) && authorityNotBefore >= 0
      && integer(now) && authorityNotBefore <= now && integer(document.capturedAt)
      && document.capturedAt >= authorityNotBefore && document.capturedAt <= now
      && document.resource && Object.keys(document.resource).length === 3
      && Object.entries(expected).every(([k,v]) => document.resource[k] === v), 'invalid_or_stale_authority');
    const pins = [document.backupSha256,document.currentSha256,recoveredSha256,authoritySha256];
    paths.forEach((p,i) => pinFile(p,pins[i],i===3?64*1024:MAX_BYTES));
    const dbs = [];
    let result;
    try {
      for (const p of paths.slice(0,3)) dbs.push(new DatabaseSync(p,{ readOnly:true }));
      result = verifyCreditRecovery(...dbs);
    } finally { dbs.forEach(db => db.close()); }
    // Recheck every input after all comparisons; the success marker is last.
    paths.forEach((p,i) => pinFile(p,pins[i],i===3?64*1024:MAX_BYTES));
    const report = { version:1, scope:document.scope, complete:true, resource:expected,
      capturedAt:document.capturedAt, authoritySha256, backupSha256:pins[0], currentSha256:pins[1],
      recoveredSha256:pins[2], ...result };
    writeReport(join(destination,'credit-recovery-report.json'), report);
    return report;
  } catch (error) {
    const code = error instanceof CreditRecoveryError ? error.message : 'credit_recovery_check_failed';
    writeReport(join(destination,'credit-recovery-failure.json'), { complete:false, liveReady:false,error:code });
    throw new CreditRecoveryError(code);
  }
}
function writeReport(path, report) {
  writeFileSync(path, JSON.stringify(report)+'\n', { flag:'wx',mode:0o600 });
  const fd = openSync(path,'r+'); try { fsyncSync(fd); } finally { closeSync(fd); }
}
if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url) {
  try {
    const { values } = parseArgs({ options:Object.fromEntries(['backup','current','recovered','authority',
      'authority-sha256','recovered-sha256','authority-not-before','out','environment'].map(k => [k,{type:'string'}])) });
    requireTrue(['backup','current','recovered','authority','authority-sha256','recovered-sha256',
      'authority-not-before','out'].every(k => values[k]) && /^\d+$/.test(values['authority-not-before']), 'invalid_arguments');
    console.log(JSON.stringify(checkCreditRecovery({ ...values, authoritySha256:values['authority-sha256'],
      recoveredSha256:values['recovered-sha256'],authorityNotBefore:Number(values['authority-not-before']) })));
  } catch (error) { console.error(JSON.stringify({ complete:false,error:error instanceof CreditRecoveryError
    ? error.message:'credit_recovery_check_failed' })); process.exitCode = 1; }
}
