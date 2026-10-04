"""Offline verification of the reduced private 1,024-location Mac reference.

The operator obtains the archive byte count and SHA-256 independently from
GitHub. No native execution, network, account, contribution or qualification.
Omitted preprocessing tensors are hashes only, not locally verified transports.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import stat
import struct
import zipfile

from calibration.quality import decoded_difference

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_SHA = '106c6bbbceb7b0c76892277c69dd7f1e88c7043584b1ca2313db216107aa5752'
MAC_BINARY = {'bytes':35490896, 'sha256':'e0c4dc80c848af33c76bcf0e82517839d131ad62a2013a247bd70e370984dfed'}
SHAPES = {'pixel-values':[3,224,224], 'normalized':[768], 'pooler-output':[768]}
LABELS = ('capture','repeat-1','repeat-2','repeat-3')
QUERY_NAMES = ('road','shop','landscape','forest','mountain','beach','city','village','desert','bridge','farm','snowy landscape')
HEX = re.compile(r'[a-f0-9]{64}\Z')
MAX_ARCHIVE_BYTES = 2*1024**3
MAX_ENTRIES = 50_000
MAX_JSON = 16*1024**2


class ReferenceError(ValueError):
    pass


def plain(path, *, directory=False):
    path = Path(path).absolute()
    if '..' in path.parts:
        raise ReferenceError('unsafe_reference_path')
    for parent in reversed(path.parents):
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:
            raise ReferenceError('unsafe_reference_path')
    info = path.lstat()
    if (not (stat.S_ISDIR if directory else stat.S_ISREG)(info.st_mode)
            or getattr(info,'st_file_attributes',0)&0x400):
        raise ReferenceError('unsafe_reference_path')
    return path


def sha(path):
    digest = hashlib.sha256()
    with plain(path).open('rb') as source:
        for block in iter(lambda:source.read(1024**2),b''): digest.update(block)
    return digest.hexdigest()


def pin(path):
    path = plain(path)
    return {'bytes':path.stat().st_size,'sha256':sha(path)}


def read(path):
    with plain(path).open('rb') as source: raw = source.read(MAX_JSON+1)
    if len(raw)>MAX_JSON:
        raise ReferenceError('reference_json_size_limit')
    return json.loads(raw)


def allowed_archive_name(name, directory=False):
    if directory:
        return name in (*LABELS,'pilot-control','native-logs','frozen-rgb')
    if name in ('full-reference-evidence.json','locations.tsv','study.json','search.json','frozen-rgb/manifest.json'):
        return True
    parts = name.split('/')
    if len(parts)!=2: return False
    folder, filename = parts
    if folder=='frozen-rgb':
        match = re.fullmatch(r'scene-(\d{4})-view-([0-3])\.rgb',filename)
        return bool(match and int(match[1])<1024)
    if folder=='native-logs':
        commands = {'layout','pilot-control-replay-index','pilot-control-replay-search',
                    *('full-1024-'+label+'-'+command for label in LABELS for command in ('index','search'))}
        return any(filename in (command+'.log',command+'.stderr.log') for command in commands)
    if folder not in (*LABELS,'pilot-control'): return False
    label = 'replay' if folder=='pilot-control' else folder
    if filename in ('scene-evidence.json','shard-000000.i8','shard-000000.mask',
                    label+'-results.json',label+'-checkpoint.json',label+'-search-results.json'):
        return True
    match = re.fullmatch(r'scene-(\d{4})-view-([0-3])-(normalized|pooler-output)\.f32le',filename)
    return bool(match and int(match[1])<(16 if folder=='pilot-control' else 1024))


def extract_pinned(archive, expected, target):
    if (not isinstance(expected,dict) or set(expected)!={'bytes','sha256'}
            or type(expected['bytes']) is not int or not 1<=expected['bytes']<=MAX_ARCHIVE_BYTES
            or not isinstance(expected['sha256'],str) or not HEX.fullmatch(expected['sha256'])
            or pin(archive)!=expected):
        raise ReferenceError('reference_archive_pin_mismatch')
    plain(target.parent,directory=True)
    with zipfile.ZipFile(archive) as packed:
        rows = packed.infolist()
        if not 1<=len(rows)<=MAX_ENTRIES or sum(row.file_size for row in rows)>MAX_ARCHIVE_BYTES:
            raise ReferenceError('reference_archive_size_limit')
        seen = set()
        for row in rows:
            name = row.filename.rstrip('/')
            kind = stat.S_IFMT(row.external_attr>>16)
            if (not name or any(part in ('','.','..') or ':' in part or '\\' in part for part in name.split('/'))
                    or name.casefold() in seen or kind not in (0,stat.S_IFREG,stat.S_IFDIR)
                    or row.flag_bits&1 or row.compress_type not in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED)
                    or row.file_size>MAX_JSON or not allowed_archive_name(name,row.is_dir())):
                raise ReferenceError('invalid_reference_archive_entry')
            seen.add(name.casefold())
        if shutil.disk_usage(target.parent).free<sum(row.file_size for row in rows)+1024**3:
            raise ReferenceError('reference_extraction_storage_required')
        target.mkdir(exist_ok=False)
        for row in rows:
            path = target.joinpath(*row.filename.rstrip('/').split('/'))
            if row.is_dir(): path.mkdir(exist_ok=True)
            else:
                path.parent.mkdir(exist_ok=True)
                with packed.open(row) as source,path.open('xb') as output:
                    shutil.copyfileobj(source,output,1024**2)
    if pin(archive)!=expected:
        raise ReferenceError('reference_archive_changed_during_read')


def model_pins():
    manifest = read(ROOT/'community/runtime_manifest.json')
    return [{'name':Path(row['path']).name,'bytes':row['bytes'],'sha256':row['sha256']}
            for row in manifest['files'] if row['path'].startswith('models/siglip-b16-224-canonical/')]


def verify_rgb(folder, source, models, count=1024):
    manifest = read(folder/'manifest.json')
    if (manifest.get('schemaVersion')!=1 or manifest.get('status')!='COMPLETE_RGB_BOUNDARY_ONLY'
            or manifest.get('productionQualified') is not False or manifest.get('totalLocations')!=count
            or manifest.get('sourceTsv')!={'name':'locations.tsv',**pin(source)} or manifest.get('modelFiles')!=models
            or manifest.get('boundary')!='native-four-view-thumbnail-rgb224'):
        raise ReferenceError('reference_rgb_identity_mismatch')
    rows = plain(source).read_text(encoding='utf-8').splitlines()
    if len(rows)!=count: raise ReferenceError('reference_source_geometry_mismatch')
    bits = lambda value:struct.pack('>d',value).hex()
    seen, expected = set(), {'manifest.json'}
    frames = manifest.get('frames',[])
    for frame in frames:
        ordinal,view = frame.get('ordinal'),frame.get('view')
        if (type(ordinal) is not int or ordinal not in range(count) or type(view) is not int
                or view not in range(4) or (ordinal,view) in seen):
            raise ReferenceError('reference_rgb_geometry_mismatch')
        row = rows[ordinal].split('\t')
        heading = math.fmod(float(row[4])+view*90,360)
        if heading<0: heading+=360
        name = f'scene-{ordinal:04}-view-{view}.rgb'
        info = frame.get('rgb',{})
        if (len(row)!=11 or frame.get('panoId')!=row[7] or frame.get('headingBits')!=bits(heading)
                or frame.get('pitchBits')!=bits(float(row[5])) or frame.get('zoomBits')!=bits(float(row[6]))
                or info.get('name')!=name or info.get('bytes')!=224*224*3
                or pin(folder/name)!={k:info[k] for k in ('bytes','sha256')}):
            raise ReferenceError('reference_rgb_transport_or_pose_mismatch')
        seen.add((ordinal,view)); expected.add(name)
    if len(seen)!=count*4 or {path.name for path in folder.iterdir()}!=expected:
        raise ReferenceError('reference_rgb_inventory_mismatch')
    return manifest


def verify_reduced_case(folder, label, count, queries, models, *, manifest=None):
    evidence = read(folder/'scene-evidence.json')
    frames = evidence.get('frames',[])
    if (evidence.get('schemaVersion')!=1 or evidence.get('status')!='NATIVE_SCENE_STUDY_COMPLETED_UNQUALIFIED'
            or evidence.get('productionQualified') is not False or evidence.get('selectedImageGraph')!='vision_model_fp32.onnx'
            or evidence.get('modelFiles')!=models or len(frames)!=count*4
            or manifest is not None and any(evidence.get(k)!=manifest[k] for k in ('frames','sourceTsv'))):
        raise ReferenceError('reference_native_identity_mismatch')
    frame_keys = {(f['ordinal'],f['view']) for f in frames}
    if (any(type(f['ordinal']) is not int or type(f['view']) is not int for f in frames)
            or frame_keys!={(i,v) for i in range(count) for v in range(4)}):
        raise ReferenceError('reference_frame_geometry_mismatch')
    source_pin = evidence.get('sourceTsv',{})
    if (source_pin.get('name')!='locations.tsv' or type(source_pin.get('bytes')) is not int or source_pin['bytes']<1
            or not isinstance(source_pin.get('sha256'),str) or not HEX.fullmatch(source_pin['sha256'])):
        raise ReferenceError('reference_native_identity_mismatch')
    for frame in frames:
        info = frame.get('rgb',{})
        if (info.get('name')!=f"scene-{frame['ordinal']:04}-view-{frame['view']}.rgb" or info.get('bytes')!=150528
                or not isinstance(info.get('sha256'),str) or not HEX.fullmatch(info['sha256'])):
            raise ReferenceError('reference_frame_geometry_mismatch')
    expected = {'scene-evidence.json','shard-000000.i8','shard-000000.mask',
                label+'-results.json',label+'-checkpoint.json',label+'-search-results.json'}
    hashes = {}
    for tensor in evidence.get('tensors',[]):
        key = tensor.get('ordinal'),tensor.get('view'),tensor.get('event')
        if (type(key[0]) is not int or type(key[1]) is not int or key[:2] not in frame_keys or key in hashes
                or key[2] not in SHAPES or tensor.get('shape')!=SHAPES[key[2]]
                or tensor.get('dtype')!='float32-little-endian'):
            raise ReferenceError('reference_tensor_geometry_mismatch')
        name = f'scene-{key[0]:04}-view-{key[1]}-{key[2]}.f32le'
        info = tensor.get('file',{})
        if (info.get('name')!=name or type(info.get('bytes')) is not int or info['bytes']!=math.prod(SHAPES[key[2]])*4
                or not isinstance(info.get('sha256'),str) or not HEX.fullmatch(info['sha256'])):
            raise ReferenceError('reference_tensor_geometry_mismatch')
        hashes[key] = info['sha256']
        if key[2]=='pixel-values': continue
        path = folder/name
        if pin(path)!={k:info[k] for k in ('bytes','sha256')}:
            raise ReferenceError('reference_tensor_transport_mismatch')
        values = struct.unpack('<768f',path.read_bytes())
        norm = sum(value*value for value in values)
        if not all(math.isfinite(value) for value in values) or norm<=0 or key[2]=='normalized' and abs(norm-1)>0.001:
            raise ReferenceError('invalid_reference_float_vector')
        expected.add(name)
    if (set(hashes)!={(i,v,event) for i in range(count) for v in range(4) for event in SHAPES}
            or {path.name for path in folder.iterdir()}!=expected):
        raise ReferenceError('reference_reduced_inventory_mismatch')
    payload = pin(folder/'shard-000000.i8')
    if payload['bytes']!=count*3080 or plain(folder/'shard-000000.mask').read_bytes()!=b'\x0f'*count:
        raise ReferenceError('reference_index_incomplete')
    blob = (folder/'shard-000000.i8').read_bytes()
    decoded_difference(blob,blob)
    for name in (label+'-results.json',label+'-checkpoint.json'):
        result = read(folder/name)
        if (result.get('completed') is not True or result.get('totalLocations')!=count or result.get('nextLocationIndex')!=count
                or any(result.get(k)!=0 for k in ('fetchErrors','inferenceErrors','incompleteLocations'))):
            raise ReferenceError('reference_native_case_incomplete')
    search = read(folder/(label+'-search-results.json'))
    saved = search.get('queries',[])
    if len(saved)!=len(queries): raise ReferenceError('reference_queries_incomplete')
    semantic = []
    for actual,wanted in zip(saved,queries):
        hits = actual.get('hits',[])
        if (any(actual.get(k)!=wanted[k] for k in ('name','query','mode')) or len(hits)!=count
                or {h['locationIndex'] for h in hits}!=set(range(count))
                or any(type(h['locationIndex']) is not int or type(h['viewOffset']) is not int or h['viewOffset'] not in range(4)
                       or type(h['similarity']) not in (int,float) or not math.isfinite(h['similarity']) for h in hits)
                or any(hits[i]['similarity']<hits[i+1]['similarity'] for i in range(len(hits)-1))):
            raise ReferenceError('reference_query_geometry_mismatch')
        semantic.append((actual['name'],actual['query'],actual['mode'],
                         [(h['locationIndex'],h['viewOffset'],h['similarity']) for h in hits]))
    return {'locations':count,'frames':len(frames),'tensorEvents':len(hashes),
            'normalizedAndPoolerTransportsVerified':count*8,'preprocessedHashesOnly':count*4,
            'payload':payload,'evidence':pin(folder/'scene-evidence.json'),
            'search':pin(folder/(label+'-search-results.json'))}, hashes, semantic


def verify_full_reference(root):
    receipt = read(root/'full-reference-evidence.json')
    commands = ['layout','pilot-control-replay-index','pilot-control-replay-search',
                *('full-1024-'+label+'-'+command for label in LABELS for command in ('index','search'))]
    if (receipt.get('status')!='FULL_FIXED_CAPTURE_AND_THREE_MAC_REPEATS_COMPLETE_UNQUALIFIED'
            or receipt.get('scope')!='private-full-scene-reference-1024' or receipt.get('productionQualified') is not False
            or receipt.get('phase')!='complete' or receipt.get('accountsCreated')!=0 or receipt.get('creditsChanged')!=0
            or receipt.get('binary')!=MAC_BINARY or receipt.get('fixtureSha256')!=FIXTURE_SHA
            or receipt.get('preprocessedTensorTransport')!='HASH_ONLY_NOT_EXPORTED'
            or [c['label'] for c in receipt.get('commands',[])]!=commands
            or any(c.get('status')!='COMPLETE' or type(c.get('exitCode')) is not int or c['exitCode']!=0 for c in receipt['commands'])
            or receipt.get('identicalPackedIndexesAndTensorHashes') is not True or receipt.get('identicalNativeQueryResults') is not True):
        raise ReferenceError('full_reference_not_complete_or_pinned')
    source = root/'locations.tsv'
    raw = plain(source).read_bytes()
    rows = [line.split(b'\t') for line in raw.splitlines()]
    if (sha(source)!=FIXTURE_SHA or len(rows)!=1024 or any(len(row)!=11 for row in rows)
            or len({row[7] for row in rows})!=1024):
        raise ReferenceError('full_reference_source_mismatch')
    study,search = read(root/'study.json'),read(root/'search.json')
    queries = search.get('queries',[])
    if (study.get('totalLocations')!=1024 or study.get('sceneFp32') is not True or study.get('embeddingBatchSize')!=16
            or study.get('imageEncoderSessions')!=1 or search.get('topK')!=1024 or search.get('resultPruneMeters')!=0
            or [q['name'] for q in queries]!=list(QUERY_NAMES)
            or any(q.get('query')!='a '+q['name'] or q.get('mode')!='textOnly' for q in queries)
            or study.get('queries')!=queries):
        raise ReferenceError('full_reference_settings_mismatch')
    models = model_pins()
    manifest = verify_rgb(root/'frozen-rgb',source,models)
    if sha(root/'frozen-rgb/manifest.json')!=receipt.get('frozenManifestSha256'):
        raise ReferenceError('full_reference_manifest_mismatch')
    runs = receipt.get('runs',[])
    if len(runs)!=5 or {(r['case'],r['label']) for r in runs}!={('pilot-control','replay'),*(('full-1024',label) for label in LABELS)}:
        raise ReferenceError('full_reference_repetitions_incomplete')
    control = next(r for r in runs if r['case']=='pilot-control')
    control_queries = read(root/'pilot-control/replay-search-results.json')['queries']
    if len(control_queries)!=3:
        raise ReferenceError('full_reference_control_queries_incomplete')
    checked_control,_,_ = verify_reduced_case(root/'pilot-control','replay',16,control_queries,models)
    for key in ('payload','evidence','search'):
        if checked_control[key]!=control[key]: raise ReferenceError('full_reference_control_pin_mismatch')
    bounds = receipt.get('pilotControlMetrics',{})
    cosine = bounds.get('cosine_similarity',{}).get('min')
    relative_l2 = bounds.get('relative_l2_error',{}).get('max')
    if (type(cosine) not in (int,float) or type(relative_l2) not in (int,float)
            or not math.isfinite(cosine) or not math.isfinite(relative_l2) or cosine<.9999 or relative_l2>.02):
        raise ReferenceError('full_reference_original_control_failed')
    summaries, first = [], None
    for label in LABELS:
        checked, hashes, semantic = verify_reduced_case(root/label,label,1024,queries,models,manifest=manifest)
        recorded = next(r for r in runs if r['label']==label)
        if any(checked[key]!=recorded[key] for key in ('payload','evidence','search')):
            raise ReferenceError('full_reference_case_pin_mismatch')
        if first is None: first = checked['payload'],hashes,semantic
        elif first!=(checked['payload'],hashes,semantic): raise ReferenceError('full_reference_repeat_difference')
        summaries.append({'label':label,**checked})
    expected_logs = {command+suffix for command in commands for suffix in ('.log','.stderr.log')}
    logs = root/'native-logs'
    if {path.name for path in plain(logs,directory=True).iterdir()}!=expected_logs:
        raise ReferenceError('full_reference_logs_incomplete')
    for command in commands[1:]:
        path = plain(logs/(command+'.stderr.log'))
        with path.open('rb') as stream: raw = stream.read(MAX_JSON+1)
        if len(raw)>MAX_JSON or b'[vision] ONNX Runtime global threads: 1, spinning disabled' not in raw.splitlines():
            raise ReferenceError('full_reference_shared_pool_not_observed')
    return {'referenceReceipt':pin(root/'full-reference-evidence.json'),'frozenManifest':pin(root/'frozen-rgb/manifest.json'),
            'source':pin(source),'validatedFullCases':summaries,'validatedPilotControl':checked_control,
            'fullRgbTransportsVerified':4096,'normalizedAndPoolerTransportsVerified':32896,
            'preprocessedTensorHashesOnly':16448,'pilotRgbTransport':'OMITTED_CHECKED_IN_MAC_RUNNER',
            'preprocessedTensorTransport':'HASH_ONLY_NOT_DOWNLOADED'}


def verify_archive(archive, expected, out):
    plain(out.parent,directory=True)
    out.mkdir(exist_ok=False)
    report = {'status':'INCOMPLETE','nativeCommands':0,'accountsCreated':0,'creditsChanged':0,'productionQualified':False}
    try:
        root = out/'artifact'
        extract_pinned(archive,expected,root)
        report.update(verify_full_reference(root),archive=expected,status='FULL_MAC_REFERENCE_TRANSPORT_VERIFIED_UNQUALIFIED')
    except (Exception,KeyboardInterrupt) as error:
        report.update(status='FAILED',errorType=type(error).__name__,
                      code=str(error) if isinstance(error,ReferenceError) else 'reference_validation_failed')
    finally:
        (out/'verification-receipt.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--sha256',required=True)
    parser.add_argument('--bytes',type=int,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args = parser.parse_args()
    report = verify_archive(args.archive,{'bytes':args.bytes,'sha256':args.sha256},args.out)
    print(json.dumps({key:report.get(key) for key in ('status','code','productionQualified')}))
    return 0 if report['status']=='FULL_MAC_REFERENCE_TRANSPORT_VERIFIED_UNQUALIFIED' else 1


if __name__=='__main__': raise SystemExit(main())
