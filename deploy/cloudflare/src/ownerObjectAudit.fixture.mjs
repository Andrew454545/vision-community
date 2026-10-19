// Fictional native/coverage/storage only, real SQLite/publication transactions.
import {readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
import {sqliteD1} from '../tools/sqlite-d1.mjs';
import {prepareDatabase} from '../tools/initialize-schema.mjs';
import {prepareObjectAuditDispatch} from '../tools/prepare-object-audit-dispatch.mjs';
import {prepareObjectSettlement} from '../tools/prepare-object-settlement.mjs';
import {stageObjectAudit} from './objectAuditDispatch.js';
import {syntheticR2} from './syntheticR2.mjs';
import {OBJECT_INDEX_MODEL} from './objectIndex.js';
import {COVERAGE_VALIDATOR} from './objectCoverage.js';
import {sha256Hex,encodeUtf8} from './model.js';
import {OWNER_OBJECT_MODE,ownerObjectBinding,claimOwnerObjectAudit} from './ownerObjectAudit.js';

const document=JSON.parse(readFileSync(new URL('../../../community/tests/fixtures/object-feature-content-v1.json',import.meta.url),'utf8'));
export const ACCOUNT='b'.repeat(32),LEASE=document.leaseId,JOB='c'.repeat(32),SECRET='f'.repeat(64);
export async function ownerFixture(t, overrides={}) {
  const now=Math.floor(Date.now()/1000),sql=new DatabaseSync(':memory:');t.after(()=>sql.close());
  const objects=new Map(),r2=syntheticR2(objects);
  let reads=0;
  const env={DB:sqliteD1(sql),DEPLOYMENT_ENVIRONMENT:'staging',INDEX_BUCKET_NAME:'vision-community-staging',
    INDEX:{...r2,async get(key){reads++;const o=await r2.get(key);return o?{...o,body:new Response(await o.arrayBuffer()).body}:null;}},
    OBJECT_AUDIT_DELIVERY:OWNER_OBJECT_MODE,OBJECT_AUDIT_AGENT_SECRET:SECRET};
  await prepareDatabase(env.DB);await prepareObjectAuditDispatch(env.DB);await prepareObjectSettlement(env.DB);
  sql.prepare("INSERT INTO accounts(id,token_hash,units) VALUES (?,'fictional-account-token',0)").run(ACCOUNT);
  sql.prepare("INSERT INTO leases(id,account_id,lane,state,expires_at) VALUES (?,?,'object','active',?)").run(LEASE,ACCOUNT,now+10000);
  for(const item of document.items){
    sql.prepare(`INSERT INTO locations(id,asset_id,capture,lane,model,state,active_lease,camera_generation,lat,lon,heading,pitch,zoom,country)
      VALUES (?,?,'fictional','object',?,'leased',?,'gen4',?,?,?,?,?,?)`).run(item.locationId,item.panoId,OBJECT_INDEX_MODEL,
        LEASE,item.lat,item.lng,item.heading,item.pitch,item.zoom,item.country);
    sql.prepare('INSERT INTO lease_items VALUES (?,?)').run(LEASE,item.locationId);
    sql.prepare('INSERT INTO object_coverage VALUES (?,?,?,?)').run(item.locationId,COVERAGE_VALIDATOR,'d'.repeat(64),now);
  }
  const index=overrides.index??{manifest:structuredClone(document.baseline.manifest),sourceTsv:document.baseline.sourceBase64,files:document.baseline.filesBase64};
  if(!overrides.index) Object.assign(index.manifest.viewQuality,{policy:'vision-per-view-quality-v1',implementationIdentity:'1'.repeat(64),viewCount:6,
    blurAreaFractionExclusive:.5,tileGrid:8,tunnelVisionProbabilityInclusive:.85,tunnelEvidencePolicy:'none-darkness-never-rejects-v1',
    protectedAuthorityManifestSha256:'2'.repeat(64)});
  index.manifest.sourceTsv='C:/FICTIONAL-PRIVATE/source.tsv';index.manifest.privateExtension={secret:'FICTIONAL-PRIVATE'};
  const authority=overrides.authority??{leaseId:LEASE,profileId:'1'.repeat(64),policyId:'staging.synthetic',assignmentSha256:'2'.repeat(64),
    sourceSha256:await sha256Hex(new Uint8Array(Buffer.from(index.sourceTsv,'base64')))};
  const pins=overrides.pins??{policySha256:'5'.repeat(64),runtimeProfileSha256:'6'.repeat(64),qualityImplementationIdentity:'1'.repeat(64),
    protectedAuthoritySha256:'2'.repeat(64),protectedOriginHandoffSha256:'7'.repeat(64)};
  const resource={accountId:'272760294910ef0b246980278aeb36e2',databaseId:'17043cb7-5dab-4a6f-84ca-19ae1c14cc05',bucket:'vision-community-staging'};
  env.OBJECT_SETTLEMENT_POLICY=JSON.stringify({version:1,scope:'object-batch-parity-v1',policyId:authority.policyId,
    profiles:[authority.profileId],...pins,resource});
  await stageObjectAudit(env,ACCOUNT,authority,index,now);
  const row=()=>sql.prepare('SELECT * FROM object_audit_candidates WHERE lease_id=?').get(LEASE);
  const audit=(state='approved',attempts=1)=>({version:1,jobId:JOB,leaseId:LEASE,profileId:authority.profileId,policyId:authority.policyId,
    assignmentSha256:authority.assignmentSha256,submissionSha256:row().submission_sha256,candidateManifestSha256:'3'.repeat(64),
    state,decision:['approved','rejected'].includes(state)?state:'pending',attempts,retryAt:0,
    receiptSha256:['approved','rejected'].includes(state)?'4'.repeat(64):null,
    serverAuthorization:false,productionQualified:false,acceptedContributions:0,searchCreditsCreated:0});
  const evidence=(at=now)=>({audit:audit(),...pins,resource,qualificationScope:'batch-only',issuedAt:at,expiresAt:at+30});
  const claim=(at=now)=>claimOwnerObjectAudit(env,{binding:ownerObjectBinding(env)},at);
  const body=(job,at=now)=>({leaseId:LEASE,claimToken:job.claimToken,audit:audit(),evidence:evidence(at)});
  const counts=()=>({publications:sql.prepare('SELECT COUNT(*) n FROM published_index').get().n,
    ledger:sql.prepare("SELECT COUNT(*) n FROM ledger WHERE reason='verified_work'").get().n,
    accepted:sql.prepare('SELECT COUNT(*) n FROM object_acceptances').get().n,
    units:sql.prepare('SELECT units FROM accounts WHERE id=?').get(ACCOUNT).units});
  return {env,sql,objects,index,authority,pins,resource,now,row,audit,evidence,claim,body,counts,reads:()=>reads};
}
