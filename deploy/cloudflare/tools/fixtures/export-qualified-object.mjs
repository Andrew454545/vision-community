// Synthetic local fixture only. Existing private runtimes; no cloud or native calls.
import {writeFileSync} from 'node:fs';
import {qualifiedFixture,ACCOUNT} from '../../src/qualifiedObject.fixture.mjs';
import {deleteAccount} from '../../src/accountPrivacy.js';
const [destination,mode='published']=process.argv.slice(2);
if(!destination||!['prepared','staged','published','deleted'].includes(mode))throw Error('invalid_synthetic_export');
const f=await qualifiedFixture(null,{file:destination});
try {
  if(mode!=='prepared')await f.stage();
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
  if(mode==='prepared') {
    const schema=f.sql.prepare("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY rowid").all();
    const tables=schema.filter(r=>r.type==='table').map(r=>({name:r.name,rows:f.sql.prepare(`SELECT * FROM ${r.name}`).all()}));
    writeFileSync(destination+'.json',JSON.stringify({schema,tables,index:f.index,authority:f.authority,
      qualificationPolicy:f.env.OBJECT_QUALIFICATION_POLICY,eligibilityPolicy:f.env.OBJECT_ELIGIBILITY_POLICY,
      eligibilitySha256:f.env.OBJECT_ELIGIBILITY_POLICY_SHA256,proof:f.proof({}),now:f.now}),{flag:'wx'});
  }
  process.stdout.write(JSON.stringify({synthetic:true,nativeInference:false,liveCalls:0,mode}));
}finally{f.sql.close();}
