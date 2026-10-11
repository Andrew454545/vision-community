// Synthetic inference only; actual SQLite/privacy/transport coordination.
import assert from 'node:assert/strict';
import test from 'node:test';
import {DatabaseSync} from 'node:sqlite';
import {prepareDatabase} from '../tools/initialize-schema.mjs';
import {prepareObjectAuditDispatch} from '../tools/prepare-object-audit-dispatch.mjs';
import {sqliteD1} from '../tools/sqlite-d1.mjs';
import {stageObjectAudit,advanceObjectAudit} from './objectAuditDispatch.js';
import {objectAuditResult} from '../native-object-verifier-bridge/worker.js';
import {sha256Hex,encodeUtf8} from './model.js';
import {syntheticR2} from './syntheticR2.mjs';
import {deleteAccount,cleanupAccountArtifacts} from './accountPrivacy.js';
import {COVERAGE_VALIDATOR} from './objectCoverage.js';
import {PRIVACY_FENCE} from './artifactWrites.js';
import worker from './worker.js';
const account='a'.repeat(32),lease='b'.repeat(32),other='c'.repeat(32),job='d'.repeat(32),token='synthetic-session';
const now=100000,source=encodeUtf8('synthetic source\n');
const objectIndex={manifest:{synthetic:true},files:{'synthetic.bin':''},sourceTsv:Buffer.from(source).toString('base64')};
async function setup(t,install=true) {
  const sql=new DatabaseSync(':memory:');t.after(()=>sql.close());
  const objects=new Map(),r2=syntheticR2(objects);
  const env={DB:sqliteD1(sql),INDEX:{...r2,async get(key){
    const object=await r2.get(key);return object?{...object,body:new Response(await object.arrayBuffer()).body}:null;
  }}};
  await prepareDatabase(env.DB);if(install) await prepareObjectAuditDispatch(env.DB);
  sql.prepare('INSERT INTO accounts(id,token_hash,units) VALUES (?,?,10)').run(account,await sha256Hex(encodeUtf8(token)));
  sql.prepare('INSERT INTO accounts(id,token_hash,units) VALUES (?,?,10)').run(other,'synthetic-other');
  sql.prepare("INSERT INTO leases(id,account_id,lane,state,expires_at) VALUES (?,?,'object','active',?)").run(lease,account,now+1000);
  sql.prepare("INSERT INTO locations(id,asset_id,capture,lane,model,state,active_lease,camera_generation) VALUES (1,'synthetic','fixture','object','synthetic','leased',?,'gen4')").run(lease);
  sql.prepare('INSERT INTO lease_items VALUES (?,1)').run(lease);
  sql.prepare('INSERT INTO object_coverage VALUES (?,?,?,?)').run(1,COVERAGE_VALIDATOR,'f'.repeat(64),now);
  const authority={leaseId:lease,profileId:'1'.repeat(64),policyId:'staging.synthetic',assignmentSha256:'2'.repeat(64),sourceSha256:await sha256Hex(source)};
  const row=()=>sql.prepare('SELECT * FROM object_audit_candidates WHERE lease_id=?').get(lease);
  const reply=(changes={})=>({version:1,jobId:job,leaseId:lease,profileId:authority.profileId,policyId:authority.policyId,
    assignmentSha256:authority.assignmentSha256,submissionSha256:row().submission_sha256,candidateManifestSha256:'3'.repeat(64),
    state:'queued',decision:'pending',attempts:0,retryAt:0,receiptSha256:null,serverAuthorization:false,productionQualified:false,
    acceptedContributions:0,searchCreditsCreated:0,...changes});
  const stage=()=>stageObjectAudit(env,account,authority,structuredClone(objectIndex),now);
  const destroy=()=>deleteAccount(env,account,{accountId:account,confirmation:'DELETE',idempotencyKey:'4'.repeat(64)},now+1);
  return {sql,env,objects,authority,row,reply,stage,destroy};
}
test('explicit optional setup is required; ordinary requests never install its schema',async t=>{
  const {sql,env,authority}=await setup(t,false);
  await assert.rejects(stageObjectAudit(env,account,authority,objectIndex,now),{message:'object_dispatch_setup_required',status:503});
  assert.equal(sql.prepare("SELECT count(*) AS n FROM sqlite_master WHERE name LIKE 'object_dispatch_%'").get().n,0);
  await prepareObjectAuditDispatch(env.DB);await prepareObjectAuditDispatch(env.DB);
  assert.equal(sql.prepare('SELECT count(*) AS n FROM object_dispatch_revision').get().n,1);
  sql.exec("UPDATE object_dispatch_revision SET contract='future'");
  await assert.rejects(prepareObjectAuditDispatch(env.DB));
  assert.equal(sql.prepare('SELECT contract FROM object_dispatch_revision').get().contract,'future');
});
test('upload intent precedes storage and staging reserves the assignment atomically without credit',async t=>{
  const {sql,env,row,stage}=await setup(t),put=env.INDEX.put;
  env.INDEX.put=async(...args)=>{
    assert.equal(sql.prepare('SELECT count(*) AS n FROM account_artifact_writes').get().n,1);
    assert.equal(row(),undefined);return put(...args);
  };
  const result=await stage();assert.equal(result.accepted,0);assert.equal(result.pending,1);assert.equal(result.unitsEarned,0);
  assert.equal(row().state,'pending');assert.equal(row().job_id,null);
  assert.deepEqual({...sql.prepare('SELECT state,queue_state,active_lease,lease_until FROM locations').get()},
    {state:'pending',queue_state:'quarantined',active_lease:lease,lease_until:null});
  assert.equal(sql.prepare('SELECT state FROM leases').get().state,'submitted');
  assert.equal(sql.prepare('SELECT units FROM accounts WHERE id=?').get(account).units,10);
  assert.equal(sql.prepare('SELECT count(*) AS n FROM ledger').get().n,0);
  assert.equal((await stage()).freshAuditReply,false);
  assert.equal(sql.prepare('SELECT count(*) AS n FROM object_audit_candidates').get().n,1);
});
test('exact replay is stable and a changed payload or authority cannot reinterpret the saved candidate',async t=>{
  const {env,authority,stage}=await setup(t);await stage();
  for(const changes of [{profileId:'5'.repeat(64)},{assignmentSha256:'5'.repeat(64)},{policyId:'different'}]) {
    await assert.rejects(stageObjectAudit(env,account,{...authority,...changes},objectIndex,now),{message:'object_candidate_conflict'});
  }
  await assert.rejects(stageObjectAudit(env,account,authority,{...objectIndex,manifest:{changed:true}},now),{message:'object_candidate_conflict'});
  await assert.rejects(stageObjectAudit(env,other,authority,objectIndex,now),{message:'lease_lost'});
});
test('expired, wrong-lane, stale/future/nonofficial and changed assignments cannot be staged',async t=>{
  for(const damage of [
    sql=>sql.exec('UPDATE leases SET expires_at=1'),sql=>sql.exec("UPDATE leases SET lane='scene'"),
    sql=>sql.exec('DELETE FROM object_coverage'),sql=>sql.exec('UPDATE object_coverage SET validated_at=1'),
    sql=>sql.exec('UPDATE object_coverage SET validated_at=100001'),sql=>sql.exec("UPDATE locations SET camera_generation='gen3'"),
    sql=>sql.exec("UPDATE object_coverage SET validator='old-v1'"),sql=>sql.exec("UPDATE locations SET state='published'")]) {
    const {sql,stage,objects}=await setup(t);damage(sql);await assert.rejects(stage());assert.equal(objects.size,0);
  }
});
test('ownership and coverage changed during R2 upload refuse the atomic reservation',async t=>{
  for(const damage of [sql=>sql.exec("UPDATE locations SET active_lease=NULL"),sql=>sql.exec('DELETE FROM object_coverage')]) {
    const {sql,env,stage,row}=await setup(t),put=env.INDEX.put;
    env.INDEX.put=async(...args)=>{const value=await put(...args);damage(sql);return value;};
    await assert.rejects(stage(),{message:'lease_lost'});assert.equal(row(),undefined);
    assert.equal(sql.prepare('SELECT state FROM leases').get().state,'active');
  }
});
test('late reservation failure rolls back location and lease state; the owned upload can replay',async t=>{
  const {sql,stage,row}=await setup(t);
  sql.exec("CREATE TRIGGER fail_stage BEFORE UPDATE ON leases WHEN NEW.state='submitted' BEGIN SELECT RAISE(ABORT,'injected_failure'); END");
  await assert.rejects(stage(),/injected_failure/);assert.equal(row(),undefined);
  assert.equal(sql.prepare('SELECT state FROM locations').get().state,'leased');
  sql.exec('DROP TRIGGER fail_stage');assert.equal((await stage()).pending,1);
});
test('lost start acknowledgement retries identical content and recovers the same job; subsequent delivery uses GET',async t=>{
  const {env,row,reply,stage}=await setup(t);await stage();let posts=0,gets=0,body;
  env.OBJECT_VERIFIER={async fetch(request){
    assert.equal(request.headers.get('authorization'),null);assert.equal(request.headers.get('cookie'),null);
    if(request.method==='POST') {
      posts++;const next=await request.text();if(body)assert.equal(next,body);body=next;
      if(posts===1)throw Error('lost private acknowledgement');
    } else {gets++;assert.equal(request.url,'https://object-verifier.internal/object-audits/'+job);}
    return Response.json(reply());
  }};
  assert.equal((await advanceObjectAudit(env,account,lease,now)).retryAt,now+30);
  assert.equal(row().job_id,null);assert.equal((await advanceObjectAudit(env,account,lease,now+29)).freshAuditReply,false);
  assert.equal(posts,1);assert.equal((await advanceObjectAudit(env,account,lease,now+30)).freshAuditReply,true);
  assert.equal(row().job_id,job);assert.equal(row().transport_failures,0);
  await advanceObjectAudit(env,account,lease,now+60);assert.equal(posts,2);assert.equal(gets,1);
  assert.equal(JSON.parse(body).submissionSha256,await sha256Hex(encodeUtf8(JSON.stringify(objectIndex))));
});
test('one persisted claim wins concurrent starts and survives an interrupted handler',async t=>{
  const {sql,env,row,reply,stage}=await setup(t);await stage();let complete,calls=0;
  env.OBJECT_VERIFIER={fetch(){calls++;return new Promise(resolve=>{complete=resolve;});}};
  const first=advanceObjectAudit(env,account,lease,now);
  while(!complete)await new Promise(resolve=>setTimeout(resolve,1));
  assert.equal((await advanceObjectAudit(env,account,lease,now)).freshAuditReply,false);assert.equal(calls,1);
  complete(Response.json(reply()));await first;
  sql.prepare('UPDATE object_audit_candidates SET job_id=job_id,claim_token=?,claim_until=?,next_attempt=0').run('9'.repeat(32),now+90);
  env.OBJECT_VERIFIER={fetch(){calls++;return Response.json(reply());}};
  assert.equal((await advanceObjectAudit(env,account,lease,now+60)).freshAuditReply,false);
  assert.equal((await advanceObjectAudit(env,account,lease,now+90)).freshAuditReply,true);
  assert.equal(row().claim_token,null);
});
test('every identity, manifest pin and response authority flag is checked before retaining approval',async t=>{
  const {env,row,reply,stage}=await setup(t);await stage();
  env.OBJECT_VERIFIER={fetch:()=>Response.json(reply())};await advanceObjectAudit(env,account,lease,now);
  for(const change of [{jobId:'9'.repeat(32)},{leaseId:other},{profileId:'9'.repeat(64)},
    {policyId:'different'},{assignmentSha256:'9'.repeat(64)},{submissionSha256:'9'.repeat(64)},
    {candidateManifestSha256:'9'.repeat(64)},{productionQualified:true},{acceptedContributions:1},
    {receiptSha256:null,state:'approved',decision:'approved',attempts:1},{privatePath:'forbidden'}]) {
    env.OBJECT_VERIFIER={fetch:()=>Response.json(reply(change))};
    const result=await advanceObjectAudit(env,account,lease,row().next_attempt);
    assert.equal(result.freshAuditReply,false);assert.equal(row().native_state,'queued');
    // Independent cases retain the original failure observation via the return,
    // then allow the next malformed reply to run without exhausting this fixture.
    const failures=row().transport_failures;assert.ok(failures>0);
    row(); // A result must never carry native paths or caller-owned fields.
    assert.equal(result.accepted,0);
    // Explicit fixture operator reset, not application automatic native retry.
    await env.DB.prepare('UPDATE object_audit_candidates SET transport_failures=0').run();
  }
});
test('fresh approval is only an audit result; cached approval cannot create or replay production acceptance',async t=>{
  const {sql,env,reply,stage}=await setup(t);await stage();let calls=0;
  env.OBJECT_VERIFIER={fetch(){calls++;return Response.json(reply({state:'approved',decision:'approved',attempts:1,receiptSha256:'6'.repeat(64)}));}};
  const first=await advanceObjectAudit(env,account,lease,now);assert.equal(first.auditState,'approved');assert.equal(first.freshAuditReply,true);
  assert.equal(first.accepted,0);assert.equal(first.unitsEarned,0);assert.equal(first.productionQualified,false);
  assert.equal((await advanceObjectAudit(env,account,lease,now+1)).freshAuditReply,false);assert.equal(calls,1);
  assert.equal((await stage()).freshAuditReply,false);
  env.OBJECT_VERIFIER={fetch:()=>Response.json({error:'object_job_origin_unavailable'},{status:503})};
  assert.equal((await advanceObjectAudit(env,account,lease,now+30)).freshAuditReply,false);
  assert.equal(sql.prepare('SELECT count(*) AS n FROM published_index').get().n,0);
  assert.equal(sql.prepare('SELECT count(*) AS n FROM ledger').get().n,0);
});
test('rejection/cancellation release quarantined locations and never allow revival',async t=>{
  for(const state of ['rejected','cancelled','erasing','erased']) {
    const {sql,env,row,reply,stage}=await setup(t);await stage();
    env.OBJECT_VERIFIER={fetch:()=>Response.json(reply({state,decision:state==='rejected'?state:'pending',
      attempts:1,receiptSha256:state==='rejected'?'6'.repeat(64):null}))};
    await advanceObjectAudit(env,account,lease,now);
    assert.equal(row().state,state==='rejected'?'rejected':'cancelled');
    assert.deepEqual({...sql.prepare('SELECT state,queue_state,active_lease FROM locations').get()},
      {state:'pending',queue_state:'pending',active_lease:null});
    assert.throws(()=>sql.exec("UPDATE object_audit_candidates SET state='pending'"),/object_dispatch_immutable/);
  }
});
test('account deletion wins a late start approval and journals native assignment cleanup',async t=>{
  const {sql,env,objects,row,reply,stage,destroy}=await setup(t);await stage();
  env.OBJECT_VERIFIER={async fetch(){const response=Response.json(reply({state:'approved',decision:'approved',attempts:1,receiptSha256:'6'.repeat(64)}));await destroy();return response;}};
  await assert.rejects(advanceObjectAudit(env,account,lease,now),{message:'account_not_active',status:401});
  assert.equal(row().state,'cancelled');assert.equal(row().receipt_sha256,null);assert.equal(row().job_id,null);
  assert.ok(sql.prepare('SELECT 1 FROM account_cleanup WHERE artifact_key=?').get('object-audit-jobs/'+lease));
  env.OBJECT_VERIFIER={fetch:()=>Response.json({version:1,leaseId:lease,policyId:'staging.synthetic',assignmentSha256:'2'.repeat(64),
    state:'erased',serverAuthorization:false,productionQualified:false})};
  await cleanupAccountArtifacts(env,account,64);
  assert.equal(new TextDecoder().decode([...objects.values()][0]),PRIVACY_FENCE);
  await assert.rejects(stage(),{message:'account_not_active',status:401});
  assert.equal(sql.prepare('SELECT units FROM accounts WHERE id=?').get(account).units,0);
});
test('deletion after a rejected audit still revokes credentials and preserves its original audit state',async t=>{
  const {env,row,reply,stage,destroy}=await setup(t);await stage();
  env.OBJECT_VERIFIER={fetch:()=>Response.json(reply({state:'rejected',decision:'rejected',attempts:1,receiptSha256:'6'.repeat(64)}))};
  await advanceObjectAudit(env,account,lease,now);await destroy();
  assert.equal(row().state,'cancelled');assert.equal(row().native_state,'rejected');
});
test('corrupt/fenced/stalled payload or response and late responses leave bounded durable retries',async t=>{
  for(const damage of [
    s=>s.objects.set(s.row().artifact_key,encodeUtf8('corrupt')),
    s=>{s.env.INDEX.get=async()=>new Promise(()=>{});},
    s=>{s.env.OBJECT_VERIFIER.fetch=()=>new Response(new Uint8Array(65537),{headers:{'content-type':'application/json'}});},
    s=>{s.env.OBJECT_VERIFIER.fetch=()=>new Response(new ReadableStream({pull(){return new Promise(()=>{});}}),{headers:{'content-type':'application/json'}});},
    s=>{s.env.OBJECT_VERIFIER.fetch=()=>new Promise(()=>{});},
  ]) {
    const s=await setup(t);await s.stage();s.env.OBJECT_VERIFIER={fetch:()=>Response.json(s.reply())};damage(s);
    const result=await advanceObjectAudit(s.env,account,lease,now,10);
    assert.equal(result.freshAuditReply,false);assert.equal(s.row().transport_failures,1);assert.equal(s.row().claim_token,null);
    assert.equal(s.row().last_error,'object_audit_transport_unavailable');
  }
});
test('backoff and transport failures are finite; clock rollback cannot trap a saved claim indefinitely',async t=>{
  const {sql,env,row,stage}=await setup(t);await stage();let calls=0;
  env.OBJECT_VERIFIER={fetch(){calls++;throw Error('private token and path must not be retained');}};
  for(let i=0;i<8;i++)await advanceObjectAudit(env,account,lease,row().next_attempt || now);
  assert.equal(calls,8);assert.equal((await advanceObjectAudit(env,account,lease,row().next_attempt)).needsAttention,true);
  assert.equal(calls,8);assert.equal(row().last_error,'object_audit_transport_unavailable');
  sql.prepare('UPDATE object_audit_candidates SET transport_failures=0,claim_token=?,claim_until=?,next_attempt=?')
    .run('9'.repeat(32),now+99999,now+99999);
  await advanceObjectAudit(env,account,lease,now);assert.equal(calls,9);assert.equal(row().claim_token,null);
});
test('the ordinary upload replay reports pending Object quarantine, never accepted work',async t=>{
  const {env,stage}=await setup(t);await stage();
  const response=await worker.fetch(new Request('https://community.test/api/submissions',{method:'POST',
    headers:{authorization:'Bearer '+token,'content-type':'application/json'},body:JSON.stringify({leaseId:lease,outputs:[]})}),env);
  assert.equal(response.status,200);const result=await response.json();
  assert.equal(result.accepted,0);assert.equal(result.unitsEarned,0);assert.equal(result.pendingAudit,true);assert.equal(result.pending,1);
});

test('an altered deletion fence cannot receive the optional ready checkpoint',async t=>{
  const {sql,env}=await setup(t);
  sql.exec('DROP TRIGGER object_dispatch_deleted');
  sql.exec("CREATE TRIGGER object_dispatch_deleted AFTER UPDATE OF deleted_at ON accounts BEGIN SELECT 1; END");
  await assert.rejects(prepareObjectAuditDispatch(env.DB));
  assert.match(sql.prepare("SELECT sql FROM sqlite_master WHERE name='object_dispatch_deleted'").get().sql,/SELECT 1/);
});
test('expired/revoked assignments release quarantine and cannot accept a delayed saved approval',async t=>{
  const {sql,env,row,reply,stage}=await setup(t);await stage();
  env.OBJECT_VERIFIER={async fetch(){sql.exec("UPDATE leases SET state='expired'");return Response.json(reply({state:'approved',decision:'approved',attempts:1,receiptSha256:'6'.repeat(64)}));}};
  const result=await advanceObjectAudit(env,account,lease,now);
  assert.equal(result.freshAuditReply,false);assert.equal(row().state,'cancelled');assert.equal(row().job_id,null);
  assert.deepEqual({...sql.prepare('SELECT state,queue_state,active_lease FROM locations').get()},
    {state:'pending',queue_state:'pending',active_lease:null});
});
test('an existing approval receipt cannot be replaced by a different cached proof or older native attempt',async t=>{
  const {env,row,reply,stage}=await setup(t);await stage();
  env.OBJECT_VERIFIER={fetch:()=>Response.json(reply({state:'approved',decision:'approved',attempts:2,receiptSha256:'6'.repeat(64)}))};
  await advanceObjectAudit(env,account,lease,now);
  for(const changes of [{receiptSha256:'7'.repeat(64)},{attempts:1},{state:'running',decision:'pending'}]) {
    env.OBJECT_VERIFIER={fetch:()=>Response.json(reply({state:'approved',decision:'approved',attempts:2,receiptSha256:'6'.repeat(64),...changes}))};
    assert.equal((await advanceObjectAudit(env,account,lease,row().next_attempt)).freshAuditReply,false);
    assert.equal(row().receipt_sha256,'6'.repeat(64));assert.equal(row().native_attempts,2);
  }
});
test('a native reply after the handler deadline is cancelled and cannot mutate the outbox',async t=>{
  const {env,row,stage}=await setup(t);await stage();let complete,cancelled=false;
  env.OBJECT_VERIFIER={fetch:()=>new Promise(resolve=>{complete=resolve;})};
  const result=await advanceObjectAudit(env,account,lease,now,5);assert.equal(result.freshAuditReply,false);
  complete(new Response(new ReadableStream({cancel(){cancelled=true;}}),{headers:{'content-type':'application/json'}}));
  await new Promise(resolve=>setTimeout(resolve,5));assert.equal(cancelled,true);assert.equal(row().job_id,null);
});
test('eight retained pending assignments bound capacity before extra storage; no inference retry is dispatched',async t=>{
  const {sql,env,objects,authority,stage}=await setup(t);await stage();
  for(let i=2;i<=9;i++) {
    const next=i.toString(16).padStart(32,'0');
    sql.prepare("INSERT INTO leases(id,account_id,lane,state,expires_at) VALUES (?,?,'object','active',?)").run(next,account,now+1000);
    sql.prepare("INSERT INTO locations(id,asset_id,capture,lane,model,state,active_lease,camera_generation) VALUES (?,?,'fixture','object','synthetic','leased',?,'gen4')").run(i,'synthetic-'+i,next);
    sql.prepare('INSERT INTO lease_items VALUES (?,?)').run(next,i);
    sql.prepare('INSERT INTO object_coverage VALUES (?,?,?,?)').run(i,COVERAGE_VALIDATOR,'f'.repeat(64),now);
    const call=()=>stageObjectAudit(env,account,{...authority,leaseId:next},objectIndex,now);
    if(i===9)await assert.rejects(call(),{message:'object_dispatch_capacity',status:503});else await call();
  }
  assert.equal(objects.size,8);assert.equal(sql.prepare('SELECT count(*) AS n FROM object_audit_candidates').get().n,8);
  assert.equal(sql.prepare('SELECT count(*) AS n FROM ledger').get().n,0);
});
test('a pending Scene retry also reports audit waiting, never the number of leased items as accepted',async t=>{
  const {sql,env}=await setup(t);
  sql.exec("UPDATE leases SET lane='scene',state='submitted';UPDATE locations SET lane='scene',state='pending',queue_state='quarantined',active_lease=NULL");
  sql.prepare("INSERT INTO scene_qualifications VALUES (?,?,?,'staging.synthetic',?,999999,1)").run('8'.repeat(32),account,'1'.repeat(64),'2'.repeat(64));
  sql.prepare("INSERT INTO scene_candidates VALUES (?,?,?,'staging.synthetic',?,'synthetic-private','[]',1,'pending')")
    .run(lease,account,'8'.repeat(32),'3'.repeat(64));
  const response=await worker.fetch(new Request('https://community.test/api/submissions',{method:'POST',
    headers:{authorization:'Bearer '+token,'content-type':'application/json'},body:JSON.stringify({leaseId:lease,outputs:[]})}),env);
  assert.equal(response.status,200);const result=await response.json();assert.equal(result.accepted,0);assert.equal(result.pending,1);
});
