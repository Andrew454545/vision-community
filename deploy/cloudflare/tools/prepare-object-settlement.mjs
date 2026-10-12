// Explicit operator migration; public requests never install this schema.
import {OBJECT_SETTLEMENT_SCHEMA,OBJECT_SETTLEMENT_CONTRACT_SQL} from '../src/objectSettlement.js';
export async function prepareObjectSettlement(db) {
  await db.batch([...OBJECT_SETTLEMENT_SCHEMA,OBJECT_SETTLEMENT_CONTRACT_SQL].map(sql=>db.prepare(sql)));
}
