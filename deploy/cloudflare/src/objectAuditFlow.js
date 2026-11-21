// Internal coordinator: saved native comparison -> guarded publication/credit.
// Authority still comes from the trusted assignment registry and operator pins.
import {advanceObjectAudit} from './objectAuditDispatch.js';
import {settleObjectAudit} from './objectSettlement.js';
import {retireAcceptedObjectAudits} from './objectAuditRetention.js';
import {ownerObjectDelivery,ownerObjectAuditStatus} from './ownerObjectAudit.js';
export async function advanceObjectContribution(env,account,lease,now=Math.floor(Date.now()/1000)) {
  // Owner mode status reads never start a hosted verifier or publish a cached
  // approval. Only a fresh authenticated owner completion can settle it.
  if(ownerObjectDelivery(env))return ownerObjectAuditStatus(env,account,lease);
  const status=await advanceObjectAudit(env,account,lease,now);
  if(status.cancelled)return {...status,rejected:true};
  const result=status.accepted || status.waitingForCapacity || status.auditState!=='approved' || !status.pendingAudit
    ? status : await settleObjectAudit(env,account,lease,now);
  if(result.accepted)await retireAcceptedObjectAudits(env,{account,lease,limit:1,now});
  return result;
}
