// Explicit operator/local migration. Never imported by the HTTP router.
import {QUALIFIED_OBJECT_SCHEMA,QUALIFIED_OBJECT_CONTRACT_SQL} from '../src/qualifiedObjectSchema.js';
export async function prepareQualifiedObject(db) {
  await db.batch([...QUALIFIED_OBJECT_SCHEMA,QUALIFIED_OBJECT_CONTRACT_SQL].map(sql=>db.prepare(sql)));
}
export async function bindQualifiedObjectPolicy(db,eligibilitySha256,qualificationAuthoritySha256) {
  if(![eligibilitySha256,qualificationAuthoritySha256].every(v=>typeof v==='string'&&/^[0-9a-f]{64}$/.test(v)))throw Error('invalid_qualified_object_policy');
  const old=await db.prepare('SELECT * FROM qualified_object_policy WHERE slot=1').first();
  if(old){if(old.eligibility_sha256!==eligibilitySha256||old.qualification_authority_sha256!==qualificationAuthoritySha256)
    throw Error('qualified_object_policy_rotation_required');return;}
  // Never reconstruct lost authority after restoring retained work.
  const inserted=await db.prepare(`INSERT INTO qualified_object_policy SELECT 1,0,?,?
    WHERE NOT EXISTS (SELECT 1 FROM qualified_object_candidates) AND NOT EXISTS (SELECT 1 FROM qualified_object_acceptances)
    ON CONFLICT(slot) DO NOTHING`).bind(eligibilitySha256,qualificationAuthoritySha256).run();
  const current=await db.prepare('SELECT * FROM qualified_object_policy WHERE slot=1').first();
  if(!current||current.eligibility_sha256!==eligibilitySha256||current.qualification_authority_sha256!==qualificationAuthoritySha256)
    throw Error('qualified_object_policy_recovery_required');
  return inserted.meta.changes;
}
