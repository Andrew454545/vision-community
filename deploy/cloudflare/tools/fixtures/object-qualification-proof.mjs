// Synthetic only: no real runtime, model, input, coverage or account evidence.
const profile='c'.repeat(64),settings='d'.repeat(64),now=Math.floor(Date.now()/1000);
export function policy() {
  return {version:1,scope:'saved-full-object-sample-qualification-v1',policyId:'staging.synthetic-object.index-v1',
    policySha256:'1'.repeat(64),scorePolicySha256:'2'.repeat(64),fixtureSha256:'3'.repeat(64),referenceBundleSha256:'4'.repeat(64),
    frozenViewsManifestSha256:'5'.repeat(64),sourceSha256:'6'.repeat(64),locations:100,profiles:{[profile]:settings},
    resource:{accountId:'272760294910ef0b246980278aeb36e2',databaseId:'17043cb7-5dab-4a6f-84ca-19ae1c14cc05',bucket:'vision-community-staging'},
    validFrom:now-100,validUntil:now+86400};
}
export function evidence(request,p=policy(),compatible=true,at=now) {
  const lane=(id)=>({id,missingRecords:0,extraRecords:0,discreteDifferences:0,maximumScoreDifference:0,
    maximumConfidenceDifference:0,maximumHeadingDegrees:0,maximumPitchDegrees:0,maximumZoomDifference:0,maximumAreaDifference:0});
  const candidate='7'.repeat(64);
  return {version:1,scope:'trusted-saved-object-sample-evidence-v1',accountId:request.accountId,requestId:request.requestId,
    challenge:request.challenge,artifactSetSha256:request.artifactSetSha256,
    artifacts:{detectorProfileId:profile,indexProfileId:profile,detectorSettingsSha256:settings,indexSettingsSha256:settings,
      executionReceiptSha256:'8'.repeat(64)},issuedAt:at,expiresAt:at+30,
    report:{version:1,qualificationScope:'fixed-input-object-score-and-index-parity-only',sampleCompatible:compatible,
      scoreCompatible:compatible,indexCompatible:true,qualified:false,policyId:p.policyId,policySha256:p.policySha256,
      scorePolicySha256:p.scorePolicySha256,profileId:profile,fixtureSha256:p.fixtureSha256,referenceBundleSha256:p.referenceBundleSha256,
      scoreSubmissionSha256:'9'.repeat(64),candidateManifestSha256:candidate,frozenViewsManifestSha256:p.frozenViewsManifestSha256,
      locations:100,views:600,issuedAt:at,expiresAt:at+3600,identicalInputBindingVerified:true,inferenceProvenanceVerified:false,
      currentEligibilityVerified:false,serverAuthorization:false,productionQualified:false,acceptedContributions:0,searchCreditsCreated:0,
      detectorComparison:{structuralDifferences:compatible?0:1,numericValuesCompared:9600,maximumScoreDifference:0,maximumBoxDifference:0},
      indexComparison:{version:1,scope:'offline-object-index-comparison',status:'COMPLETE',referenceManifestSha256:'a'.repeat(64),
        candidateManifestSha256:candidate,sourceSha256:p.sourceSha256,locations:100,qualified:false,referenceProvenanceVerified:false,
        identicalPixelsVerified:false,nativeSearchParityVerified:false,serverAuthorization:false,viewQualityDifferences:0,
        declaredFrozenViews:{reference:p.frozenViewsManifestSha256,candidate:p.frozenViewsManifestSha256},
        lanes:{classes:Array.from({length:80},(_,i)=>lane(i+1)),hotConcepts:[lane(0),lane(1)]},
        semantic:{recordsCompared:1600,differentCodeBytes:0,differentFaces:0,maximumBoxDifference:0,
          maximumLogitShiftDifference:0,maximumLogitScaleDifference:0},
        nativeCounters:{reference:{fetchErrors:0,inferenceErrors:0,permanentlyInvalidLocations:0},
          candidate:{fetchErrors:0,inferenceErrors:0,permanentlyInvalidLocations:0}}}}};
}
