"""Private saved Object indexes and search; never grants processing/publication.

Packed records stay unchanged. Frozen diagnostic data remains explicitly marked;
none of this module's receipts can be used as Community or device approval.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import sys
import tempfile
import threading
import zipfile
import zlib

REPO = Path(os.path.abspath(__file__)).parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from community.bootstrap import RELEASE, download_file, files_for_platform, runtime_platform
from community.local_scene_packets import canonical
from community.local_scene_pilot import atomic_json, immutable
from community.mac_starter import regular
from community.object_features import MAX_BYTES, MAX_LOCATIONS, MAX_SOURCE_BYTES, validate_feature_contents
from community.object_index import (COMMON_MODEL_SHA256, RUNTIME_IDENTITY, OBJECT_FEATURE,
    CONFIDENCE_FLOORS, manifest_file_names, verify_arguments, object_search_input, map_from_object_search)
from community.process_owner import run_owned
from community.vision_index import assert_not_live_vision_path, file_identity, inference_environment

CONTRACT = 'vision-local-object-library-v1'
MAX_ARCHIVE = 40 * 1024**2
MANIFEST_LIMIT = 1024**2
# Preserve the VISION contract and numerical provenance, without workstation paths.
SCALARS = ('version feature architecture sourceId sourceBytes sourceSha256 modelSha256 runtimeIdentity '
    'totalLocations indexedLocations globalStart globalIdMode minimumGlobalLocation maximumGlobalLocation '
    'imageSize tileGrid tileOverlap minimumRelativeClassScore smallObjectRelativeClassScore '
    'fullTileArtifactThreshold rankingStrategy viewStrategy viewCount faceSize faceFov bandsPerFace '
    'bandWidth bandHeight bandOffset bandFov recordBytes positionPolicy coverage fetchErrors inferenceErrors '
    'permanentlyInvalidLocations completed frozenViewsManifestSha256').split()
ENTRY = ('file recordBytes records bytes sha256 id name storageFloor codec codebookSha256 '
    'embeddingDimensions proposalsPerLocation policy implementationIdentity viewCount blurAreaFractionExclusive '
    'tileGrid tunnelVisionProbabilityInclusive tunnelEvidencePolicy tunnelEvidenceManifestSha256 '
    'tunnelEvidenceQualifiedViews tunnelEvidenceMapMatchRecords tunnelEvidenceVisualScoreRecords '
    'keptViews blurRejectedViews darkTunnelRejectedViews fullyRejectedLocations permanentlyInvalidLocations '
    'invalidLocationPolicy protectedAuthorityManifestSha256').split()


def require(value, code='invalid_local_object_index'):
    if not value:
        raise ValueError(code)


def strict_json(raw):
    def pairs(values):
        result = {}
        for key, value in values:
            require(key not in result)
            result[key] = value
        return result
    def constant(_):
        raise ValueError('invalid_local_object_index')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def safe_manifest(value):
    require(isinstance(value, dict))
    result = {k:value[k] for k in SCALARS if k in value}
    result['sourceTsv'] = 'locations.tsv'
    contracts = value.get('contractVersions')
    countries = value.get('countries')
    require(isinstance(contracts,dict) and all(type(v) is int for v in contracts.values())
        and isinstance(countries,list) and all(isinstance(v,str) and len(v)<=100 for v in countries))
    result['contractVersions'],result['countries'] = contracts,countries
    for key in ('offsets','metadata','globalIds','semantic','viewQuality','classes','hotConcepts'):
        entry = value.get(key)
        if key == 'viewQuality' and not entry:
            continue
        if key in ('classes','hotConcepts'):
            require(isinstance(entry,list) and len(entry)<=100 and all(isinstance(e,dict) for e in entry))
            result[key] = [{k:e[k] for k in ENTRY if k in e} for e in entry]
        else:
            require(isinstance(entry,dict))
            result[key] = {k:entry[k] for k in ENTRY if k in entry}
    def scalar(v):
        return v is None or type(v) in (bool,int,float,str)
    require(all(scalar(result[k]) for k in SCALARS if k in result))
    for key in ('offsets','metadata','globalIds','semantic','viewQuality','classes','hotConcepts'):
        entries = result.get(key,[])
        if isinstance(entries,dict):entries=[entries]
        require(all(scalar(v) for e in entries for v in e.values()))
    return result


def checked_bundle(manifest, files, source):
    require(safe_manifest(manifest)==manifest)
    total = manifest.get('indexedLocations')
    require(type(total) is int and 0<total<=MAX_LOCATIONS and manifest.get('totalLocations')==total
        and manifest.get('version')==4 and manifest.get('feature')==OBJECT_FEATURE
        and manifest.get('completed') is True and manifest.get('modelSha256')==COMMON_MODEL_SHA256
        and manifest.get('runtimeIdentity')==RUNTIME_IDENTITY
        and isinstance(manifest.get('sourceId'),str)
        and re.fullmatch(r'[A-Za-z0-9_-]{1,120}',manifest['sourceId'])
        and type(manifest.get('globalStart')) is int and 0<=manifest['globalStart']<2**53
        and manifest.get('sourceBytes')==len(source) and manifest.get('sourceSha256')==sha(source)
        and 0<len(source)<=MAX_SOURCE_BYTES and len(files)<=87 and sum(map(len,files.values()))<=MAX_BYTES)
    names = manifest_file_names(manifest)
    require(len(names)==len(set(names)) and set(names)==set(files)
        and all(re.fullmatch(r'[a-z0-9][a-z0-9.-]*\.bin',n) for n in names))
    entries = [manifest[k] for k in ('offsets','metadata','globalIds','semantic')]
    entries += manifest['classes']+manifest['hotConcepts']
    if manifest.get('viewQuality'):entries.append(manifest['viewQuality'])
    for e in entries:
        raw = files[e['file']]
        require(type(e.get('bytes')) is int and len(raw)==e['bytes'] and sha(raw)==e.get('sha256'))
    validate_feature_contents(manifest,files,source)
    fields = [line.split('\t') for line in source.decode('utf-8').splitlines()]
    require(len(fields)==total and len({f[7] for f in fields})==total
        and all(0<len(f[7])<=1000 for f in fields))
    global_ids=files['global-location-ids.bin']
    require(len(global_ids)==12*total)
    identities=set()
    for position,row in enumerate(fields):
        require(re.fullmatch(r'[0-9]{1,16}',row[11]))
        number=int(row[11]);record=global_ids[position*12:(position+1)*12]
        require(0<=number<2**53 and number not in identities
            and int.from_bytes(record[:8],'little')==number
            and int.from_bytes(record[8:],'little')==zlib.crc32(record[:8]))
        identities.add(number)
    return fields


def archive_bytes(index_dir, source_tsv, label='My saved Objects'):
    index_dir = regular(index_dir,directory=True)
    manifest_path = regular(index_dir/'manifest.json')
    require(manifest_path.stat().st_size<=MANIFEST_LIMIT)
    manifest = safe_manifest(strict_json(manifest_path.read_bytes()))
    source_path = regular(source_tsv)
    require(source_path.stat().st_size<=MAX_SOURCE_BYTES)
    source = source_path.read_bytes()
    files,total = {},0
    for name in manifest_file_names(manifest):
        require(isinstance(name,str) and re.fullmatch(r'[a-z0-9][a-z0-9.-]*\.bin',name))
        path=regular(index_dir/name);total+=path.stat().st_size
        require(total<=MAX_BYTES)
        files[name]=path.read_bytes()
    checked_bundle(manifest,files,source)
    return make_archive(manifest,files,source,label)


def make_archive(manifest, files, source, label):
    require(isinstance(label,str) and 0<len(label.strip())<=200 and all(ord(c)>=32 for c in label))
    content = {**files,'manifest.json':canonical(manifest)+b'\n','locations.tsv':source}
    descriptor = {'contract':CONTRACT,'label':label.strip(),
        'files':{name:{'bytes':len(raw),'sha256':sha(raw)} for name,raw in sorted(content.items())}}
    memory=io.BytesIO()
    with zipfile.ZipFile(memory,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for name,raw in sorted({**content,'object-library.json':canonical(descriptor)+b'\n'}.items()):
            info=zipfile.ZipInfo(name);info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=(stat.S_IFREG|0o600)<<16
            archive.writestr(info,raw)
    require(memory.tell()<=MAX_ARCHIVE,'local_object_archive_limit')
    return memory.getvalue()


def read_archive(raw):
    require(isinstance(raw,bytes) and 0<len(raw)<=MAX_ARCHIVE,'local_object_archive_limit')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries=archive.infolist();names=[e.filename for e in entries]
        require(6<=len(entries)<=90 and len(names)==len(set(names))
            and {'manifest.json','locations.tsv','object-library.json'}<=set(names)
            and all(re.fullmatch(r'[a-z0-9][a-z0-9.-]*',e.filename) and not e.flag_bits&1
                and stat.S_IFMT(e.external_attr>>16) in (0,stat.S_IFREG)
                and e.compress_type in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED) for e in entries)
            and sum(e.file_size for e in entries)<=MAX_BYTES+3*MANIFEST_LIMIT
            and archive.getinfo('object-library.json').file_size<=64*1024
            and archive.getinfo('manifest.json').file_size<=MANIFEST_LIMIT
            and archive.getinfo('locations.tsv').file_size<=MAX_SOURCE_BYTES)
        descriptor=strict_json(archive.read('object-library.json'))
        require(isinstance(descriptor,dict) and set(descriptor)=={'contract','label','files'}
            and descriptor['contract']==CONTRACT and isinstance(descriptor['label'],str)
            and 0<len(descriptor['label'])<=200 and all(ord(c)>=32 for c in descriptor['label'])
            and isinstance(descriptor['files'],dict) and set(descriptor['files'])==set(names)-{'object-library.json'})
        content={}
        for name,pin in descriptor['files'].items():
            require(isinstance(pin,dict) and set(pin)=={'bytes','sha256'}
                and type(pin['bytes']) is int and archive.getinfo(name).file_size==pin['bytes'])
            content[name]=archive.read(name)
            require(sha(content[name])==pin['sha256'])
    manifest=strict_json(content.pop('manifest.json'));source=content.pop('locations.tsv')
    fields=checked_bundle(manifest,content,source)
    identity=sha(canonical(descriptor['files']))
    return identity,descriptor,manifest,source,content,fields


def runtime_entries():
    return files_for_platform(json.loads(Path(__file__).with_name('runtime_manifest.json').read_text()),
        runtime_platform(),lane='object')


def setup_runtime(root, *, allow_downloads=False, downloader=download_file):
    root=regular(root,directory=True,missing=True)
    assert_not_live_vision_path(root)
    for item in runtime_entries():
        target=regular(root/item['path'],missing=True)
        if file_identity(target)!={'bytes':item['bytes'],'sha256':item['sha256']}:
            require(allow_downloads,'local_object_setup_required')
            target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
            partial=regular(target.with_name(target.name+'.partial'),missing=True)
            downloader(RELEASE+'/'+item['asset'],partial,item)
            require(file_identity(partial)=={'bytes':item['bytes'],'sha256':item['sha256']},'local_object_runtime_changed')
            os.replace(partial,target)
        if item.get('executable'):target.chmod(0o755)
    binary=root/('bin/vision-object.exe' if sys.platform=='win32' else 'object-runtime/vision-object')
    return binary,root/'models/object-hybrid-v1'


class ObjectLibrary:
    def __init__(self,root):
        self.root=regular(root,directory=True,missing=True)
        assert_not_live_vision_path(self.root)
        self.root.mkdir(mode=0o700,parents=True,exist_ok=True)
        with self.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS bundles(
                id TEXT PRIMARY KEY,label TEXT NOT NULL,locations INTEGER NOT NULL,ordinal INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS locations(pano TEXT PRIMARY KEY,bundle TEXT NOT NULL,
                country TEXT NOT NULL,generation TEXT NOT NULL);''')

    def db(self):
        return sqlite3.connect(regular(self.root/'objects.sqlite',missing=True),timeout=20)

    @contextmanager
    def writing(self):
        from community.background import single_instance
        with single_instance(self.root):yield

    def status(self):
        with self.db() as db:
            return {'locations':db.execute('SELECT count(*) FROM locations').fetchone()[0],
                'indexes':db.execute('SELECT count(*) FROM bundles').fetchone()[0],
                'countries':[v[0] for v in db.execute('SELECT DISTINCT country FROM locations WHERE country!="" ORDER BY country')],
                'generations':[v[0] for v in db.execute('SELECT DISTINCT generation FROM locations WHERE generation!="" ORDER BY generation')],
                'localOnly':True,'processingEnabled':False,'communitySubmissionAllowed':False}

    def native(self, command, job, *, runner=None):
        if runner is not None:
            runner(command,job)
            return
        with (job/'stdout.log').open('wb') as out,(job/'stderr.log').open('wb') as err:
            result=run_owned(command,env=inference_environment(job),cwd=job,stdout=out,stderr=err,timeout=150)
        if result.returncode:
            raise ValueError('local_object_native_failed')

    def import_archive(self,raw,runtime_root,*,runner=None,verifier=setup_runtime):
        identity,descriptor,manifest,source,files,fields=read_archive(raw)
        binary,_=verifier(runtime_root)
        with self.writing(),self.db() as db:
            if db.execute('SELECT 1 FROM bundles WHERE id=?',(identity,)).fetchone():
                return {'added':0,'alreadyPresent':True,'locations':len(fields)}
            require(not any(db.execute('SELECT 1 FROM locations WHERE pano=?',(f[7],)).fetchone() for f in fields),
                'local_object_overlap')
            # A retained ZIP/half-copy can be resumed, but becomes searchable only
            # after the pinned native verifier succeeds and the SQL commit lands.
            target=regular(self.root/identity,directory=True,missing=True)
            target.mkdir(mode=0o700,exist_ok=True)
            immutable(target/'saved-objects.zip',raw)
            for name,body in {**files,'manifest.json':canonical(manifest)+b'\n','locations.tsv':source}.items():
                immutable(target/name,body)
            with tempfile.TemporaryDirectory(prefix='verify-',dir=self.root) as temp:
                job=Path(temp)
                try:
                    atomic_json(job/'native-manifest.json',{**manifest,'sourceTsv':str(target/'locations.tsv')})
                    command=[str(binary),*verify_arguments(source_tsv=target/'locations.tsv',output_dir=target,
                        source_id=manifest['sourceId'],total=len(fields),global_start=manifest['globalStart'],full=True)]
                    command[command.index('--manifest')+1]=str(job/'native-manifest.json')
                    self.native(command,job,runner=runner)
                    log=regular(job/'stdout.log');require(log.stat().st_size<=MANIFEST_LIMIT)
                    verified=strict_json(log.read_bytes())
                    require(verified.get('valid') is True and verified.get('full') is True
                        and verified.get('indexVersion')==4 and verified.get('indexedLocations')==len(fields)
                        and verified.get('sourceId')==manifest['sourceId'],'local_object_native_verification_failed')
                except BaseException:
                    self.retain_logs(job)
                    raise
            ordinal=db.execute('SELECT coalesce(max(ordinal+locations),0) FROM bundles').fetchone()[0]
            db.execute('INSERT INTO bundles VALUES(?,?,?,?)',(identity,descriptor['label'],len(fields),ordinal))
            db.executemany('INSERT INTO locations VALUES(?,?,?,?)',[(f[7],identity,f[8],f[9]) for f in fields])
            atomic_json(target/'local-receipt.json',{'contract':CONTRACT,'scope':'PRIVATE_IMPORTED_INDEX_ONLY',
                'bundleId':identity,'locations':len(fields),'diagnostic': 'frozenViewsManifestSha256' in manifest,
                'processingApproved':False,'communitySubmissionAllowed':False})
            return {'added':len(fields),'alreadyPresent':False,'locations':len(fields)}

    def retain_logs(self,job):
        import time
        folder=self.root/'diagnostics'/str(time.time_ns());folder.mkdir(mode=0o700,parents=True)
        for name in ('stdout.log','stderr.log'):
            path=regular(job/name,missing=True)
            if path.exists():shutil.copy2(path,folder/name)

    def search(self,query,runtime_root,*,runner=None,verifier=setup_runtime):
        require(isinstance(query,dict) and set(query)=={'prompt','confidence','country','generation','resultCount'},
            'invalid_local_object_query')
        prompt,country,generation,count=(query[k] for k in ('prompt','country','generation','resultCount'))
        require(isinstance(prompt,str) and 0<len(prompt.strip())<=1000 and isinstance(query['confidence'],str)
            and query['confidence'] in CONFIDENCE_FLOORS
            and isinstance(country,str) and len(country)<=100 and isinstance(generation,str) and len(generation)<=30
            and type(count) is int and 1<=count<=200,'invalid_local_object_query')
        binary,models=verifier(runtime_root)
        with self.writing(),self.db() as db:
            bundles=db.execute('SELECT id,locations,ordinal FROM bundles ORDER BY ordinal').fetchall()
            require(bundles,'local_object_library_empty')
            hits=[];original_ids={};total=sum(b[1] for b in bundles)
            # CoreML preparation is expensive on first use. Reuse only this
            # library's private cache for the exact pinned platform runtime.
            cache=regular(self.root/'model-cache'/sha(canonical(runtime_entries())),directory=True,missing=True)
            cache.mkdir(mode=0o700,parents=True,exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='search-',dir=self.root) as temp:
                job=Path(temp)
                try:
                    for identity,locations,offset in bundles:
                        folder=regular(self.root/identity,directory=True)
                        identity2,_,manifest,source,files,fields=read_archive(regular(folder/'saved-objects.zip').read_bytes())
                        require(identity==identity2 and locations==len(fields),'local_object_saved_index_changed')
                        for name,body in {**files,'manifest.json':canonical(manifest)+b'\n','locations.tsv':source}.items():
                            require(regular(folder/name).read_bytes()==body,'local_object_saved_index_changed')
                        source_entry={'id':manifest['sourceId'],'sourceTsv':str(folder/'locations.tsv'),
                            'indexDir':str(folder),'manifestPath':str(job/'native-manifest.json'),
                            'globalStart':manifest['globalStart'],'indexedLocations':locations}
                        atomic_json(job/'native-manifest.json',{**manifest,'sourceTsv':source_entry['sourceTsv']})
                        request=object_search_input(prompt,[source_entry],confidence=query['confidence'],result_count=1000,
                            max_per_country=1000,countries=[country] if country else [],country_mode='include' if country else 'all',
                            camera_generations=[generation] if generation else [],model_dir=models,model_cache=cache)
                        request['resultPruneMeters']=0
                        atomic_json(job/'input.json',request)
                        output=regular(job/'output.json',missing=True)
                        if output.exists():output.unlink()
                        self.native([str(binary),'search','--input',str(job/'input.json'),'--output',str(output)],job,runner=runner)
                        require(output.stat().st_size<=8*1024**2,'local_object_search_output_limit')
                        result=strict_json(output.read_bytes())
                        require(result.get('contractVersion')==2 and result.get('totalLocations')==locations
                            and isinstance(result.get('queries'),list) and len(result['queries'])==1,'local_object_search_incomplete')
                        require(result['queries'][0].get('mode')=='objects')
                        found=result['queries'][0].get('hits');require(isinstance(found,list) and len(found)<=locations)
                        seen=set();positions={int(row[11]):position for position,row in enumerate(fields)}
                        for hit in found:
                            require(isinstance(hit,dict))
                            global_id,score=hit.get('locationIndex'),hit.get('similarity')
                            require(type(global_id) is int and global_id in positions
                                and type(score) in (int,float) and math.isfinite(score)
                                and CONFIDENCE_FLOORS[query['confidence']]<=score<=1)
                            position=positions[global_id]
                            require(position not in seen)
                            seen.add(position)
                            location=hit.get('location');require(isinstance(location,dict) and isinstance(hit.get('object'),dict))
                            obj=hit['object']
                            require(type(hit.get('viewOffset')) is int and 0<=hit['viewOffset']<6
                                and obj.get('lane') in ('common','hot','semantic')
                                and isinstance(obj.get('className'),str) and len(obj['className'])<=1000
                                and type(obj.get('supportCount')) is int and 0<=obj['supportCount']<=255)
                            for key,low,high in [('heading',0,360),('pitch',-90,90),('zoom',0,5),('confidence',0,1),('bboxArea',0,1)]:
                                require(type(obj.get(key)) in (int,float) and math.isfinite(obj[key]) and low<=obj[key]<=high)
                            row=fields[position]
                            require(location.get('panoId')==row[7] and location.get('country')==row[8]
                                and location.get('cameraGeneration')==row[9]
                                and all(type(location.get(k)) in (float,int) and math.isfinite(location[k])
                                    and abs(location[k]-float(row[col]))<=1e-5 for k,col in [('lat',2),('lng',3)]))
                            require(not country or location['country']==country)
                            require(not generation or location['cameraGeneration']==generation)
                            original_ids[row[7]]=global_id
                            hits.append({**hit,'locationIndex':offset+position})
                    from community.rank import prune_nearby
                    from community.mma import build_map
                    document=map_from_object_search({'totalLocations':total,'queries':[{'hits':hits}]},prompt=prompt,
                        output_name='My VISION Object results',result_count=min(10000,len(hits) or 1),max_per_country=10000,
                        min_score=CONFIDENCE_FLOORS[query['confidence']])
                    coordinates=[]
                    for row in document['customCoordinates']:
                        kept=prune_nearby([*coordinates,row])
                        if len(kept)>len(coordinates):coordinates.append(row)
                        if len(coordinates)>=count:break
                    for rank,row in enumerate(coordinates,1):
                        row['extra']['visionRank']=rank
                        row['extra']['visionOriginalGlobalLocationId']=original_ids[row['panoId']]
                    return {'ok':True,'locations':total,'indexes':len(bundles),
                        'map':build_map('My VISION Object results',coordinates),'localOnly':True,'uploads':0}
                except BaseException:
                    self.retain_logs(job)
                    raise


def task(data_dir,runtime_root,action,*,raw=None,query=None,stop):
    """Isolate disk/model operations; cancellation exits only this owned task."""
    runtime_root=regular(runtime_root,directory=True)
    tasks=regular(runtime_root/'local-object-tasks',directory=True,missing=True);tasks.mkdir(mode=0o700,exist_ok=True)
    library=ObjectLibrary(Path(data_dir)/'object-library')
    with tempfile.TemporaryDirectory(prefix='task-',dir=tasks) as temp:
        folder=Path(temp);marker=folder/'stop';done=threading.Event()
        request={'dataDir':str(data_dir),'runtimeRoot':str(runtime_root/'local-object-runtime'),
            'action':action,'query':query,'stopFile':str(marker)}
        if raw is not None:immutable(folder/'input.zip',raw)
        atomic_json(folder/'request.json',request)
        def cancel():
            while not done.wait(.1):
                if stop.is_set():
                    immutable(marker,b'stop\n')
                    return
        watcher=threading.Thread(target=cancel,daemon=True);watcher.start()
        logs=library.root/'diagnostics'/folder.name;logs.mkdir(mode=0o700,parents=True)
        try:
            with (logs/'stdout.log').open('xb') as out,(logs/'stderr.log').open('xb') as err:
                result=run_owned([sys.executable,'-I','-B',str(Path(__file__).absolute()),'--task',str(folder/'request.json')],
                    env=inference_environment(folder),cwd=REPO,stdout=out,stderr=err,timeout=3600 if action=='setup' else 600)
            if stop.is_set():raise ValueError('library_search_cancelled')
            response_path=regular(folder/'response.json',missing=True)
            require(response_path.exists(),'local_object_action_failed')
            require(response_path.stat().st_size<=4*1024**2,'local_object_search_output_limit')
            response=strict_json(response_path.read_bytes())
            if result.returncode or 'error' in response:
                raise ValueError(response.get('error','local_object_action_failed'))
            return response
        finally:
            done.set();watcher.join(1)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task',type=Path)
    parser.add_argument('--index',type=Path)
    parser.add_argument('--source-tsv',type=Path)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--label',default='My saved Objects')
    args=parser.parse_args()
    if not args.task:
        require(args.index and args.source_tsv and args.output,'local_object_export_paths_required')
        assert_not_live_vision_path(args.output)
        immutable(args.output,archive_bytes(args.index,args.source_tsv,args.label))
        print(json.dumps({'sha256':sha(regular(args.output).read_bytes()),'localOnly':True,'processingApproved':False}))
        return
    path=regular(args.task);require(path.stat().st_size<=8192)
    value=strict_json(path.read_bytes())
    require(isinstance(value,dict) and set(value)=={'dataDir','runtimeRoot','action','query','stopFile'})
    marker=regular(Path(value['stopFile']),missing=True)
    require(not marker.exists(),'library_search_cancelled')
    done=threading.Event()
    def cancel():
        while not done.wait(.1):
            if marker.exists():os._exit(79)
    threading.Thread(target=cancel,daemon=True).start()
    try:
        runtime=Path(value['runtimeRoot']);library=ObjectLibrary(Path(value['dataDir'])/'object-library')
        if value['action']=='setup':
            setup_runtime(runtime,allow_downloads=True);result={'ready':True,'processingApproved':False}
        elif value['action']=='import':
            upload=regular(path.parent/'input.zip');require(upload.stat().st_size<=MAX_ARCHIVE)
            result=library.import_archive(upload.read_bytes(),runtime)
        elif value['action']=='search':
            result=library.search(value['query'],runtime)
        else:raise ValueError('invalid_local_object_action')
        atomic_json(path.parent/'response.json',result)
    except Exception as error:
        code=str(error)
        atomic_json(path.parent/'response.json',{'error':code if re.fullmatch('[a-z_]{1,70}',code) else 'local_object_action_failed'})
        raise
    finally:done.set()


if __name__=='__main__':main()
