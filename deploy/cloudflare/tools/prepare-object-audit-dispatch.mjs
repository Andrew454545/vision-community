// Explicit optional operator migration; no HTTP DDL or change to public gates.
import {objectDispatchMigration} from '../src/objectAuditDispatch.js';
export async function prepareObjectAuditDispatch(db) {
  const installed=await db.prepare("SELECT 1 FROM sqlite_master WHERE type='table' AND name='object_dispatch_revision'").first();
  const revision=installed?await db.prepare('SELECT contract FROM object_dispatch_revision WHERE slot=1').first():null;
  if(installed && !revision)throw Error('object_dispatch_setup_required');
  await db.batch(objectDispatchMigration(revision?.contract??null).map(sql=>db.prepare(sql)));
}
