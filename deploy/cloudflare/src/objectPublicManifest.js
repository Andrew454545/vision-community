// Public metadata projection, matching community.object_snapshot.public_manifest.
// Call only after full feature validation. This is neither a native approval
// nor proof that a supplied protected-authority checksum is authentic.
const SCALARS = [
  'version','feature','architecture','sourceId','sourceBytes','sourceSha256','modelSha256',
  'runtimeIdentity','totalLocations','indexedLocations','globalStart','globalIdMode',
  'minimumGlobalLocation','maximumGlobalLocation','imageSize','tileGrid','tileOverlap',
  'minimumRelativeClassScore','smallObjectRelativeClassScore','fullTileArtifactThreshold',
  'rankingStrategy','viewStrategy','viewCount','faceSize','faceFov','bandsPerFace','bandWidth',
  'bandHeight','bandOffset','bandFov','recordBytes','positionPolicy','coverage','fetchErrors',
  'inferenceErrors','permanentlyInvalidLocations','completed',
];
const ENTRY = ['file','recordBytes','records','bytes','sha256'];
const CLASS = [...ENTRY,'id','name','storageFloor'];
const SEMANTIC = [...ENTRY,'codec','codebookSha256','embeddingDimensions','proposalsPerLocation'];
const QUALITY = [...ENTRY,'policy','implementationIdentity','viewCount','blurAreaFractionExclusive',
  'tileGrid','tunnelVisionProbabilityInclusive','tunnelEvidencePolicy','tunnelEvidenceManifestSha256',
  'tunnelEvidenceQualifiedViews','tunnelEvidenceMapMatchRecords','tunnelEvidenceVisualScoreRecords',
  'keptViews','blurRejectedViews','darkTunnelRejectedViews','fullyRejectedLocations',
  'permanentlyInvalidLocations','invalidLocationPolicy','protectedAuthorityManifestSha256'];
const CONTRACTS = ['manifest','checkpoint','commonRecord','hotRecord','semanticRecord','metadataRecord','offsets','globalIds'];
const HEX = /^[a-f0-9]{64}$/;
const fail = () => {throw Error('verification_failed');};
const dict = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const scalar = value => value === null || typeof value === 'string' || typeof value === 'boolean'
  || typeof value === 'number' && Number.isFinite(value);
function project(document, fields) {
  if (!dict(document)) fail();
  return Object.fromEntries(fields.filter(key => Object.hasOwn(document,key)).map(key => {
    if (!scalar(document[key])) fail();
    return [key,document[key]];
  }));
}
function qualityContract(quality, locations, invalid) {
  const counts = ['keptViews','blurRejectedViews','darkTunnelRejectedViews','fullyRejectedLocations'];
  if (!Number.isSafeInteger(locations) || locations < 1 || quality.file !== 'view-quality.bin'
      || quality.policy !== 'vision-per-view-quality-v1' || quality.viewCount !== 6
      || quality.blurAreaFractionExclusive !== 0.5 || quality.tileGrid !== 8
      || quality.tunnelVisionProbabilityInclusive !== 0.85
      || !HEX.test(quality.implementationIdentity ?? '') || !HEX.test(quality.protectedAuthorityManifestSha256 ?? '')
      || counts.some(key => !Number.isSafeInteger(quality[key]) || quality[key] < 0 || quality[key] > locations*6)) fail();
  const rejected = Object.hasOwn(quality,'permanentlyInvalidLocations') ? quality.permanentlyInvalidLocations : 0;
  if (!Number.isSafeInteger(rejected) || rejected < 0 || rejected > quality.fullyRejectedLocations
      || quality.fullyRejectedLocations > locations || rejected !== invalid
      || counts.slice(0,3).reduce((sum,key) => sum+quality[key],0)+rejected*6 !== locations*6
      || quality.invalidLocationPolicy != null && quality.invalidLocationPolicy !==
        'quality-lane-tombstone:definitive-google-pano-or-repeated-image-decode-v1'
      || rejected && quality.invalidLocationPolicy == null) fail();
  const evidence = ['tunnelEvidenceQualifiedViews','tunnelEvidenceMapMatchRecords','tunnelEvidenceVisualScoreRecords'];
  if (evidence.some(key => Object.hasOwn(quality,key) && (!Number.isSafeInteger(quality[key]) || quality[key] < 0))) fail();
  if (quality.tunnelEvidencePolicy === 'none-darkness-never-rejects-v1') {
    if (quality.tunnelEvidenceManifestSha256 != null || quality.darkTunnelRejectedViews
        || evidence.some(key => (quality[key] ?? 0) !== 0)) fail();
  } else if (quality.tunnelEvidencePolicy === 'sealed-external-map-plus-tunnel-vision-exact-pano-coordinate-v1') {
    if (!HEX.test(quality.tunnelEvidenceManifestSha256 ?? '') || evidence.some(key => !Object.hasOwn(quality,key))
        || quality.darkTunnelRejectedViews > quality.tunnelEvidenceQualifiedViews) fail();
  } else fail();
}

export function publicObjectManifest(document) {
  if (!dict(document) || Object.hasOwn(document,'frozenViewsManifestSha256')) fail();
  const result = project(document,SCALARS);
  for (const key of ['fetchErrors','inferenceErrors','permanentlyInvalidLocations']) {
    if (Object.hasOwn(result,key) && (!Number.isSafeInteger(result[key]) || result[key] < 0)) fail();
  }
  result.sourceTsv = 'locations.tsv';
  if (!dict(document.contractVersions) || !Array.isArray(document.countries) || document.countries.length > 65536) fail();
  result.contractVersions = Object.fromEntries(CONTRACTS.map(key => {
    const value = document.contractVersions[key] ?? null;
    if (!scalar(value)) fail();
    return [key,value];
  }));
  result.countries = document.countries.map(value => {
    if (typeof value !== 'string' || [...value].length > 100 || /[\x00-\x1f]/.test(value)) fail();
    return value;
  });
  for (const key of ['offsets','metadata','globalIds','semantic','viewQuality']) {
    const entry = document[key];
    if (key === 'viewQuality' && (entry == null || dict(entry) && Object.keys(entry).length === 0)) continue;
    result[key] = project(entry,key === 'semantic' ? SEMANTIC : key === 'viewQuality' ? QUALITY : ENTRY);
  }
  for (const key of ['classes','hotConcepts']) {
    if (!Array.isArray(document[key]) || document[key].length > 100) fail();
    result[key] = document[key].map(entry => project(entry,CLASS));
  }
  if (result.viewQuality) qualityContract(result.viewQuality,result.totalLocations,result.permanentlyInvalidLocations ?? 0);
  return result;
}
