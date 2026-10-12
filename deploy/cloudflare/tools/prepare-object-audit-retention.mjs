// Explicit operator setup only. Requests and cron never install a schema.
import {OBJECT_RETENTION_SCHEMA,OBJECT_RETENTION_CONTRACT_SQL} from '../src/objectAuditRetention.js';
export async function prepareObjectAuditRetention(db) {
  await db.batch([...OBJECT_RETENTION_SCHEMA,OBJECT_RETENTION_CONTRACT_SQL].map(sql=>db.prepare(sql)));
}
