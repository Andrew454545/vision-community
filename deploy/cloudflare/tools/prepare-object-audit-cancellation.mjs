// Optional private operator setup only; no request-time DDL or public gate.
import {prepareObjectAuditDispatch} from './prepare-object-audit-dispatch.mjs';
import {OBJECT_CANCELLATION_SCHEMA,OBJECT_CANCELLATION_CONTRACT_SQL} from '../src/objectAuditCancellation.js';
export async function prepareObjectAuditCancellation(db) {
  await prepareObjectAuditDispatch(db);
  await db.batch([...OBJECT_CANCELLATION_SCHEMA,OBJECT_CANCELLATION_CONTRACT_SQL].map(sql=>db.prepare(sql)));
}
