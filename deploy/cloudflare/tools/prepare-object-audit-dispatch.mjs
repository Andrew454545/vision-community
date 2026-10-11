// Explicit optional operator migration; no HTTP DDL or change to public gates.
import {OBJECT_DISPATCH_SCHEMA,OBJECT_DISPATCH_CONTRACT_SQL} from '../src/objectAuditDispatch.js';
export async function prepareObjectAuditDispatch(db) {
  await db.batch([...OBJECT_DISPATCH_SCHEMA,OBJECT_DISPATCH_CONTRACT_SQL].map(sql=>db.prepare(sql)));
}
