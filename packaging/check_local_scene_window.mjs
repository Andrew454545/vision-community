// Execute the shipped inline script against both private export response types.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const page = fs.readFileSync(process.argv[2], 'utf8');
const script = page.match(/<script nonce="[^"]+">([\s\S]*?)<\/script>/)[1];
for (const mode of ['readiness', 'collection']) {
  const elements = new Map();
  const element = id => {
    if (!elements.has(id)) elements.set(id, {value:'', disabled:false, hidden:true,
      checked:false, textContent:'', click(){}, remove(){}});
    return elements.get(id);
  };
  let downloads = 0;
  const status = {phase:'complete', participant:'test', total:128, completed:128,
    message:'Saved', outputDirectory:'/private/work', exportAvailable:true,
    readiness:mode==='readiness', campaign:mode==='collection', startupEnabled:true,
    settings:{dayPace:'medium', nightPace:'max', dayStart:'06:00', nightStart:'00:00', pauseOnBattery:true}};
  const requests = [];
  const context = vm.createContext({
    location:{hash:'#test-token',pathname:'/'},history:{replaceState(){}},
    document:{getElementById:element, querySelectorAll:()=>[],body:{appendChild(){}},
      createElement:()=>({click(){downloads++;},remove(){}})},
    URL:{createObjectURL(){return 'blob:local';},revokeObjectURL(){}},
    setInterval(){},setTimeout(){},
    async fetch(path, options) {
      assert.equal(options.headers.Authorization, 'Bearer test-token');
      requests.push(path);
      if (path==='/api/status') return {ok:true,json:async()=>status};
      if (path==='/api/export') return {ok:true,
        headers:{get:()=>mode==='collection'?'application/json':'application/zip'},
        json:async()=>({kind:'local_directory',locations:128,path:'/private/exports'}),
        blob:async()=>{assert.equal(mode,'readiness','campaign must never buffer all results');return {};}};
      throw Error('unexpected request');
    },
  });
  vm.runInContext(script, context, {timeout:1000});
  await new Promise(setImmediate);
  assert.equal(element('save').disabled,false);
  if (mode==='readiness') assert.match(element('intro').textContent,/112 fixed/);
  else assert.equal(element('startup').checked,true);
  await element('save').onclick();
  assert.equal(downloads,mode==='readiness'?1:0);
  assert.match(element('backup-message').textContent,mode==='readiness'?/browser downloads/:/128.*\/private\/exports/);
  assert.equal(requests.filter(p=>p==='/api/export').length,1);
}
console.log('Local Scene window: readiness ZIP and bounded campaign folder export passed.');
