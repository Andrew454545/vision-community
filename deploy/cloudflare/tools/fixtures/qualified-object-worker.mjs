// Bundled only by the finite local fixture. Never part of the application router.
import {stageQualifiedObjectUpload,settleQualifiedObjectUpload} from '../../src/qualifiedObjectPublication.js';
import {deleteAccount} from '../../src/accountPrivacy.js';
import {requestQualifiedObjectWork,cancelQualifiedObjectWork} from '../../src/objectWork.js';
export default {async fetch(request,env) {
  if(request.headers.get('authorization')!=='Bearer synthetic-local-only')return new Response(null,{status:401});
  const body=await request.json();
  try {
    const action=new URL(request.url).pathname;
    if(action==='/work')return Response.json(await requestQualifiedObjectWork(env,body.account,body.input));
    if(action==='/work-cancel')return Response.json(await cancelQualifiedObjectWork(env,body.account,body.requestKey));
    if(action==='/stage')return Response.json(await stageQualifiedObjectUpload(env,body.account,body.authority,body.index));
    if(action==='/settle')return Response.json(await settleQualifiedObjectUpload(env,body.account,body.lease));
    if(action==='/delete')return Response.json(await deleteAccount(env,body.account,body.deletion));
    return new Response(null,{status:404});
  }catch(error){return Response.json({error:error.message},{status:error.status||503});}
}};
