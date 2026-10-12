// Internal coordinator: saved native comparison -> guarded publication/credit.
// Authority still comes from the trusted assignment registry and operator pins.
import {advanceObjectAudit} from './objectAuditDispatch.js';
import {settleObjectAudit} from './objectSettlement.js';
export async function advanceObjectContribution(env,account,lease,now=Math.floor(Date.now()/1000)) {
  const status=await advanceObjectAudit(env,account,lease,now);
  if(status.cancelled)return {...status,rejected:true};
  if(status.accepted || status.waitingForCapacity || status.auditState!=='approved' || !status.pendingAudit)return status;
  return settleObjectAudit(env,account,lease,now);
}
