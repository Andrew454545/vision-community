"""Private MMA queues. Local reference checks never grant Community authority."""
from __future__ import annotations

import base64
import hashlib
import json
import math
from pathlib import Path
import re
import secrets
import sqlite3
import zipfile

from calibration.quality import decoded_difference
from .four_view import BYTES_PER_LOCATION
from .local_scene_campaign import PERSONAL_CONTRACT, PACKET_LOCATIONS, validate_manifest
from .local_scene_packets import canonical, digest, validate_packet
from .local_scene_pilot import CheckedRuntime, immutable
from .local_scene_qualification import BOUNDS, fixed_policy, read_document
from .mac_starter import regular
from .mma import _coordinates
from .rank import canonicalize_country

RECEIPT = 'vision-personal-scene-approval-v1'
MAX_MAP_BYTES = 20*1024**2
MAX_MAP_ROWS = 100_000


def personal_approval(report,policy,installation_id,profile,threads,policy_sha):
    if (report.get('status') != 'COMPLETE' or report.get('complete') is not True
            or report.get('inputIdentity') != 'SEALED_SYNTHETIC_RGB_BYTES'
            or report.get('locations') != 112 or report.get('views') != 448
            or report.get('runtimeProfile') != profile
            or policy.document['runtimeProfileSha256'] != profile['sha256']):
        raise ValueError('personal_computer_check_required')
    canary = report.get('submission',{}).get('canary',{})
    records = canary.get('records',[])
    if not isinstance(records,list) or len(records) != 112 or canary.get('runtimeProfile') != profile:
        raise ValueError('personal_computer_check_required')
    try:
        decoded = [base64.b64decode(row,validate=True) for row in records]
    except (ValueError,TypeError):
        raise ValueError('personal_computer_check_required') from None
    if any(len(row) != BYTES_PER_LOCATION for row in decoded):
        raise ValueError('personal_computer_check_required')
    body = b''.join(decoded)
    if hashlib.sha256(body).hexdigest() not in (report.get('payloadSha256'),) or canary.get('outputSha256') != report['payloadSha256']:
        raise ValueError('personal_computer_check_required')
    identity = report.get('identity',{})
    if any(canary.get(k) != identity.get(k) for k in ('fixtureSha256','referenceSha256','parentReferenceSha256')):
        raise ValueError('personal_computer_check_required')
    metrics = decoded_difference(body,policy.pinned_inputs()['referenceBytes'])
    if not policy.evaluate(profile['sha256'],identity,metrics)[0]:
        raise ValueError('personal_computer_check_failed')
    value = {'contract':RECEIPT,'installationId':installation_id,'runtimeProfile':profile,
        'inferenceThreads':threads,'reportSha256':digest(report),'policySha256':policy_sha,
        'metrics':metrics,'locations':112,'views':448,'scope':'LOCAL_PERSONAL_ONLY','productionQualified':False}
    value['sha256'] = digest(value)
    return value


def validate_personal_approval(value,installation_id,profile):
    if (not isinstance(value,dict) or value.get('contract') != RECEIPT or value.get('scope') != 'LOCAL_PERSONAL_ONLY'
            or value.get('productionQualified') is not False or value.get('installationId') != installation_id
            or value.get('runtimeProfile') != profile or value.get('locations') != 112 or value.get('views') != 448
            or type(value.get('inferenceThreads')) is not int or value.get('inferenceThreads') not in (1,2,4)
            or value.get('sha256') != digest({k:v for k,v in value.items() if k!='sha256'})):
        raise ValueError('personal_computer_check_required')
    try:
        cosine = value['metrics']['cosine_similarity']['min']
        error = value['metrics']['relative_l2_error']['max']
        if (not math.isfinite(cosine) or not math.isfinite(error)
                or not BOUNDS['minimumViewCosine'] <= cosine <= 1 or not 0 <= error <= BOUNDS['maximumViewRelativeL2']):
            raise ValueError()
    except (KeyError,ValueError,TypeError):
        raise ValueError('personal_computer_check_failed') from None
    return value


def checked_profiles(roots,runtime_root,installation_id):
    runtime = CheckedRuntime()
    results = {}
    for source in roots:
        checks = regular(Path(source)/'checks'/installation_id,directory=True,missing=True)
        if not checks.exists():
            continue
        for path in sorted(checks.glob('readiness-*.json')):
            saved = read_document(path)
            for item in saved.get('reports',[]):
                if (not isinstance(item,dict) or item.get('threads') not in (1,2,4)
                        or not re.fullmatch('attempt-[a-f0-9]{24}',str(item.get('attempt')))
                        or not re.fullmatch('[a-f0-9]{64}',str(item.get('policySha256')))):
                    raise ValueError('personal_computer_check_required')
                if item['threads'] in results:
                    continue
                policy_path = regular(checks/'policy-cache'/item['policySha256']/'policy.json',missing=True)
                if not policy_path.exists():
                    continue
                policy = fixed_policy(policy_path,item['policySha256'])
                report = read_document(checks/item['attempt']/'canary-report.json')
                profile = runtime(runtime_root,inference_threads=item['threads'])[2]
                try:
                    results[item['threads']] = personal_approval(report,policy,installation_id,profile,item['threads'],item['policySha256'])
                except ValueError:
                    continue  # A failed faster profile must never become available.
    if 1 not in results:
        raise ValueError('personal_computer_check_required')
    return [results[k] for k in sorted(results)]


def map_rows(document,fallback_country=''):
    countries = set(regular(Path(__file__).with_name('country-names.txt')).read_text().splitlines())
    if fallback_country and fallback_country not in countries:
        raise ValueError('invalid_personal_country')
    rows = _coordinates(document)
    if not rows or len(rows) > MAX_MAP_ROWS:
        raise ValueError('personal_map_size_limit')
    seen, output, metadata = set(), [], []
    for original in rows:
        if not isinstance(original,dict):
            raise ValueError('invalid_personal_location')
        pano = original.get('panoId') or original.get('pano_id') or original.get('pano')
        if not isinstance(pano,str) or not re.fullmatch('[A-Za-z0-9_-]{4,80}',pano):
            raise ValueError('personal_map_requires_panorama_ids')
        if pano in seen:
            continue
        seen.add(pano)
        extra = original.get('extra') if isinstance(original.get('extra'),dict) else {}
        tags = extra.get('tags',[])
        tags = [t.strip() for t in tags if isinstance(t,str) and 0<len(t.strip())<=200 and all(ord(c)>=32 for c in t)] if isinstance(tags,list) else []
        tags = list(dict.fromkeys(tags))[:128]
        country = ''
        for value in [original.get('country'),extra.get('country'),*tags]:
            candidate = canonicalize_country(value) if isinstance(value,str) else ''
            if candidate in countries:
                country = candidate
                break
        country = country or fallback_country
        if not country:
            raise ValueError('personal_map_country_required')
        try:
            values = [float(original['lat']),float(original.get('lng',original.get('lon'))),
                      float(original.get('heading') or 0),float(original.get('pitch') or 0),float(original.get('zoom') or 0)]
        except (KeyError,ValueError,TypeError):
            raise ValueError('invalid_personal_location') from None
        lat,lng,heading,pitch,zoom = values
        if (not all(math.isfinite(v) for v in values) or not -90<=lat<=90 or not -180<=lng<=180
                or not -90<=pitch<=90 or not 0<=zoom<=5):
            raise ValueError('invalid_personal_location')
        heading = math.fmod(heading,360)
        if heading<0:heading+=360
        generation = extra.get('visionCameraGeneration',original.get('cameraGeneration','unknown'))
        if generation not in ('gen1','gen2','gen3','gen4','badcam','unknown'):
            generation = 'unknown'
        road = extra.get('visionHasRoadName',original.get('hasRoadName'))
        pose = [format(v,'.17g') for v in (lat,lng,heading,pitch,zoom)]
        output.append('\t'.join(['personal',str(len(output)),*pose,pano,country,generation,'true' if road is True else 'false']))
        metadata.append({'panoId':pano,'tags':tags})
    return output,metadata,len(rows)-len(output)


def sanitized_map(document,fallback_country=''):
    """Persist only map poses and supported metadata, never arbitrary MMA fields."""
    lines,metadata,duplicates = map_rows(document,fallback_country)
    coordinates = []
    for line,meta in zip(lines,metadata):
        fields = line.split('\t')
        coordinates.append(dict(zip(('lat','lng','heading','pitch','zoom'),map(float,fields[2:7])),
            panoId=fields[7],country=fields[8],extra={'tags':meta['tags'],
                'visionCameraGeneration':fields[9],'visionHasRoadName':fields[10]=='true'}))
    name = document.get('name','My MMA map') if isinstance(document,dict) else 'My MMA map'
    if not isinstance(name,str) or len(name)>300 or any(ord(c)<32 for c in name):
        name = 'My MMA map'
    return {'name':name,'customCoordinates':coordinates},duplicates


def prepare_map(document,data_dir,roots,runtime_root,installation_id):
    """Owned worker entry: saved evidence and metadata only; no inference/fetch."""
    from .local_scene_library import SceneLibrary
    approvals = checked_profiles(roots,runtime_root,installation_id)
    library = SceneLibrary(Path(data_dir)/'personal-library',personal=True)
    with library._db() as db:
        known = [r[0] for r in db.execute('SELECT pano FROM locations')]
    result = create_queue(document,data_dir,approvals,known_panos=known)
    path = Path(result['metadataPath'])
    # Metadata is useful even when all locations were already reserved/indexed.
    from .local_scene_collection import LocalCollection
    LocalCollection(SceneLibrary(Path(data_dir)/'library'),library).add_map_metadata(result['queueId'],json.loads(path.read_text()))
    selected = result['path']
    if not selected and result['existingQueueId']:
        selected = str(Path(data_dir)/'personal-queues'/result['existingQueueId']/'campaign.json')
    if selected:
        result['archivePath'] = str(queue_zip(Path(selected).parent))
    return result


def create_queue(document,data_dir,approvals,*,fallback_country='',known_panos=()):
    rows,metadata,duplicates = map_rows(document,fallback_country)
    name = document.get('name','My MMA map') if isinstance(document,dict) else 'My MMA map'
    name = name if isinstance(name,str) and len(name)<=300 and all(ord(c)>=32 for c in name) else 'My MMA map'
    device = approvals[0]['installationId'] if approvals else None
    if not approvals or len(approvals)>3 or not any(a.get('inferenceThreads')==1 for a in approvals):
        raise ValueError('personal_computer_check_required')
    for value in approvals:
        validate_personal_approval(value,device,value['runtimeProfile'])
    source_sha = digest(rows)
    identity = digest([source_sha,metadata,name,approvals])
    data_dir = regular(data_dir,directory=True)
    destination = regular(data_dir/'personal-queues'/identity,directory=True,missing=True)
    registry = regular(data_dir/'personal-queue-registry.sqlite',missing=True)
    db = sqlite3.connect(registry,timeout=30)
    try:
        db.executescript('CREATE TABLE IF NOT EXISTS queues(id TEXT PRIMARY KEY,manifest TEXT,metadata TEXT,summary TEXT);'
            'CREATE TABLE IF NOT EXISTS packets(queue_id TEXT,ordinal INTEGER,body BLOB,PRIMARY KEY(queue_id,ordinal));'
            'CREATE TABLE IF NOT EXISTS reserved(pano TEXT PRIMARY KEY,queue_id TEXT NOT NULL);')
        db.execute('BEGIN IMMEDIATE')
        prior = db.execute('SELECT manifest,metadata,summary FROM queues WHERE id=?',(identity,)).fetchone()
        if prior:
            manifest,meta,summary = (json.loads(value) for value in prior)
        else:
            chosen,previous = [],None
            known = set(known_panos)
            for line in rows:
                pano = line.split('\t')[7]
                if pano in known:
                    continue
                inserted = db.execute('INSERT OR IGNORE INTO reserved VALUES(?,?)',(pano,identity)).rowcount
                if inserted:
                    chosen.append(line)
                elif previous is None:
                    previous = db.execute('SELECT queue_id FROM reserved WHERE pano=?',(pano,)).fetchone()[0]
            manifest = None
            if chosen:
                manifest = {'contract':PERSONAL_CONTRACT,'campaignId':'personal-'+identity[:32],
                    'participant':'personal','locations':len(chosen),'packets':[],'approvals':approvals,'personalSourceSha256':source_sha}
                for number,start in enumerate(range(0,len(chosen),PACKET_LOCATIONS)):
                    packet = {'contract':'vision-local-scene-packet-v1','participant':'personal','sourceSha256':source_sha,'lane':'scene',
                        'rows':[{'id':hashlib.sha256(line.encode()).hexdigest(),'sourceIndex':start+i,'line':line}
                                for i,line in enumerate(chosen[start:start+PACKET_LOCATIONS])]}
                    packet['packetId'] = digest(packet)
                    packet['payloadSha256'] = digest(packet)
                    validate_packet(packet)
                    body = canonical(packet)+b'\n'
                    filename = f'packets/{number:06d}.json'
                    db.execute('INSERT INTO packets VALUES(?,?,?)',(identity,number,body))
                    manifest['packets'].append({'path':filename,'sha256':hashlib.sha256(body).hexdigest(),
                        'packetId':packet['packetId'],'locations':len(packet['rows'])})
                manifest['sha256'] = digest(manifest)
                validate_manifest(manifest)
            meta = {'name':name,'rows':metadata,'sourceSha256':source_sha,
                    'scope':'LOCAL_PERSONAL_ONLY','communitySubmissionAllowed':False}
            summary = {'queueId':identity,'locations':len(chosen),'duplicatesSkipped':duplicates+len(rows)-len(chosen),
                'scope':'LOCAL_PERSONAL_ONLY','communitySubmissionAllowed':False,'name':name,'existingQueueId':previous}
            db.execute('INSERT INTO queues VALUES(?,?,?,?)',(identity,json.dumps(manifest),json.dumps(meta),json.dumps(summary)))
        # Commit all private reservations and exact packet bodies before delivery.
        # A failed ZIP/file write can be retried without assigning those IDs again.
        db.commit()
        destination.mkdir(mode=0o700,parents=True,exist_ok=True)
        immutable(destination/'personal-map.json',canonical(meta)+b'\n')
        if manifest:
            for number,body in db.execute('SELECT ordinal,body FROM packets WHERE queue_id=? ORDER BY ordinal',(identity,)):
                immutable(destination/manifest['packets'][number]['path'],body)
            immutable(destination/'campaign.json',canonical(manifest)+b'\n')
        return {**summary,'path':str(destination/'campaign.json') if manifest else None,
                'metadataPath':str(destination/'personal-map.json')}
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def queue_zip(folder):
    from .local_scene_campaign import load_manifest,campaign_packet
    folder = regular(folder,directory=True)
    manifest = load_manifest(folder/'campaign.json')
    if manifest['contract'] != PERSONAL_CONTRACT:
        raise ValueError('personal_queue_required')
    target = regular(folder/'personal-queue.zip',missing=True)
    if target.exists():
        with zipfile.ZipFile(target) as archive:
            paths = {'campaign.json':regular(folder/'campaign.json'),
                'personal-map.json':regular(folder/'personal-map.json')}
            paths.update((entry['path'],campaign_packet(folder,manifest,n)) for n,entry in enumerate(manifest['packets']))
            if (target.stat().st_size>64*1024**2 or len(archive.infolist()) != len(paths)
                    or set(archive.namelist()) != set(paths)
                    or any(archive.getinfo(name).file_size != path.stat().st_size
                        or archive.read(name) != path.read_bytes() for name,path in paths.items())):
                raise ValueError('personal_queue_archive_changed')
        return target
    pending = folder/('queue-'+secrets.token_hex(8)+'.pending')
    with zipfile.ZipFile(pending,'x',compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(regular(folder/'campaign.json'),'campaign.json')
        archive.write(regular(folder/'personal-map.json'),'personal-map.json')
        for number,entry in enumerate(manifest['packets']):
            archive.write(campaign_packet(folder,manifest,number),entry['path'])
    if pending.stat().st_size > 64*1024**2:
        raise ValueError('personal_queue_size_limit')
    pending.replace(target)
    return target
