// Synthetic prepared-pool fixture; no actual qualification, coverage or native work.
import {qualifiedFixture,ACCOUNT,LEASE} from './qualifiedObject.fixture.mjs';
import {prepareObjectWorkPool} from './objectWorkSchema.js';
import {importObjectWorkPool} from '../tools/import-object-work-pool.mjs';
import {requestQualifiedObjectWork} from './objectWork.js';
import {sha256Hex,encodeUtf8} from './model.js';
export async function objectWorkFixture(t,{file=':memory:'}={}){
 const f=await qualifiedFixture(t,{file});
 f.sql.prepare("UPDATE locations SET state='pending',active_lease=NULL WHERE active_lease=?").run(LEASE);
 f.sql.prepare('DELETE FROM lease_items WHERE lease_id=?').run(LEASE);f.sql.prepare('DELETE FROM leases WHERE id=?').run(LEASE);
 await prepareObjectWorkPool(f.env.DB);
 const source=new TextDecoder().decode(new Uint8Array(Buffer.from(f.index.sourceTsv,'base64'))),lines=source.trimEnd().split('\n');
 const records=f.sql.prepare("SELECT * FROM locations WHERE lane='object' ORDER BY id").all().map((r,i)=>({locationId:r.id,panoId:r.asset_id,
   lat:r.lat,lng:r.lon,heading:r.heading,pitch:r.pitch,zoom:r.zoom,country:r.country,cameraGeneration:'gen4',
   roadName:lines[i].split('\t')[10],coverageEvidenceSha256:'d'.repeat(64)}));
 const doc={version:1,scope:'operator-prepared-qualified-object-pool-v1',resource:f.policy.resource,
   eligibilityPolicySha256:f.env.OBJECT_ELIGIBILITY_POLICY_SHA256,entries:[{leaseId:LEASE,profileId:f.authority.profileId,
   assignmentSha256:f.authority.assignmentSha256,sourceSha256:f.authority.sourceSha256,sourceTsv:source,records,validUntil:f.now+1800}]};
 const raw=JSON.stringify(doc);await importObjectWorkPool(f.env,raw,await sha256Hex(encodeUtf8(raw)),f.now);
 const body={requestKey:'5'.repeat(32),profileId:f.authority.profileId,count:2,pace:'medium'};
 return {...f,doc,body,claim:(value=body,at=f.now,timeout=20000)=>requestQualifiedObjectWork(f.env,ACCOUNT,value,at,timeout)};
}
