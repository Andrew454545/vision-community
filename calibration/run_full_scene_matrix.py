"""Maintainer-only, finite Windows comparison against a complete private Mac gold.

Nine fresh 1,024-location runs, rotated 1/2/4 threads. Offline sealed imagery;
no downloads, accounts, contributions, credits, installed-worker access or
production qualification. Keep original failures and all generated tensors.
"""
import argparse
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import shutil
import struct
import time

from calibration.quality import decoded_difference
from calibration.run_windows import child_environment
from calibration.verify_full_scene_reference import (ROOT, ReferenceError, model_pins,
    pin, plain, read, sha, verify_archive, verify_reduced_case, verify_rgb, MAX_JSON, HEX, SHAPES)
from community.background import atomic_json, keep_awake
from community.desktop import DesktopError
from community.pc_canary import DLLS, runtime_profile

WINDOWS_BINARY={'bytes':30888448,'sha256':'6ce8f5c9dbfeb8404da13daa71afecfd07a56f118fc61819d07c1d2330f191ba'}
MODEL_MANIFEST_SHA='b086083e00e527164b0433579a34d7a8141b05ed492081a4c1aa2f14a9164e87'
OVERALL_SECONDS=36*60*60
INDEX_SECONDS=4*60*60
SEARCH_SECONDS=600
DISK_FLOOR=32*1024**3

class MatrixError(ValueError):
    pass

def save_report(path,report):
    # Validate before replacing the last readable receipt. Atomic file updates
    # retain the previous report if writing or replacing the new one fails.
    json.dumps(report,allow_nan=False)
    atomic_json(path,report)

def time_budgets(args):
    hours=getattr(args,'overall_hours',OVERALL_SECONDS//3600)
    minutes=getattr(args,'index_minutes',INDEX_SECONDS//60)
    if type(hours) is not int or not 1 <= hours <= 48:
        raise MatrixError('matrix_overall_hours_must_be_1_to_48')
    if type(minutes) is not int or not 1 <= minutes <= 360 or minutes > hours*60:
        raise MatrixError('matrix_index_minutes_must_be_1_to_360_within_overall_budget')
    return {'overallSeconds':hours*3600,'indexSeconds':minutes*60,
            'searchSeconds':SEARCH_SECONDS,'automaticNativeRetry':False}

@contextmanager
def observed_awake(report,checkpoint):
    entered=False
    try:
        with keep_awake():
            entered=True
            report['wakeRequest']='SYSTEM_ONLY_REQUEST_ACCEPTED_RESTORE_NOT_YET_CONFIRMED'
            checkpoint()
            yield
    except BaseException as error:
        if isinstance(error,DesktopError) and str(error)=='keep_awake_release_failed':
            report['wakeRequest']='DIAGNOSTIC_THREAD_PREVIOUS_STATE_RESTORE_FAILED'
        elif entered:
            report['wakeRequest']='DIAGNOSTIC_THREAD_PREVIOUS_STATE_RESTORED'
        else:
            report['wakeRequest']='SYSTEM_ONLY_REQUEST_NOT_ESTABLISHED'
        raise
    else:
        report['wakeRequest']='DIAGNOSTIC_THREAD_PREVIOUS_STATE_RESTORED'
    finally:
        checkpoint()

def windows_platform():
    return os.name=='nt'

def rotated_cases():
    for replica in range(1,4):
        order=(1,2,4)
        for threads in order[replica-1:]+order[:replica-1]:
            yield replica,threads

def thread_environment(root,threads):
    if type(threads) is not int or threads not in (1,2,4):
        raise MatrixError('invalid_matrix_threads')
    env=child_environment(root)
    env.update({key:str(threads) for key in ('VISION_ORT_THREADS','RAYON_NUM_THREADS','OMP_NUM_THREADS','ORT_NUM_THREADS')})
    env.update({key:'1' for key in ('OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS')})
    return env

def checked_runtime(binary,models,expected_profile):
    if not isinstance(expected_profile,str) or not HEX.fullmatch(expected_profile):
        raise MatrixError('independent_windows_profile_pin_required')
    if pin(binary)!=WINDOWS_BINARY or sha(ROOT/'community/runtime_manifest.json')!=MODEL_MANIFEST_SHA:
        raise MatrixError('matrix_runtime_or_model_manifest_pin_mismatch')
    for name in DLLS: plain(binary.parent/name)
    for entry in model_pins():
        if pin(models/entry['name'])!={key:entry[key] for key in ('bytes','sha256')}:
            raise MatrixError('matrix_model_pin_mismatch')
    profiles={threads:runtime_profile(binary,models,inference_threads=threads) for threads in (1,2,4)}
    if profiles[1]['sha256']!=expected_profile:
        raise MatrixError('matrix_runtime_profile_pin_mismatch')
    return profiles

def native_commands(binary,models,case,frozen,manifest_sha,*,index_seconds=INDEX_SECONDS):
    return (('index',index_seconds,[binary,'study-four-views','--input',case/'study.json',
        '--model-dir',models,'--locations-tsv',case/'locations.tsv','--index-dir',case/'repeat-index',
        '--checkpoint',case/'repeat-checkpoint.json','--output',case/'repeat-results.json',
        '--evidence-dir',case/'repeat-evidence','--evidence-budget-mib','4096','--scene-fp32',
        '--sealed-rgb',frozen,'--sealed-sha256',manifest_sha]),
        ('search',SEARCH_SECONDS,[binary,'search-four-view-index','--input',case/'search.json',
        '--model-dir',models,'--locations-tsv',case/'locations.tsv','--index-dir',case/'repeat-index',
        '--profile-cache-dir',case/'repeat-search-cache','--output',case/'repeat-search-results.json']))

def finite_command(run,argv,*,case,label,threads,environment,deadline,limit,entry,checkpoint,sample_working_set):
    remaining=min(limit,int(deadline-time.monotonic()))
    if remaining<1: raise MatrixError('full_matrix_overall_time_limit')
    entry.update(status='STARTED',timeoutSeconds=remaining,resource={})
    checkpoint()
    try:
        with (case/(label+'.stdout.log')).open('xb') as stdout,(case/(label+'.stderr.log')).open('xb') as stderr:
            result=run([str(value) for value in argv],receipt=entry['resource'],
                sample_working_set=sample_working_set,env=environment,cwd=case,
                stdout=stdout,stderr=stderr,timeout=remaining,creationflags=0x08000000)
        entry['exitCode']=result.returncode
        if result.returncode or entry['resource'].get('completeAfterOwnedCleanup') is not True:
            raise MatrixError('matrix_native_exit_or_cleanup_failed')
        for suffix in ('.stdout.log','.stderr.log'):
            if plain(case/(label+suffix)).stat().st_size>MAX_JSON:
                raise MatrixError('matrix_native_log_budget')
        with (case/(label+'.stderr.log')).open('rb') as source: raw=source.read(MAX_JSON+1)
        if f'[vision] ONNX Runtime global threads: {threads}, spinning disabled'.encode() not in raw.splitlines():
            raise MatrixError('matrix_requested_shared_pool_not_observed')
        entry.update(status='COMPLETE',sharedPoolObserved=True)
    except (Exception,KeyboardInterrupt) as error:
        entry.update(status='FAILED',errorType=type(error).__name__)
        raise
    finally:
        checkpoint()

def verify_native_case(case,manifest,queries,models,count=1024,*,reduced_out=None):
    """Check every PC tensor byte, then reuse the independent reduced validator.

    Generated raw preprocessing is retained. Reduced copies contain small
    vectors/indexes only, allowing identical schema validation without treating
    Mac hash-only preprocessing as downloaded bytes.
    """
    evidence=read(case/'repeat-evidence/scene-evidence.json')
    if (evidence.get('frames')!=manifest['frames'] or evidence.get('modelFiles')!=models
        or evidence.get('sourceTsv')!=manifest['sourceTsv']):
        raise MatrixError('matrix_native_inputs_changed')
    initial=read(case/'repeat-evidence/initial-evidence.json')
    initial_expected={**evidence,'status':'INCOMPLETE','frames':[],'tensors':[],'failure':None}
    if (initial!=initial_expected or evidence.get('failure') is not None
        or initial.get('productionQualified') is not False):
        raise MatrixError('matrix_initial_evidence_identity_invalid')
    tensors=evidence.get('tensors',[])
    seen=set()
    expected={'scene-evidence.json','initial-evidence.json'}
    for tensor in tensors:
        key=tensor.get('ordinal'),tensor.get('view'),tensor.get('event')
        if (type(key[0]) is not int or type(key[1]) is not int or key[0] not in range(count)
            or key[1] not in range(4) or key[2] not in SHAPES or key in seen
            or tensor.get('shape')!=SHAPES[key[2]] or tensor.get('dtype')!='float32-little-endian'):
            raise MatrixError('matrix_tensor_geometry_invalid')
        name=f'scene-{key[0]:04}-view-{key[1]}-{key[2]}.f32le'
        info=tensor.get('file',{})
        if (info.get('name')!=name or type(info.get('bytes')) is not int
            or info['bytes']!=math.prod(SHAPES[key[2]])*4
            or pin(case/'repeat-evidence'/name)!={k:info[k] for k in ('bytes','sha256')}):
            raise MatrixError('matrix_tensor_transport_invalid')
        seen.add(key);expected.add(name)
    if (seen!={(i,v,event) for i in range(count) for v in range(4) for event in SHAPES}
        or {p.name for p in plain(case/'repeat-evidence',directory=True).iterdir()}!=expected):
        raise MatrixError('matrix_tensor_inventory_incomplete')
    index=read(case/'repeat-index/manifest.json')
    if any(index.get(key)!=value for key,value in {'version':4,'viewsPerLocation':4,
        'bytesPerLocation':3080,'embeddingDimension':768,'shardLocations':count,
        'totalLocations':count,'indexedLocations':count,'completed':True}.items()):
        raise MatrixError('matrix_index_manifest_incomplete')
    reduced=case/'verified-reduced' if reduced_out is None else Path(reduced_out)
    plain(reduced.parent,directory=True)
    reduced.mkdir(exist_ok=False)
    for source,target in ((case/'repeat-evidence/scene-evidence.json','scene-evidence.json'),
        (case/'repeat-index/shard-000000.i8','shard-000000.i8'),
        (case/'repeat-index/shard-000000.mask','shard-000000.mask'),
        *((case/('repeat-'+suffix+'.json'),'repeat-'+suffix+'.json')
          for suffix in ('results','checkpoint','search-results'))):
        shutil.copyfile(plain(source),reduced/target)
    for tensor in tensors:
        if tensor['event']!='pixel-values':
            name=tensor['file']['name']
            shutil.copyfile(plain(case/'repeat-evidence'/name),reduced/name)
    checked,hashes,semantic=verify_reduced_case(reduced,'repeat',count,queries,models,manifest=manifest)
    checked.update(pcTensorByteFilesVerified=len(tensors),pcPreprocessingTransport='BYTES_VERIFIED_AND_RETAINED',
        initialEvidence=pin(case/'repeat-evidence/initial-evidence.json'))
    return checked,hashes,semantic

def inversion_count(order):
    """Number of reordered pairs in a complete zero-based rank permutation."""
    size=len(order)
    if set(order)!=set(range(size)) or any(type(v) is not int for v in order):
        raise MatrixError('matrix_rank_permutation_invalid')
    tree=[0]*(size+1)
    result=0
    for processed,value in enumerate(order):
        index=value+1
        lower=0
        while index:
            lower+=tree[index];index-=index&-index
        result+=processed-lower
        index=value+1
        while index<=size:
            tree[index]+=1;index+=index&-index
    return result

def query_comparison(actual,expected):
    if len(actual)!=len(expected): raise MatrixError('matrix_query_identity_mismatch')
    output=[]
    for current,gold in zip(actual,expected):
        if current[:3]!=gold[:3] or len(current[3])!=len(gold[3]):
            raise MatrixError('matrix_query_identity_mismatch')
        a,b=current[3],gold[3]
        ranks={row[0]:i for i,row in enumerate(b)}
        by_id={row[0]:row for row in b}
        if len(ranks)!=len(b) or {row[0] for row in a}!=set(ranks) or len({row[0] for row in a})!=len(a):
            raise MatrixError('matrix_query_location_mismatch')
        order=[ranks[row[0]] for row in a]
        positions={row[0]:i for i,row in enumerate(a)}
        gaps=[b[i][2]-b[i+1][2] for i in range(len(b)-1)
              if positions[b[i][0]]>positions[b[i+1][0]]]
        output.append({'name':current[0],'nativeQueryExactlyMatches':a==b,
            'orderedLocationsMatch':[row[0] for row in a]==[row[0] for row in b],
            'orderedLocationsAndSelectedViewsMatch':[(row[0],row[1]) for row in a]==[(row[0],row[1]) for row in b],
            'scoreValuesMatch':all(row[2]==by_id[row[0]][2] for row in a),
            'top10SetMatch':{row[0] for row in a[:10]}=={row[0] for row in b[:10]},
            'top100SetMatch':{row[0] for row in a[:100]}=={row[0] for row in b[:100]},
            'selectedViewDifferences':sum(row[1]!=by_id[row[0]][1] for row in a),
            'maxAbsoluteScoreDifference':max((abs(row[2]-by_id[row[0]][2]) for row in a),default=0),
            'rankInversions':inversion_count(order),'maximumRankDisplacement':max((abs(i-rank) for i,rank in enumerate(order)),default=0),
            'reversedAdjacentReferencePairs':len(gaps),'largestReversedAdjacentReferenceScoreGap':max(gaps,default=0)})
    return output

def tensor_comparison(case,gold,count=1024):
    current=read(case/'repeat-evidence/scene-evidence.json')
    reference=read(gold/'scene-evidence.json')
    by_event={(row['ordinal'],row['view'],row['event']):row for row in reference['tensors']}
    groups={event:{'total':0,'equalHashes':0,'maxRelativeL2':0.0} for event in SHAPES}
    for tensor in current['tensors']:
        other=by_event[tensor['ordinal'],tensor['view'],tensor['event']]
        group=groups[tensor['event']]
        group['total']+=1
        group['equalHashes']+=tensor['file']['sha256']==other['file']['sha256']
        if tensor['event']=='pixel-values': continue
        a=struct.unpack('<768f',plain(case/'repeat-evidence'/tensor['file']['name']).read_bytes())
        b=struct.unpack('<768f',plain(gold/other['file']['name']).read_bytes())
        norm=sum(v*v for v in b)
        if norm<=0 or any(not math.isfinite(v) for v in a+b): raise MatrixError('matrix_nonfinite_vector')
        group['maxRelativeL2']=max(group['maxRelativeL2'],math.sqrt(sum((x-y)**2 for x,y in zip(a,b))/norm))
    if any(row['total']!=count*4 for row in groups.values()): raise MatrixError('matrix_comparison_geometry')
    groups['pixel-values'].update(referenceTransport='HASH_ONLY_NOT_DOWNLOADED',relativeL2Measured=False)
    del groups['pixel-values']['maxRelativeL2']
    return groups

def run_matrix(args):
    budgets=time_budgets(args)
    out=args.out.absolute()
    plain(out.parent,directory=True)
    if out.is_relative_to(ROOT): raise MatrixError('private_matrix_output_must_be_outside_checkout')
    out.mkdir(exist_ok=False)
    report={'version':1,'status':'INCOMPLETE','scope':'finite-private-full-windows-matrix-1024',
        'productionQualified':False,'accountsCreated':0,'creditsChanged':0,'submissions':0,
        'liveImageryRetrieved':False,'installedWorkerInspected':False,'installedWorkerModified':False,
        'serialCases':True,'timeBudgets':budgets,'runs':[],'commands':[],'wakeRequest':'NOT_STARTED',
        'limitations':['CONTROLLED_REPLAY_NOT_TRUSTED_LIVE_CONTRIBUTION_AUDIT',
            'NO_PROVIDER_NODE_OR_INTERNAL_PRECISION_ATTESTATION','NO_THERMAL_OR_OVERNIGHT_ENDURANCE_APPROVAL',
            'WORKING_SETS_ARE_NON_ATOMIC_SAMPLED_SUMS_NOT_UNIQUE_PHYSICAL_RAM']}
    def checkpoint():
        save_report(out/'full-windows-matrix-evidence.json',report)
    checkpoint()
    deadline=time.monotonic()+budgets['overallSeconds']
    try:
        if not windows_platform(): raise MatrixError('full_matrix_requires_windows')
        if shutil.disk_usage(out).free<DISK_FLOOR: raise MatrixError('full_matrix_requires_32_gib_free')
        binary,models=args.binary.absolute(),args.models.absolute()
        profiles=checked_runtime(binary,models,args.runtime_profile_sha256)
        report.update(starterRuntimeIdentityProfiles=profiles,runner=pin(Path(__file__)),
            resourceMeasurement=pin(ROOT/'calibration/windows_resource_measurement.py'),
            referenceVerifier=pin(ROOT/'calibration/verify_full_scene_reference.py'))
        checkpoint()
        verified=verify_archive(args.archive,{'bytes':args.bytes,'sha256':args.sha256},out/'reference-verification')
        report['referenceVerification']=verified
        checkpoint()
        if verified['status']!='FULL_MAC_REFERENCE_TRANSPORT_VERIFIED_UNQUALIFIED':
            raise MatrixError('completed_independently_pinned_full_mac_reference_required')
        root=out/'reference-verification/artifact'
        frozen=root/'frozen-rgb'
        manifest=read(frozen/'manifest.json')
        queries=read(root/'search.json')['queries']
        model_files=model_pins()
        report['matrixSettings']=read(root/'study.json')
        checkpoint()
        reference_search=read(root/'repeat-1/repeat-1-search-results.json')
        gold_semantic=[(q['name'],q['query'],q['mode'],[(h['locationIndex'],h['viewOffset'],h['similarity']) for h in q['hits']])
                       for q in reference_search['queries']]
        baselines={}
        with observed_awake(report,checkpoint):
            for replica,threads in rotated_cases():
                if shutil.disk_usage(out).free<4*1024**3: raise MatrixError('full_matrix_per_case_storage_floor')
                if checked_runtime(binary,models,args.runtime_profile_sha256)!=profiles:
                    raise MatrixError('matrix_runtime_changed')
                case=out/f'threads-{threads}-replica-{replica}'
                case.mkdir(exist_ok=False)
                for name in ('locations.tsv','study.json','search.json'): shutil.copyfile(plain(root/name),case/name)
                env=thread_environment(case/'isolated-environment',threads)
                for label,limit,argv in native_commands(binary,models,case,frozen,verified['frozenManifest']['sha256'],index_seconds=budgets['indexSeconds']):
                    entry={'case':case.name,'label':label,'requestedInferenceThreads':threads}
                    report['commands'].append(entry)
                    from calibration.windows_resource_measurement import measure_owned
                    finite_command(measure_owned,argv,case=case,label=label,threads=threads,environment=env,
                        deadline=deadline,limit=limit,entry=entry,checkpoint=checkpoint,
                        sample_working_set=args.sample_working_set)
                checked,hashes,semantic=verify_native_case(case,manifest,queries,model_files)
                if sha(case/'locations.tsv')!=verified['source']['sha256']:
                    raise MatrixError('matrix_case_source_changed')
                baseline=baselines.setdefault(threads,(checked['payload'],hashes,semantic))
                report['runs'].append({'case':case.name,'replica':replica,'threads':threads,**checked,
                    'decodedMacComparison':decoded_difference((case/'repeat-index/shard-000000.i8').read_bytes(),
                                                              (root/'repeat-1/shard-000000.i8').read_bytes()),
                    'tensorMacComparison':tensor_comparison(case,root/'repeat-1'),
                    'nativeSearchMacComparison':query_comparison(semantic,gold_semantic),
                    'sameThreadPackedPayloadMatchesFirst':checked['payload']==baseline[0],
                    'sameThreadTensorHashDifferences':sum(hashes[key]!=baseline[1][key] for key in hashes),
                    'sameThreadNativeQueriesExactlyMatchFirst':semantic==baseline[2]})
                checkpoint()
                print(case.name+' complete; unqualified comparison retained.',flush=True)
            if checked_runtime(binary,models,args.runtime_profile_sha256)!=profiles:
                raise MatrixError('matrix_runtime_changed')
            verify_rgb(frozen,root/'locations.tsv',model_files)
            for source,key in ((Path(__file__),'runner'),(ROOT/'calibration/windows_resource_measurement.py','resourceMeasurement'),
                               (ROOT/'calibration/verify_full_scene_reference.py','referenceVerifier')):
                if pin(source)!=report[key]: raise MatrixError('matrix_helper_source_changed')
            for name,key in (('full-reference-evidence.json','referenceReceipt'),('frozen-rgb/manifest.json','frozenManifest'),('locations.tsv','source')):
                if pin(root/name)!=verified[key]: raise MatrixError('matrix_reference_changed')
        report.update(status='NINE_FULL_FROZEN_WINDOWS_REPLAYS_COMPLETE_UNQUALIFIED',
            wakeRequest='DIAGNOSTIC_THREAD_PREVIOUS_STATE_RESTORED',
            allPackedPayloadsIdenticalAcrossRuns=len({r['payload']['sha256'] for r in report['runs']})==1,
            firstNativeQueriesIdenticalAcrossThreadCounts=all(baselines[t][2]==baselines[1][2] for t in (2,4)),
            firstTensorHashDifferencesAcrossThreadCounts={str(t):sum(baselines[t][1][key]!=baselines[1][1][key] for key in baselines[1][1]) for t in (2,4)})
    except (Exception,KeyboardInterrupt) as error:
        report.update(status='FAILED',errorType=type(error).__name__,
            code=str(error) if isinstance(error,(MatrixError,ReferenceError)) else 'Inspect retained private receipts and native logs.')
    finally:
        checkpoint()
    return report

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('archive','binary','models','out'): parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--bytes',type=int,required=True)
    parser.add_argument('--sha256',required=True)
    parser.add_argument('--runtime-profile-sha256',required=True)
    parser.add_argument('--sample-working-set',action='store_true')
    parser.add_argument('--overall-hours',type=int,default=OVERALL_SECONDS//3600,
                        help='Finite total allowance, 1–48 hours (default: 36).')
    parser.add_argument('--index-minutes',type=int,default=INDEX_SECONDS//60,
                        help='Finite allowance for each fresh index, 1–360 minutes (default: 240).')
    args=parser.parse_args()
    report=run_matrix(args)
    print(json.dumps({k:report.get(k) for k in ('status','code','productionQualified')}),flush=True)
    return 0 if report['status'].startswith('NINE_FULL_') else 1

if __name__=='__main__': raise SystemExit(main())
