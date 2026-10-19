// Synthetic local fixture only. Existing private runtimes; no cloud or native calls.
import {writeFileSync} from 'node:fs';
import {qualifiedFixture,ACCOUNT} from '../../src/qualifiedObject.fixture.mjs';
import {objectWorkFixture} from '../../src/objectWork.fixture.mjs';
import {deleteAccount} from '../../src/accountPrivacy.js';
const [destination,mode='published']=process.argv.slice(2);
if(!destination||!['prepared','work-prepared','work-ready','work-published','staged','published','deleted'].includes(mode))throw Error('invalid_synthetic_export');
const f=mode.startsWith('work-')?await objectWorkFixture(null,{file:destination}):await qualifiedFixture(null,{file:destination});
try {
  if(['work-ready','work-published'].includes(mode))await f.claim();
  if(!['prepared','work-prepared','work-ready'].includes(mode))await f.stage();
  if(mode==='work-published')await f.settle();
  if(['published','deleted'].includes(mode))await f.settle();
  if(mode==='deleted')await deleteAccount(f.env,ACCOUNT,{accountId:ACCOUNT,idempotencyKey:'8'.repeat(64),confirmation:'DELETE'},Math.floor(Date.now()/1000));
  if(mode==='published') {
    // An earlier independently synthetic award and already paid exact reply.
    f.sql.prepare("INSERT INTO ledger(account_id,units,reason,reference) VALUES (?,100000,'verified_work','lease:synthetic-earlier-work')").run(ACCOUNT);
    f.sql.prepare('UPDATE accounts SET units=units+100000 WHERE id=?').run(ACCOUNT);
    f.sql.prepare("INSERT INTO ledger(account_id,units,reason,reference) VALUES (?,-100000,'search',?)").run(ACCOUNT,'search:'+'c'.repeat(32));
    f.sql.prepare('UPDATE accounts SET units=units-100000 WHERE id=?').run(ACCOUNT);
    f.sql.prepare('INSERT INTO searches VALUES (?,?,?,?,?)').run('c'.repeat(32),ACCOUNT,'synthetic-private-retry',
      'sha256:'+'d'.repeat(64),JSON.stringify({searchId:'c'.repeat(32),privateResult:'synthetic exact saved reply'}));
  }
  if(['prepared','work-prepared'].includes(mode)) {
    const schema=f.sql.prepare("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY rowid").all();
    const tables=schema.filter(r=>r.type==='table').map(r=>({name:r.name,rows:f.sql.prepare(`SELECT * FROM ${r.name}`).all()}));
    writeFileSync(destination+'.json',JSON.stringify({schema,tables,index:f.index,authority:f.authority,
      qualificationPolicy:f.env.OBJECT_QUALIFICATION_POLICY,eligibilityPolicy:f.env.OBJECT_ELIGIBILITY_POLICY,
      eligibilitySha256:f.env.OBJECT_ELIGIBILITY_POLICY_SHA256,proof:f.proof({}),now:f.now,workBody:f.body}),{flag:'wx'});
  }
  process.stdout.write(JSON.stringify({synthetic:true,nativeInference:false,liveCalls:0,mode}));
}finally{f.sql.close();}
