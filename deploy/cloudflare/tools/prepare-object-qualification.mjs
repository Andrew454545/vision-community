import {OBJECT_QUALIFICATION_SCHEMA,OBJECT_QUALIFICATION_CONTRACT_SQL} from '../src/objectQualificationSchema.js';
// Local/operator caller only; never imported by the request router.
export async function prepareObjectQualification(db) {
  await db.batch([...OBJECT_QUALIFICATION_SCHEMA,OBJECT_QUALIFICATION_CONTRACT_SQL].map(sql=>db.prepare(sql)));
}
