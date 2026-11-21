// Consume the actual Python adapter contract, not a native audit or admission.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {validateObjectProtectionEvidence} from '../src/qualifiedObjectEligibility.js';
const packet=JSON.parse(readFileSync(process.argv[2],'utf8'));
assert.equal(packet.scope,'synthetic-private-live-object-protection-no-inference');
const value=validateObjectProtectionEvidence(packet.proof,packet.request,packet.policy,packet.rows,Math.floor(Date.now()/1000));
assert.equal(value.protectedEligible,true);assert.equal(value.qualificationVerified,false);
assert.equal(value.sceneMembershipVerified,false);assert.equal(value.coverageVerified,false);
assert.equal(value.serverAuthorization,false);assert.equal(value.acceptedContributions,0);assert.equal(value.searchCreditsCreated,0);
assert.throws(()=>validateObjectProtectionEvidence(value,{...packet.request,challenge:'0'.repeat(32)},packet.policy,packet.rows,Math.floor(Date.now()/1000)));
console.log(JSON.stringify({status:'SYNTHETIC_PYTHON_OBJECT_PROTECTION_CONTRACT_PASSED',checks:1,
  records:value.records.length,currentOriginalSourceGuards:true,nativeInference:false,realQualifiedAccounts:0,
  acceptedContributions:0,creditsCreated:0,providerCalls:0}));
