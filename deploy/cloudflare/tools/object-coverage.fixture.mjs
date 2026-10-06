// Synthetic test inputs only. These are never trusted coverage for live work.
import {digest,VALIDATOR_POLICY} from './import-object-coverage.mjs';
export const SOURCE_HEADER='location_id\tsource_id\tsource_row\tcountry\tcountry_code\tlat\tlng\tpano_id\tsource_provenance\theading\tpitch\tzoom\troad_name_state';
export const NORMAL_HEADER='location_id\tsource_id\tsource_row\tcountry\tcountry_code\tlat\tlng\tpano_id\tcapture_year\tcapture_month\tcamera_generation\tofficial_validation\tsource_provenance\troad_name_state\theading\tpitch\tzoom';
export const REJECT_HEADER=SOURCE_HEADER+'\treason';
const encode=rows=>Buffer.from(rows.join('\n')+'\n');
export function coverageFixture({generation='gen4',rows=1,rejections=0,provenance='operator-only',clock=Date.now()}={}) {
  const inputRows=[],validRows=[],deniedRows=[];
  const csv=value=>/["\t\n\r]/.test(value)?'"'+value.replaceAll('"','""')+'"':value;
  for(let i=0;i<rows+rejections;i++) {
    const pano=('fixture'+String(i).padStart(14,'0'))+'A';
    const raw=[`row-${i}`,'synthetic',String(i+1),'USA','US','10.25','20.5',pano,csv(provenance),'90.25','2','0','no-road'];
    inputRows.push(raw.join('\t'));
    if(i<rows)validRows.push([...raw.slice(0,8),'2020','6',generation,'official',raw[8],'no-road',...raw.slice(9,12)].join('\t'));
    else deniedRows.push([...raw,'broken'].join('\t'));
  }
  const input=encode([SOURCE_HEADER,...inputRows]),accepted=encode([NORMAL_HEADER,...validRows]),denied=encode([REJECT_HEADER,...deniedRows]);
  const countries=Buffer.from('USA\nItaly\n');
  const file=(bytes,path)=>({path,bytes:bytes.length,sha256:digest(bytes)});
  const document={schemaVersion:2,validatorPolicy:VALIDATOR_POLICY,completedAt:new Date(clock).toISOString(),
    input:file(input,'private/input.tsv'),countryNames:file(countries,'private/countries.txt'),cache:'private/cache.sqlite',
    cacheMaxAgeDays:1,metadataBatchSize:125,requestConcurrency:8,maxRows:1000,
    countryCodeInputPolicy:'required-input-must-match-google-metadata-v1',
    counts:{inputRows:rows+rejections,officialRows:rows,rejectedRows:rejections,cacheHits:0,cacheMisses:rows+rejections,metadataRequests:1,metadataRetries:0},
    rejectionReasons:rejections?{broken:rejections}:{},artifacts:{'normalized.tsv':file(accepted,'normalized.tsv'),'rejected.tsv':file(denied,'rejected.tsv')},
    invariants:{allInputRowsAccountedFor:true,normalizedRowsAreStrictlyOfficial:true,normalizedRowsHaveValidCountryTags:true,
      normalizedRowsHaveMatchingCountryCodes:true,normalizedRowsHaveValidCaptureDates:true,normalizedRowsHaveKnownCameraGenerations:true,brokenOrUnofficialRowsInNormalized:0},
    resumePolicy:'restart-immutable-shard-and-reuse-versioned-batch-cache-v2'};
  return repin({...document}, {input,accepted,denied,countries});
}
export function repin(document,bytes) {
  document.input={...document.input,bytes:bytes.input.length,sha256:digest(bytes.input)};
  document.countryNames={...document.countryNames,bytes:bytes.countries.length,sha256:digest(bytes.countries)};
  for(const [name,k] of [['normalized.tsv','accepted'],['rejected.tsv','denied']])
    document.artifacts[name]={...document.artifacts[name],bytes:bytes[k].length,sha256:digest(bytes[k])};
  const manifest=Buffer.from(JSON.stringify(document));
  return {...bytes,manifest,manifestSha256:digest(manifest),inputSha256:digest(bytes.input),countriesSha256:digest(bytes.countries)};
}
