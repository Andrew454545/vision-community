// Explicit private operator setup only. Existing dispatch/data fences remain.
import {prepareObjectAuditDispatch} from './prepare-object-audit-dispatch.mjs';
import {OBJECT_RECOVERY_SCHEMA,OBJECT_RECOVERY_CONTRACT_SQL} from '../src/objectAuditRecovery.js';
export async function prepareObjectAuditRecovery(db) {
  await prepareObjectAuditDispatch(db);
  await db.batch([...OBJECT_RECOVERY_SCHEMA,OBJECT_RECOVERY_CONTRACT_SQL].map(sql=>db.prepare(sql)));
}
