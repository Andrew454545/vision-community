// Private operator preparation only. No HTTP endpoint, credentials or cloud calls.
import {createHash} from 'node:crypto';
import {lstatSync,readFileSync,mkdirSync,writeFileSync} from 'node:fs';
import {dirname,join,resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import {parseArgs} from 'node:util';
import {SCHEMA_CONTRACT,SCHEMA_REVISION} from '../src/schemaRevision.js';
import {OBJECT_INDEX_MODEL} from '../src/objectIndex.js';
import {COVERAGE_VALIDATOR} from '../src/objectCoverage.js';

export const VALIDATOR_POLICY='strict-google-official-historical-v7-exact-pano-2026-10-06';
export {COVERAGE_VALIDATOR};
export const MAX_ROWS=1000;
const HEX=/^[0-9a-f]{64}$/;
const MAX_FILE=8*1024*1024;
const required=['location_id','source_id','source_row','country','country_code','lat','lng','pano_id','source_provenance'];
const normalized=[...required.slice(0,8),'capture_year','capture_month','camera_generation','official_validation','source_provenance','road_name_state','heading','pitch','zoom'];
const rejected=[...required,'heading','pitch','zoom','road_name_state','reason'];
const fail=code=>{throw Error(code);};
export const digest=bytes=>createHash('sha256').update(bytes).digest('hex');
const integer=(value,min=0)=>Number.isSafeInteger(value)&&value>=min;
const text=value=>typeof value==='string'&&value.length>0&&value.length<=4096&&!/[\x00-\x1f\x7f]/.test(value);
const key=row=>JSON.stringify([row.source_id,row.location_id,row.source_row]);
const quote=value=>"'"+value.replaceAll("'","''")+"'";
const number=(value,fallback=NaN)=>value===''?fallback:
  (/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(value)?Number(value):NaN);

// Accept Rust csv::Writer quoted TSV (including doubled quotes). Never split a
// quoted provenance field into additional rows or silently drop a broken line.
export function tsv(bytes) {
  const input=new TextDecoder('utf-8',{fatal:true}).decode(bytes);
  if (!input.endsWith('\n')||input.includes('\0')) fail('invalid_validator_tsv');
  const records=[];let row=[],field='',quoted=false,closed=false;
  for(let i=0;i<input.length;i++) {
    const c=input[i];
    if(quoted) {
      if(c==='"') {if(input[i+1]==='"'){field+='"';i++;}else{quoted=false;closed=true;}}
      else field+=c;
    } else if(c==='"'&&!field&&!closed) quoted=true;
    else if(c==='\t'||c==='\n'||(c==='\r'&&input[i+1]==='\n')) {
      row.push(field);field='';closed=false;
      if(c!=='\t') {records.push(row);row=[];if(c==='\r')i++;}
    } else {if(closed||c==='"')fail('invalid_validator_tsv');field+=c;}
    if(records.length>MAX_ROWS+1||field.length>4096) fail('validator_packet_too_large');
  }
  if(quoted||closed||row.length||field||!records.length) fail('invalid_validator_tsv');
  const header=records.shift();
  if(header.some(v=>!text(v))||new Set(header).size!==header.length) fail('invalid_validator_header');
  return {header,rows:records.map(values=>{
    if(values.length!==header.length)fail('invalid_validator_tsv');
    return Object.fromEntries(header.map((v,i)=>[v,values[i]]));
  })};
}
function pin(bytes,expected) {
  if(!Buffer.isBuffer(bytes)||bytes.length>MAX_FILE||!HEX.test(expected||'')||digest(bytes)!==expected)fail('validator_checksum_mismatch');
}
function fileDigest(entry,bytes) {
  if(!entry||!integer(entry.bytes,1)||entry.bytes!==bytes.length)fail('invalid_validator_file');
  pin(bytes,entry.sha256);
}

// The independent manifest pin must come from an operator-verified execution of
// Andrew's current private Rust validator, NOT a volunteer or generic catalog.
export function prepareCoverage({manifest,manifestSha256,input,inputSha256,countries,countriesSha256,accepted,denied},now=Date.now()) {
  pin(manifest,manifestSha256);pin(input,inputSha256);pin(countries,countriesSha256);
  let m;try{m=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(manifest));}catch{fail('invalid_validator_manifest');}
  const completed=Date.parse(m.completedAt);
  const flags=['allInputRowsAccountedFor','normalizedRowsAreStrictlyOfficial','normalizedRowsHaveValidCountryTags',
    'normalizedRowsHaveMatchingCountryCodes','normalizedRowsHaveValidCaptureDates','normalizedRowsHaveKnownCameraGenerations'];
  if(m.schemaVersion!==2||m.validatorPolicy!==VALIDATOR_POLICY||!Number.isFinite(completed)||completed>now+60000||now-completed>86400000
    ||m.cacheMaxAgeDays!==1||!integer(m.maxRows,1)||m.maxRows>MAX_ROWS
    ||!['required-input-must-match-google-metadata-v1','empty-input-google-metadata-authoritative-v1'].includes(m.countryCodeInputPolicy)
    ||flags.some(k=>m.invariants?.[k]!==true)||m.invariants?.brokenOrUnofficialRowsInNormalized!==0
    ||m.resumePolicy!=='restart-immutable-shard-and-reuse-versioned-batch-cache-v2')fail('unsupported_validator_manifest');
  fileDigest(m.input,input);fileDigest(m.countryNames,countries);
  fileDigest(m.artifacts?.['normalized.tsv'],accepted);fileDigest(m.artifacts?.['rejected.tsv'],denied);
  const source=tsv(input),valid=tsv(accepted),invalid=tsv(denied);
  if(!required.every(h=>source.header.includes(h))||JSON.stringify(valid.header)!==JSON.stringify(normalized)
    ||JSON.stringify(invalid.header)!==JSON.stringify(rejected))fail('invalid_validator_header');
  const counts=m.counts;
  if(!counts||!['inputRows','officialRows','rejectedRows','cacheHits','cacheMisses','metadataRequests','metadataRetries'].every(k=>integer(counts[k]))
    ||counts.inputRows!==source.rows.length||counts.inputRows>m.maxRows||counts.officialRows!==valid.rows.length
    ||counts.rejectedRows!==invalid.rows.length||counts.inputRows!==counts.officialRows+counts.rejectedRows)fail('invalid_validator_accounting');
  const countrySet=new Set(new TextDecoder('utf-8',{fatal:true}).decode(countries).split(/\r?\n/).map(s=>s.trim()).filter(Boolean));
  if(!countrySet.size)fail('invalid_validator_countries');
  const raw=new Map();
  for(const row of source.rows) {
    for(const k of Object.keys(row))row[k]=row[k].trim();
    if(!['location_id','source_id','source_row'].every(k=>text(row[k]))||!integer(Number(row.source_row),1)||raw.has(key(row)))fail('duplicate_or_invalid_source_identity');
    raw.set(key(row),row);
  }
  const seen=new Set(),identities=new Set(),records=[];
  for(const [rows,isAccepted] of [[valid.rows,true],[invalid.rows,false]])for(const row of rows) {
    const original=raw.get(key(row));
    if(!original||seen.has(key(row)))fail('validator_source_identity_mismatch');seen.add(key(row));
    if(!['country','lat','lng','pano_id','source_provenance'].every(k=>isAccepted&&(k==='lat'||k==='lng')?number(row[k])===number(original[k]):row[k]===original[k]))fail('validator_source_identity_mismatch');
    if(!isAccepted) {if(!text(row.reason))fail('invalid_validator_rejection');continue;}
    if(row.official_validation!=='official'||!/^[-_A-Za-z0-9]{21}[AQgw]$/.test(row.pano_id)||!countrySet.has(row.country)
      ||!/^([A-Z]{2})$/.test(row.country_code)||!['gen1','gen2','gen3','gen4','trekker','badcam'].includes(row.camera_generation)
      ||!['has-road','no-road'].includes(row.road_name_state))fail('invalid_official_coverage');
    if(m.countryCodeInputPolicy==='required-input-must-match-google-metadata-v1'?row.country_code!==original.country_code:original.country_code!=='')fail('validator_country_identity_mismatch');
    const year=Number(row.capture_year),month=Number(row.capture_month);
    if(!integer(year,2000)||year>new Date(now).getUTCFullYear()+1||!integer(month,1)||month>12)fail('invalid_capture_date');
    const pose=Object.fromEntries(['lat','lng','heading','pitch','zoom'].map(k=>[k,number(row[k])]));
    if(Object.values(pose).some(v=>!Number.isFinite(v))||Math.abs(pose.lat)>90||Math.abs(pose.lng)>180
      ||['lat','lng','heading','pitch','zoom'].some(k=>pose[k]!==number(original[k]||'',k==='lat'||k==='lng'?NaN:0)))fail('validator_pose_mismatch');
    const capture=`${year}-${String(month).padStart(2,'0')}`,identity=JSON.stringify([row.pano_id,capture]);
    if(identities.has(identity))fail('duplicate_coverage_identity');identities.add(identity);
    if(row.camera_generation!=='gen4')continue;
    const record={assetId:row.pano_id,capture,model:OBJECT_INDEX_MODEL,...pose,country:row.country};
    record.evidenceSha256=digest(JSON.stringify({contract:COVERAGE_VALIDATOR,manifestSha256,inputSha256,countriesSha256,
      validatorPolicy:VALIDATOR_POLICY,sourceIdentity:key(row),countryCode:row.country_code,roadNameState:row.road_name_state,record}));
    records.push(record);
  }
  if(seen.size!==raw.size||!records.length)fail('no_complete_gen4_coverage');
  return {contract:'vision-community-object-coverage-import-v1',manifestSha256,inputSha256,countriesSha256,
    validatorPolicy:VALIDATOR_POLICY,validatedAt:Math.floor(completed/1000),records};
}

// One supported D1 batch is the transaction. Never submit individual statements
// or use INSERT OR REPLACE to rewrite an active/published row or its evidence.
export function coveragePlan(packet) {
  const payload=JSON.stringify(packet.records),at=packet.validatedAt;
  if(packet.contract!=='vision-community-object-coverage-import-v1'||!HEX.test(packet.manifestSha256)||!integer(at,1)
    ||!Array.isArray(packet.records)||!packet.records.length||packet.records.length>MAX_ROWS)fail('invalid_coverage_plan');
  const match=`l.asset_id=json_extract(j.value,'$.assetId') AND l.capture=json_extract(j.value,'$.capture') AND l.lane='object' AND l.model=json_extract(j.value,'$.model')`;
  const exact=`l.camera_generation='gen4' AND l.lat=json_extract(j.value,'$.lat') AND l.lon=json_extract(j.value,'$.lng')
    AND l.heading=json_extract(j.value,'$.heading') AND l.pitch=json_extract(j.value,'$.pitch') AND l.zoom=json_extract(j.value,'$.zoom') AND l.country=json_extract(j.value,'$.country')`;
  const receipt=`c.validator=${quote(COVERAGE_VALIDATOR)} AND c.evidence_sha256=json_extract(j.value,'$.evidenceSha256') AND c.validated_at=${at}`;
  const guard=predicate=>`INSERT INTO community_object_import_guard SELECT CASE WHEN ${predicate} THEN 1 ELSE 0 END`;
  return [
    {sql:'CREATE TABLE community_object_import_guard(value INTEGER NOT NULL CHECK(value=1))',params:[]},
    {sql:guard(`EXISTS(SELECT 1 FROM community_schema_revision WHERE slot=1 AND revision=${SCHEMA_REVISION} AND contract=${quote(SCHEMA_CONTRACT)})`),params:[]},
    {sql:guard(`NOT EXISTS(SELECT 1 FROM json_each(?) j JOIN locations l ON ${match} LEFT JOIN object_coverage c ON c.location_id=l.id
      WHERE NOT (${exact}) OR (c.location_id IS NOT NULL AND NOT (${receipt}))
      OR ((l.state!='pending' OR l.active_lease IS NOT NULL OR l.lease_until IS NOT NULL OR l.contributor_id IS NOT NULL OR COALESCE(l.queue_state,'pending')!='pending') AND NOT COALESCE((${receipt}),0)))`),params:[payload]},
    {sql:`INSERT OR IGNORE INTO locations(asset_id,capture,lane,model,source,rights,attribution,lat,lon,heading,pitch,zoom,country,camera_generation)
      SELECT json_extract(value,'$.assetId'),json_extract(value,'$.capture'),'object',json_extract(value,'$.model'),'street-metadata','metadata-only-no-imagery',
        'Panorama metadata only. Imagery is not stored.',json_extract(value,'$.lat'),json_extract(value,'$.lng'),json_extract(value,'$.heading'),json_extract(value,'$.pitch'),json_extract(value,'$.zoom'),json_extract(value,'$.country'),'gen4' FROM json_each(?)`,params:[payload]},
    {sql:guard(`(SELECT COUNT(*) FROM json_each(?) j JOIN locations l ON ${match} WHERE ${exact})=${packet.records.length}`),params:[payload]},
    {sql:`INSERT INTO object_coverage(location_id,validator,evidence_sha256,validated_at)
      SELECT l.id,${quote(COVERAGE_VALIDATOR)},json_extract(j.value,'$.evidenceSha256'),${at} FROM json_each(?) j JOIN locations l ON ${match} WHERE ${exact}
      ON CONFLICT(location_id) DO NOTHING`,params:[payload]},
    {sql:guard(`(SELECT COUNT(*) FROM json_each(?) j JOIN locations l ON ${match} JOIN object_coverage c ON c.location_id=l.id WHERE ${exact} AND ${receipt})=${packet.records.length}`),params:[payload]},
    {sql:'DROP TABLE community_object_import_guard',params:[]}
  ];
}
function safePath(path,directory=false) {
  let current=resolve(path),leaf=true;
  while(true) {
    const info=lstatSync(current);
    if(info.isSymbolicLink()||(leaf&&!directory?!info.isFile():!info.isDirectory()))fail('unsafe_coverage_path');
    const parent=dirname(current);if(parent===current)return;current=parent;leaf=false;
  }
}
function read(path) {safePath(path);if(lstatSync(path).size>MAX_FILE)fail('validator_packet_too_large');return readFileSync(path);}
export function saveCoveragePlan(values) {
  const source=resolve(values.input),root=resolve(values.validator),countries=resolve(values.countries),out=resolve(values.out);
  safePath(dirname(out),true);
  mkdirSync(out,{recursive:false,mode:0o700});safePath(out,true);
  try {
    safePath(root,true);
    const packet=prepareCoverage({manifest:read(join(root,'manifest.json')),manifestSha256:values['manifest-sha256'],
      input:read(source),inputSha256:values['input-sha256'],countries:read(countries),countriesSha256:values['countries-sha256'],
      accepted:read(join(root,'normalized.tsv')),denied:read(join(root,'rejected.tsv'))});
    const batch=coveragePlan(packet),encode=value=>JSON.stringify(value,null,2)+'\n';
    const batchBytes=encode(batch),packetBytes=encode(packet);
    for(const [name,bytes] of [['import-batch.private.json',batchBytes],['coverage.private.json',packetBytes],['report.private.json',encode({
      status:'OFFLINE_COVERAGE_PLAN_SAVED',manifestSha256:packet.manifestSha256,records:packet.records.length,statements:batch.length,
      batchSha256:digest(batchBytes),coverageSha256:digest(packetBytes),
      publicAdmissionReady:false,cloudResourcesAccessed:false,creditsChanged:false})]]) {
      safePath(out,true);writeFileSync(join(out,name),bytes,{flag:'wx',mode:0o600});
    }
    return packet.records.length;
  }catch(error) {
    // Never save raw filesystem/JSON diagnostics: they can expose source paths.
    // A redirected output or filesystem failure may also prevent this report.
    try {safePath(out,true);writeFileSync(join(out,'failure.private.json'),JSON.stringify({status:'INCOMPLETE',
      failure:'coverage_preparation_failed',cloudResourcesAccessed:false,publicAdmissionReady:false})+'\n',{flag:'wx',mode:0o600});}catch{}
    throw error;
  }
}
if(process.argv[1]&&import.meta.url===pathToFileURL(resolve(process.argv[1])).href) {
  try {
    const options=Object.fromEntries(['validator','manifest-sha256','input','input-sha256','countries','countries-sha256','out'].map(k=>[k,{type:'string'}]));
    const {values}=parseArgs({options});if(Object.keys(options).some(k=>!values[k]))fail('missing_coverage_inputs');
    console.log(JSON.stringify({status:'OFFLINE_COVERAGE_PLAN_SAVED',records:saveCoveragePlan(values),cloudResourcesAccessed:false}));
  } catch {console.error('Coverage preparation failed. Check the independently verified validator pins and use a new private output folder. Existing files are preserved.');process.exitCode=1;}
}
