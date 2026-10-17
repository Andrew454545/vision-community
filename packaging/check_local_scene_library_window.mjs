// One shipped-script interaction: open library, filter/search, save MMA JSON.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const page=fs.readFileSync(process.argv[2],'utf8');
const script=page.match(/<script nonce="[^"]+">([\s\S]*?)<\/script>/)[1];
const elements=new Map(),created=[],requests=[];
function node(id='') {return {id,value:'',hidden:true,disabled:false,children:[],textContent:'',style:{},files:[],options:[],selectedIndex:0,
  append(...items){this.children.push(...items);this.options=this.children;if(!this.value&&items[0]?.value)this.value=items[0].value;},replaceChildren(...items){this.children=items;this.options=this.children;},
  click(){this.clicked=true;},focus(){},remove(){}};}
const element=id=>{if(!elements.has(id))elements.set(id,node(id));return elements.get(id);};
const state={locations:112,countries:['France'],generations:['gen2'],path:'/private/library',
  message:'Saved Scenes',busy:false,mapAvailable:true,
  results:[{lat:10,lng:20,heading:123.5,pitch:-2,zoom:1,panoId:'example-pano',
    extra:{tags:['France'],visionCameraGeneration:'gen2',visionScore:0.8}}]};
class LocalURL extends URL {static createObjectURL(){return 'blob:local';}static revokeObjectURL(){}}
const context=vm.createContext({location:{hash:'#private-token',pathname:'/'},history:{replaceState(){}},
  confirm(){return true;},URL:LocalURL,URLSearchParams,setTimeout(){},clearTimeout(){},setInterval(){},
  document:{getElementById:element,querySelectorAll:()=>[],querySelector:()=>element('details'),body:{appendChild(){}},
    createElement(tag){const n=node(tag);created.push(n);return n;}},
  async fetch(path,options){assert.equal(options.headers.Authorization,'Bearer private-token');requests.push([path,options]);
    if(path==='/api/status')return {ok:true,json:async()=>({phase:'ready',participant:'tester',total:112,completed:112,libraryAvailable:true})};
    if(path==='/api/library')return {ok:true,json:async()=>state};
    if(path==='/api/library/search')return {ok:true};
    if(path==='/api/mma/connect')return {ok:true,json:async()=>({connected:true,maps:[{id:'chosen-map',name:'Chosen private map'}]})};
    if(path==='/api/mma/send')return {ok:true,json:async()=>({added:1})};
    if(path==='/api/library/map')return {ok:true,blob:async()=>({})};
    throw Error('Unexpected request: '+path);}});
vm.runInContext(script,context,{timeout:1000});
await new Promise(setImmediate);
assert.equal(element('library-nav').hidden,false);
await element('library-nav').onclick();await new Promise(setImmediate);
assert.equal(element('library-panel').hidden,false);
const card=element('library-results').children[0];
assert.match(card.children[0].textContent,/France.*gen2.*124/);
assert.match(card.children[3].href,/google\.com\/maps\/.*pano=example-pano/);
element('library-prompt').value='a road';element('library-country').value='France';
element('library-generation').value='gen2';element('library-view').value='original';
await element('library-search').onclick();await new Promise(setImmediate);
const query=JSON.parse(requests.find(([path])=>path==='/api/library/search')[1].body);
assert.equal(query.country,'France');assert.equal(query.generation,'gen2');assert.equal(query.viewDirection,'original');
assert.deepEqual(query.examples,[]);
await element('library-save').onclick();
assert.equal(created.find(n=>n.download==='VISION-search-results.json').clicked,true);
element('library-reference-file').files=[{size:200,text:async()=>JSON.stringify({customCoordinates:[{panoId:'reference-pano',heading:123,pitch:-2,zoom:1,extra:{private:'not sent'}}]})}];
await element('library-reference-file').onchange();
await element('library-search').onclick();await new Promise(setImmediate);
const reference=JSON.parse(requests.filter(([path])=>path==='/api/library/search').at(-1)[1].body);
assert.deepEqual(reference.examples,[{panoId:'reference-pano',heading:123,pitch:-2,zoom:1}]);
assert.equal(JSON.stringify(reference).includes('not sent'),false);
element('mma-key').value='memory-only-private-key';await element('mma-connect').onclick();
assert.equal(element('mma-key').value,'');
await element('mma-send').onclick();
assert.deepEqual(JSON.parse(requests.find(([path])=>path==='/api/mma/send')[1].body),{mapId:'chosen-map'});
assert.equal(requests.filter(([path])=>path.startsWith('http')).length,0);
console.log('Local library shipped script: open, metadata filters, text search, Street View link and private map download passed.');
