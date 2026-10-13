// Isolated synthetic fixture only. This is not a route or an approval exporter.
import {createHash} from 'node:crypto';
import {DatabaseSync} from 'node:sqlite';
import {readFileSync} from 'node:fs';
import {queueSearch,claimQueuedSearch,completeQueuedSearch} from './searchQueue.js';
import {deleteAccount,migrateAccountPrivacy} from './accountPrivacy.js';
import {searchDigest,verifiedSearchResult} from './onlineSearch.js';

export const ACCOUNT='a'.repeat(32), NOW=2000000000;
export const RESOURCE={accountId:'272760294910ef0b246980278aeb36e2',
  databaseId:'17043cb7-5dab-4a6f-84ca-19ae1c14cc05',bucket:'vision-community-staging'};
export const hash=raw=>createHash('sha256').update(raw).digest();
export function treeFixture(count=3) {
  const header={version:1,scope:'operator-sealed-scene-membership-v1',environment:'staging',resource:RESOURCE,
    lane:'scene',policyId:'synthetic-membership',runtimeSha256:'b'.repeat(64),snapshotSha256:'c'.repeat(64),
    locations:count,rootSha256:'0'.repeat(64)};
  const members=Array.from({length:count},(_,i)=>({sourceIndex:i,locationId:80+i,outputSha256:'d'.repeat(64),
    pose:{lat:10+i*2,lng:20,heading:90,pitch:0,zoom:0,panoId:'synthetic-scene-'+i,
      capture:'2026-10',country:i?'Italy':'Côte d’Ivoire',cameraGeneration:'gen1'}}));
  const context=Buffer.from(JSON.stringify(['vision-contributed-scene-member-v1','staging','scene',
    header.policyId,header.runtimeSha256,header.snapshotSha256,count]));
  const raw=members.map(m=>JSON.stringify(m));
  const levels=[raw.map(row=>hash(Buffer.concat([Buffer.from([0]),context,Buffer.from('\n'+row)])))];
  while(levels.at(-1).length>1) {
    const prior=levels.at(-1),next=[];
    for(let i=0;i<prior.length;i+=2) next.push(hash(Buffer.concat([Buffer.from([1]),prior[i],prior[i+1]??prior[i]])));
    levels.push(next);
  }
  header.rootSha256=levels.at(-1)[0].toString('hex');
  const proof=i=>{let index=i;const siblings=[];for(const level of levels.slice(0,-1)){
    siblings.push(level[(index^1)<level.length?(index^1):index].toString('hex'));index=Math.floor(index/2);
  }return{memberJson:raw[i],siblings};};
  return {header,members,proof};
}
export function queryFixture() {
  return {lane:'scene',prompt:'red door',examples:[],excluded:[],queryName:'My map',descriptionWeight:100,
    viewDirection:'bestOfFour',resultCount:3,maxPerCountry:25,filters:{mode:'all',countries:[],generations:[]},
    objectConfidence:'balanced',rejectRoadNames:false,minimumGlobalLocation:null};
}
export function packetFixture(tree,requestSha256) {
  return {contractVersion:2,policyId:tree.header.policyId,runtimeSha256:tree.header.runtimeSha256,
    snapshotSha256:tree.header.snapshotSha256,requestSha256,processedLocations:tree.header.locations,
    hits:tree.members.slice(0,3).map((m,i)=>({locationId:m.locationId,outputSha256:m.outputSha256,
      sourceIndex:m.sourceIndex,score:.9-i*.1,viewOffset:1})),
    membership:tree.members.slice(0,3).map((_,i)=>tree.proof(i))};
}
export async function accountingFixture(tree=treeFixture()) {
  const sql=new DatabaseSync(':memory:'),queries=[];
  sql.exec(readFileSync(new URL('../schema.sql',import.meta.url),'utf8'));
  sql.exec('ALTER TABLE pose_catalog ADD COLUMN assignee TEXT; ALTER TABLE pose_catalog ADD COLUMN assigned_at INTEGER;');
  const db={prepare(query){queries.push(query);const statement=(args=[])=>({bind:(...v)=>statement(v),
    first:async()=>sql.prepare(query).get(...args)||null,all:async()=>({results:sql.prepare(query).all(...args)}),
    run:async()=>statement(args).execute(),execute:()=>({meta:{changes:Number(sql.prepare(query).run(...args).changes)}})
  });return statement();},async batch(statements){sql.exec('BEGIN IMMEDIATE');try{
    const rows=statements.map(s=>s.execute());sql.exec('COMMIT');return rows;
  }catch(error){sql.exec('ROLLBACK');throw error;}}};
  await migrateAccountPrivacy({DB:db});sql.exec(readFileSync(new URL('../search-queue.sql',import.meta.url),'utf8'));
  sql.prepare('INSERT INTO accounts(id,token_hash,units) VALUES(?,?,?)').run(ACCOUNT,'fictional-account-token',200);
  sql.prepare('INSERT INTO ledger(account_id,units,reason,reference) VALUES(?,?,?,?)').run(ACCOUNT,200,'fixture-only','fictional-starting-credit');
  const env={DB:db,DEPLOYMENT_ENVIRONMENT:tree.header.environment,INDEX_BUCKET_NAME:tree.header.resource.bucket,SEARCH_DELIVERY:'queued-v1',
    SEARCH_AGENT_SECRET:'f'.repeat(64),SEARCH_COST_UNITS:'100',SEARCH_POLICY_ID:tree.header.policyId,
    SEARCH_RUNTIME_SHA256:tree.header.runtimeSha256,SEARCH_SNAPSHOT_SHA256:tree.header.snapshotSha256,
    SEARCH_SCENE_MEMBERSHIP:JSON.stringify(tree.header)};
  const query=queryFixture(),key=`q1.${NOW}.`+'1'.repeat(32);
  const enqueue=(options={})=>queueSearch(env,ACCOUNT,key,query,{now:NOW,maxCostUnits:100,...options});
  const claim=()=>claimQueuedSearch(env,NOW+1,['scene']);
  const complete=(job,packet,now=NOW+2)=>completeQueuedSearch(env,job.jobId,job.claimToken,packet,now);
  return {sql,queries,env,query,key,enqueue,claim,complete,tree};
}

export async function interop(document) {
  const f=await accountingFixture({header:document.header});
  try {
    const query=JSON.parse(document.rawQuery);Object.assign(f.query,query);
    const digest=await searchDigest(f.query),result=document.packet;
    if(result.requestSha256!==digest.slice(7))throw Error('interop_query_fingerprint');
    const response=await verifiedSearchResult(f.env,f.query,digest,result,document.header.snapshotSha256,'test-result',100);
    if(response.results.length!==result.hits.length)throw Error('interop_count');
    await f.enqueue();const {job}=await f.claim();await f.complete(job,result);await f.complete(job,result);
    const counts=f.sql.prepare("SELECT (SELECT units FROM accounts WHERE id=?) AS units,(SELECT COUNT(*) FROM ledger WHERE reason='search') AS debits").get(ACCOUNT);
    if(counts.units!==100||counts.debits!==1||f.queries.some(q=>/FROM published_index i/.test(q)))throw Error('interop_accounting');
    await deleteAccount(f.env,ACCOUNT,{accountId:ACCOUNT,idempotencyKey:'e'.repeat(64),confirmation:'DELETE'},NOW+3);
    let refused=false;try{await f.complete(job,result,NOW+4);}catch(error){refused=error.code==='search_claim_lost';}
    if(!refused)throw Error('interop_deletion');
    return {status:'SEALED_SCENE_MEMBERSHIP_INTEROP_PASSED',results:response.results.length,
      catalogLookups:0,onceOnlyDebits:1,deletionFences:1,synthetic:true,liveReady:false};
  }finally{f.sql.close();}
}
