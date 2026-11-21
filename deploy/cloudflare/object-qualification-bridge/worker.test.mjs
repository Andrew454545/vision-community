import assert from 'node:assert/strict';
import test from 'node:test';
import bridge, {handleObjectQualification,MAX_REQUEST,MAX_RESPONSE} from './worker.js';
import {policy,evidence} from '../tools/fixtures/object-qualification-proof.mjs';

const p=policy(),at=()=>Math.floor(Date.now()/1000);
const body={version:1,accountId:'a'.repeat(32),requestId:'b'.repeat(32),challenge:'e'.repeat(32),
  profileId:Object.keys(p.profiles)[0],artifactSetSha256:'f'.repeat(64),policyId:p.policyId,policySha256:p.policySha256};
const env={OBJECT_SAMPLE_QUALIFIER_ORIGIN:'https://private-sample.test',OBJECT_SAMPLE_QUALIFIER_SECRET:'s'.repeat(40)};
const proof=()=>evidence(body,p,true,at());
const request=(options={})=>new Request('https://object-qualifier.internal/object-qualifications/evidence',{
  method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body),...options});

test('dedicated bridge delivers only validated identity and private credentials',async()=>{
  const response=await handleObjectQualification(request({headers:{'content-type':'application/json',authorization:'caller',cookie:'private'}}),env,
    async(url,init)=>{
      assert.equal(url,env.OBJECT_SAMPLE_QUALIFIER_ORIGIN+'/object-qualifications/evidence');
      assert.equal(init.headers.authorization,'Bearer '+env.OBJECT_SAMPLE_QUALIFIER_SECRET);
      assert.equal(init.headers.cookie,undefined);assert.equal(init.redirect,'manual');
      assert.deepEqual(JSON.parse(init.body),body);
      return Response.json(proof(),{headers:{'set-cookie':'secret','x-path':'private'}});
    });
  assert.equal(response.status,200);assert.equal((await response.json()).report.qualified,false);
  assert.equal(response.headers.get('set-cookie'),null);assert.equal(response.headers.get('x-path'),null);
  assert.equal(response.headers.get('cache-control'),'no-store');
});

test('incompatible numerical reports remain evidence rather than a transport approval',async()=>{
  const value=evidence(body,p,false,at());
  const response=await handleObjectQualification(request(),env,()=>Response.json(value));
  assert.equal(response.status,200);assert.equal((await response.json()).report.sampleCompatible,false);
});

test('audit credentials, wrong origins and absent dedicated setup cannot contact a host',async()=>{
  for(const changes of [{OBJECT_SAMPLE_QUALIFIER_SECRET:undefined,NATIVE_OBJECT_VERIFIER_SECRET:'s'.repeat(40)},
    {OBJECT_SAMPLE_QUALIFIER_SECRET:'short'},{OBJECT_SAMPLE_QUALIFIER_SECRET:'s'.repeat(257)},
    {OBJECT_SAMPLE_QUALIFIER_ORIGIN:'http://host'},{OBJECT_SAMPLE_QUALIFIER_ORIGIN:'https://user:secret@host'},
    {OBJECT_SAMPLE_QUALIFIER_ORIGIN:'https://host/path'},{OBJECT_SAMPLE_QUALIFIER_ORIGIN:'https://host/?private=1'},
    {OBJECT_SAMPLE_QUALIFIER_ORIGIN:'https://host/#private'}]) {
    assert.equal((await handleObjectQualification(request(),{...env,...changes},()=>assert.fail('contacted'))).status,503);
  }
});

test('qualification is the sole exact private path and has no upload or model route',async()=>{
  for(const [path,method] of [['/qualify','POST'],['/object-audits','POST'],['/object-qualifications/evidence?path=private','POST'],
    ['/object-qualifications/evidence','GET'],['/object-qualifications/evidence#private','POST'],['/object-qualifications/upload','POST']]){
    const input=new Request('https://object-qualifier.internal'+path,{method,...(method==='POST'?{body:'{}'}:{})});
    assert.equal((await handleObjectQualification(input,env,()=>assert.fail('contacted'))).status,404);
  }
});

test('identity, unknown fields and client approval flags are rejected before delivery',async()=>{
  for(const changes of [{path:'private'},{approved:true},{accountId:'short'},{requestId:['b'.repeat(32)]},
    {version:true},{challenge:'short'},{profileId:'short'},{policyId:'bad/path'},{policySha256:'short'}]){
    assert.equal((await handleObjectQualification(request({body:JSON.stringify({...body,...changes})}),env,
      ()=>assert.fail('forwarded'))).status,400);
  }
});

test('duplicate and escaped duplicate fields, invalid UTF8, size and framing cannot reach the host',async()=>{
  for(const input of [request({body:'{"accountId":"another",'+JSON.stringify(body).slice(1)}),
    request({body:'{"\\u0061ccountId":"another",'+JSON.stringify(body).slice(1)}),
    request({body:'not json'}),request({body:new Uint8Array(MAX_REQUEST+1)}),request({body:new Uint8Array([255])}),
    request({headers:{'content-type':'application/json','content-length':'1'}}),
    request({headers:{'content-type':'text/plain'}}),request({headers:{'content-type':'application/json','content-encoding':'gzip'}})]){
    assert.equal((await handleObjectQualification(input,env,()=>assert.fail('forwarded'))).status,400);
  }
});

test('cross-account, job, profile, settings, policy and stale envelopes are unavailable',async()=>{
  for(const changes of [{accountId:'0'.repeat(32)},{requestId:'0'.repeat(32)},{challenge:'0'.repeat(32)},
    {artifactSetSha256:'0'.repeat(64)},{issuedAt:at()-66},{issuedAt:at()+3},{expiresAt:at()},
    {expiresAt:at()+31},{privatePath:'secret'},{artifacts:{...proof().artifacts,indexProfileId:'0'.repeat(64)}},
    {artifacts:{...proof().artifacts,indexSettingsSha256:'0'.repeat(64)}}]){
    assert.equal((await handleObjectQualification(request(),env,()=>Response.json({...proof(),...changes}))).status,503);
  }
});

test('transport cannot fabricate reusable qualification or contribution authority',async()=>{
  for(const changes of [{qualified:true},{serverAuthorization:true},{productionQualified:true},{currentEligibilityVerified:true},
    {inferenceProvenanceVerified:true},{identicalInputBindingVerified:false},{acceptedContributions:1},{searchCreditsCreated:1},
    {qualificationScope:'fixed-input-detector-score-parity-only'},{profileId:'0'.repeat(64)},{policySha256:'0'.repeat(64)},
    {sampleCompatible:false}]){
    const value=proof();value.report={...value.report,...changes};
    assert.equal((await handleObjectQualification(request(),env,()=>Response.json(value))).status,503);
  }
});

test('only bounded busy response is preserved and private upstream errors are sanitized',async()=>{
  const result=await handleObjectQualification(request(),env,()=>Response.json({error:'object_sample_host_busy'},{status:503}));
  assert.deepEqual(await result.json(),{error:'object_sample_host_busy'});
  for(const response of [Response.json({error:'private filesystem path'},{status:503}),
    Response.json({error:'object_sample_host_busy',private:'secret'},{status:503}),
    new Response('private',{status:302,headers:{location:'https://unrelated.test'}})]){
    const response2=await handleObjectQualification(request(),env,()=>response);
    assert.equal(response2.status,503);assert.deepEqual(await response2.json(),{error:'object_sample_host_unavailable'});
  }
});

test('invalid media, oversize, partial replies and endless empty chunks cannot deliver evidence',async()=>{
  for(const response of [new Response('private'),new Response(new Uint8Array(MAX_RESPONSE+1),{headers:{'content-type':'application/json'}}),
    Response.json(proof(),{headers:{'content-length':'1'}}),
    new Response(new ReadableStream({pull(c){c.enqueue(new Uint8Array());}}),{headers:{'content-type':'application/json'}})]){
    assert.equal((await handleObjectQualification(request(),env,()=>response)).status,503);
  }
});

test('deadlines cover request, upstream headers and body; late responses are cancelled',async()=>{
  const stalled=()=>new ReadableStream({pull(){return new Promise(()=>{});}});
  const start=Date.now();
  assert.equal((await handleObjectQualification(request({body:stalled(),duplex:'half'}),env,()=>assert.fail('contacted'),10)).status,400);
  assert.equal((await handleObjectQualification(request(),env,()=>new Promise(()=>{}),10)).status,503);
  assert.equal((await handleObjectQualification(request(),env,()=>new Response(stalled(),{headers:{'content-type':'application/json'}}),10)).status,503);
  let resolve,cancelled=false;
  const pending=handleObjectQualification(request(),env,()=>new Promise(done=>{resolve=done;}),5);
  assert.equal((await pending).status,503);
  resolve(new Response(new ReadableStream({cancel(){cancelled=true;}}),{headers:{'content-type':'application/json'}}));
  await new Promise(done=>setTimeout(done,5));assert.equal(cancelled,true);assert(Date.now()-start<1000);
});

test('rejected upstream framing cancels its body without forwarding private diagnostics',async()=>{
  let cancelled=false;
  const response=new Response(new ReadableStream({cancel(){cancelled=true;}}),{headers:{'content-type':'text/plain'}});
  assert.equal((await handleObjectQualification(request(),env,()=>response)).status,503);
  await new Promise(done=>setTimeout(done,0));assert.equal(cancelled,true);
});

test('default Worker wrapper uses fetch rather than mistaking execution context for transport',async t=>{
  t.mock.method(globalThis,'fetch',()=>Response.json(proof()));
  assert.equal((await bridge.fetch(request(),env,{waitUntil(){}})).status,200);
});
