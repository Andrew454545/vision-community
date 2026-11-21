// SQL predicates for the exact in-memory eligibility read. No cached approval.
import {objectWorkSqlFence} from './objectWorkFence.js';
const fail=()=>{throw Error('invalid_qualified_object_snapshot');};
const key=k=>{if(!/^[a-z_][a-z_0-9]*$/.test(k))fail();return k;};
export function qualifiedObjectGuard(snapshot,prepared=false) {
  const {integrity,qualification,scenes}=snapshot;
  if(!integrity?.row||!Array.isArray(integrity.rows)||!integrity.rows.length||integrity.rows.length>4
    ||!qualification||!Array.isArray(scenes)||scenes.length!==integrity.rows.length)fail();
  const q=Object.keys(qualification).map(k=>`q.${key(k)} IS json_extract(e.doc,'$.qualification.${k}')`).join(' AND ');
  const extra={validator:'v.validator',evidence_sha256:'v.evidence_sha256',validated_at:'v.validated_at',published_id:'ip.location_id'};
  const locations=Object.keys(integrity.rows[0]).map(k=>`${extra[k]||'x.'+key(k)} IS json_extract(j.value,'$.${k}')`).join(' AND ');
  const sceneExtra={deleted_at:'sa.deleted_at',four_view_sha256:'sp.four_view_sha256',four_view_key:'sp.four_view_key',published_sha256:'sp.output_sha256'};
  const scene=Object.keys(scenes[0].scene).map(k=>`${sceneExtra[k]||'s.'+key(k)} IS json_extract(j.value,'$.scene.${k}')`).join(' AND ');
  const candidateExtra={deleted_at:'a.deleted_at',lease_lane:'l.lane',lease_state:'l.state',lease_expires:'l.expires_at',lease_generation:'l.generation',
    artifact_owner:'w.account_id',artifact_lease:'w.lease_id',artifact_sha256:'w.sha256',artifact_bytes:'w.bytes',claim_token:'NULL',claim_until:'0'};
  const candidate=prepared?'1':Object.keys(integrity.row).map(k=>`${candidateExtra[k]||'c.'+key(k)} IS json_extract(e.doc,'$.integrity.row.${k}')`).join(' AND ');
  return `(${candidate}) AND a.deleted_at IS NULL AND l.account_id=a.id AND l.lane='object'
    AND l.state='${prepared?'active':'submitted'}' AND l.expires_at>e.at
    AND l.expires_at=json_extract(e.doc,'$.integrity.row.lease_expires')
    AND l.generation IS json_extract(e.doc,'$.integrity.row.lease_generation')
    AND q.account_id=a.id AND q.state='qualified' AND q.epoch=k.epoch AND q.expires_at>e.at AND (${q})
    AND ctl.slot=1 AND ctl.eligibility_sha256=e.policy AND ctl.qualification_authority_sha256=q.authority_sha256
    AND (SELECT COUNT(*) FROM lease_items WHERE lease_id=l.id)=json_array_length(e.doc,'$.integrity.rows')
    AND (SELECT COUNT(*) FROM lease_items i JOIN locations x ON x.id=i.location_id
      JOIN object_coverage v ON v.location_id=x.id LEFT JOIN published_index ip ON ip.location_id=x.id
      JOIN json_each(e.doc,'$.integrity.rows') j ON x.id=json_extract(j.value,'$.id')
      WHERE i.lease_id=l.id AND (${locations}) AND v.validated_at<=e.at AND v.validated_at>e.at-86400)=json_array_length(e.doc,'$.integrity.rows')
    AND (SELECT COUNT(*) FROM json_each(e.doc,'$.scenes') j JOIN locations s ON s.id=json_extract(j.value,'$.scene.id')
      JOIN published_index sp ON sp.location_id=s.id JOIN accounts sa ON sa.id=s.contributor_id
      JOIN lease_items i ON i.location_id=json_extract(j.value,'$.objectLocationId') AND i.lease_id=l.id
      WHERE s.lane='scene' AND s.state='published' AND sa.deleted_at IS NULL AND (${scene}))=json_array_length(e.doc,'$.scenes')${objectWorkSqlFence(snapshot.assignment)}`;
}
export const QUALIFIED_OBJECT_JOINS=`JOIN object_qualification_requests q ON q.id=json_extract(e.doc,'$.qualification.id')
  JOIN object_qualification_controls k ON k.account_id=q.account_id AND k.authority_sha256=q.authority_sha256 AND k.profile_id=q.profile_id
  JOIN qualified_object_policy ctl ON ctl.slot=1`;
