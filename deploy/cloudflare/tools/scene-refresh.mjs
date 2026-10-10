// Called with private argument/result files; never print data or credentials.
import {readFile,writeFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
import {capturePublications,checkedProxyConfig,artifactBytes,uploadBundle} from './scene-refresh-source.mjs';
import {bounded} from '../native-scene-bridge/worker.js';
const args=JSON.parse(await readFile(process.argv[2],'utf8'));
let platform,result;
try {
  checkedProxyConfig(JSON.parse(await readFile(args.proxyConfig,'utf8')));
  const {getPlatformProxy}=await import(pathToFileURL(args.wrangler));
  platform=await getPlatformProxy({configPath:args.proxyConfig,persist:false,envFiles:[],remoteBindings:true});
  const env=platform.env;
  if(args.operation==='capture')result=await capturePublications(env.DB,args.policies);
  else if(args.operation==='artifact'){
    const bytes=await artifactBytes(env.INDEX,args.key);await writeFile(args.destination,bytes,{flag:'wx'});result={bytes:bytes.byteLength};
  } else if(args.operation==='upload')result=await uploadBundle(env.INDEX,args.descriptor,new Uint8Array(await readFile(args.archive)));
  else if(['status','activate','head'].includes(args.operation)){
    const response=await (args.operation==='head'?env.SEARCH_ENGINE:env.NATIVE_OPERATOR).fetch(
      'https://private.invalid'+({status:'/operator/status',activate:'/operator/refresh',head:'/snapshot'}[args.operation]),{
      method:args.operation==='activate'?'POST':'GET',...(args.operation==='activate'?{
        headers:{'content-type':'application/json'},body:JSON.stringify(args.request)}:{}),signal:AbortSignal.timeout(150000)});
    const body=JSON.parse(new TextDecoder().decode(await bounded(response.body,16384)));
    result={httpStatus:response.status,body};
  } else throw Error('invalid_refresh_operation');
  await writeFile(args.result,JSON.stringify({ok:true,result}),{flag:'wx'});
} catch {
  await writeFile(args.result,JSON.stringify({ok:false,error:'refresh_adapter_failed'}),{flag:'wx'});
  process.exitCode=1;
} finally {await platform?.dispose();}
