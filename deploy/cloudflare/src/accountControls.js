// Current account/search controls without a corpus dashboard or storage scan.
import {MODEL_ID} from './model.js';
import {accountCredit} from './accountCredit.js';
import {searchCost} from './searchPricing.js';
import {onlineSearchConfigured} from './onlineSearch.js';
import {queuedSearchConfigured} from './searchQueue.js';
import {sceneCohortAllows} from './sceneCohort.js';
import {MAX_SEALED_SCENE_HITS} from './sceneMembership.js';

export function searchControlFields(env,cohortAllowed) {
  const cost=searchCost(env);
  const ready=cohortAllowed&&cost!==null&&(env.SEARCH_DELIVERY===undefined
    ? onlineSearchConfigured(env):queuedSearchConfigured(env));
  return {searchCost:cost,searchBackend:'online',searchOnSite:ready,searchReady:ready,
    searchDelivery:env.SEARCH_DELIVERY==='queued-v1'?'queued':'immediate',
    searchResultLimits:{scene:env.SEARCH_SCENE_MEMBERSHIP!==undefined?MAX_SEALED_SCENE_HITS
      :env.SEARCH_DELIVERY==='queued-v1'?1000:10000,object:env.SEARCH_DELIVERY==='queued-v1'?1000:10000},
    indexDownloads:false,accountDeletionAvailable:true};
}

export async function accountControls(env,account=null) {
  // Authenticated credit refresh retains the existing reservation/expiry rules.
  // Anonymous refresh neither reads another account nor maintains its jobs.
  const balance=account?await accountCredit(env,account):{
    creditContractVersion:1,accountId:null,units:0,searchesAvailable:0};
  const controls=searchControlFields(env,!!account&&await sceneCohortAllows(env,account));
  return {accountControlVersion:1,operational:true,
    environment:env.DEPLOYMENT_ENVIRONMENT==='staging'?'staging':'preview',model:MODEL_ID,...balance,...controls};
}
