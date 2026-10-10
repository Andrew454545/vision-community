// Actual offline workerd transport; explicit synthetic provider, no cloud calls.
import assert from 'node:assert/strict';
import {resolve,dirname} from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
const {Miniflare,convertV4MiniflareOptions} = await import(pathToFileURL(resolve(process.argv[2])).href);
const root = dirname(dirname(fileURLToPath(import.meta.url)));
const paths = ['tools/object-audit-jobs.fixture.mjs','native-object-verifier-bridge/worker.js',
  'src/objectAdmission.js','src/objectIndex.js','src/objectFeatures.js','src/model.js'];
const options = {modules:paths.map(path=>({type:'ESModule',path:resolve(root,path)})),
  modulesRoot:root,compatibilityDate:'2026-09-19'};
const mf = new Miniflare(convertV4MiniflareOptions ? convertV4MiniflareOptions(options) : options);
try {
  for (const [mode,status,decision] of [['start',200,'pending'],['status',200,'pending'],['complete',200,'approved'],
    ['cancel',200,'pending'],['retry',200,'pending'],['conflict',409,null],['wrong-id',503,null],
    ['unapproved',503,null],['deadline',503,null]]) {
    const response = await mf.dispatchFetch('https://community.test/'+mode,{signal:AbortSignal.timeout(10000)});
    assert.equal(response.status,200,mode);
    const value = await response.json();
    assert.equal(value.responseStatus,status,mode);
    assert.equal(value.calls,1,mode);
    assert.equal(value.objectAdmissionReady,false,mode);
    assert.equal(value.nativeInferences,0,mode);
    if (decision) assert.equal(value.result.decision,decision,mode);
    else assert.deepEqual(value.result,{error:mode==='conflict'?'object_job_conflict':'object_verifier_unavailable'},mode);
  }
  console.log(JSON.stringify({status:'ACTUAL_WORKERD_OBJECT_JOB_TRANSPORT_PASSED',cases:9,
    syntheticProvider:true,objectAdmissionReady:false,nativeInferences:0,creditsCreated:0}));
} finally { await mf.dispose(); }
