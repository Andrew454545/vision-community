"""Private photo query vectors using the pinned encoder, with no network path.

The existing sealed-RGB command is used only as a bounded image encoder. Its
temporary single-record index is never contributed, qualified, or added to a
library. Full-precision query vectors enter an isolated native query cache;
completed location indexes and their numerical pipeline remain unchanged.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import struct

from .local_scene_library import fnv_update, model_identity
from .local_scene_packets import canonical
from .local_scene_pilot import atomic_json, immutable
from .mac_starter import regular
from .process_owner import run_owned
from .vision_index import four_view_input, inference_environment, file_identity

RGB_BYTES = 224*224*3
MODEL_NAMES = ('text_model.onnx','tokenizer.json','vision_model.onnx','vision_model_fp32.onnx')


def f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


def normalize(vector):
    total = 0.0
    for value in vector:
        total = f32(total+f32(value*value))
    norm = f32(math.sqrt(total))
    if not math.isfinite(norm) or norm <= 0:
        raise ValueError('invalid_photo_vector')
    return [f32(value/norm) for value in vector]


def mix(image, text, weight):
    if weight not in (0,25,50,75):
        raise ValueError('invalid_photo_weight')
    positive = normalize(image)
    if not weight:
        return positive
    w = weight/100
    return normalize([f32(f32(a*(1-w))+f32(b*w)) for a,b in zip(positive,text)])


def profile_fingerprint(request):
    """Native query-profile identity, restricted to a single offline query."""
    if len(request['queries']) != 1:
        raise ValueError('invalid_photo_query')
    query = request['queries'][0]
    if query.get('examples'):
        raise ValueError('photo_query_must_be_offline')
    value = 0xcbf29ce484222325
    def piece(body):
        nonlocal value
        value = fnv_update(value, body+b'\xff')
    if request.get('sceneFp32'):
        piece(b'scene-fp32-image-graph-v1')
    for key in ('name','query','mode'):
        piece(query[key].encode())
    for generation in query.get('cameraGenerations',[]):
        piece(generation.encode())
    for key,marker in (('includeCountries',b'include-country'),('excludeCountries',b'exclude-country')):
        for country in query.get(key,[]):
            piece(marker);piece(country.encode())
    piece(bytes([bool(query.get('rejectRoadNames',False))]))
    for offset in query.get('viewOffsets',[]):
        piece(b'view-offset');piece(bytes([offset]))
    return f'{value:016x}'


def prepare_profile(rgb, job, binary, models, runtime_profile, request, *, weight=0, runner=None):
    if not isinstance(rgb,bytes) or len(rgb) != RGB_BYTES:
        raise ValueError('invalid_photo_pixels')
    if weight not in (0,25,50,75) or request['queries'][0].get('examples'):
        raise ValueError('photo_query_must_be_offline')
    job = regular(job, directory=True)
    root = job/'photo-encoder'
    root.mkdir(mode=0o700)
    frozen = root/'pixels'
    frozen.mkdir(mode=0o700)
    pano = 'p'*22
    source = root/'locations.tsv'
    immutable(source, f'photo\t0\t0\t0\t0\t0\t0\t{pano}\tFrance\tunknown\tfalse\n'.encode())
    models = regular(models, directory=True)
    pins = [{'name':name,'bytes':regular(models/name).stat().st_size,
             'sha256':runtime_profile['profile']['assets']['models/'+name]} for name in MODEL_NAMES]
    frames = []
    for view in range(4):
        name = f'scene-0000-view-{view}.rgb'
        immutable(frozen/name, rgb)
        frames.append({'ordinal':0,'view':view,'panoId':pano,
            'headingBits':struct.pack('>d',view*90.0).hex(),'pitchBits':'0000000000000000',
            'zoomBits':'0000000000000000','rgb':{'name':name,'bytes':RGB_BYTES,'sha256':hashlib.sha256(rgb).hexdigest()}})
    manifest = {'schemaVersion':1,'status':'COMPLETE_RGB_BOUNDARY_ONLY','productionQualified':False,
        'boundary':'native-four-view-thumbnail-rgb224','totalLocations':1,
        'sourceTsv':{'name':'locations.tsv',**file_identity(source)},'modelFiles':pins,'frames':frames}
    atomic_json(frozen/'manifest.json', manifest)
    spec = four_view_input(total=1,pace='slow',run_id='local-photo-query')
    spec['queries'] = [{'name':'Photo query text','query':request['queries'][0]['query'],
                       'mode':'textOnly','minSimilarity':-1.0,'examples':[]}]
    atomic_json(root/'input.json', spec)
    command = [str(binary),'study-four-views','--input',str(root/'input.json'),
        '--model-dir',str(models),'--locations-tsv',str(source),'--index-dir',str(root/'index'),
        '--checkpoint',str(root/'checkpoint.json'),'--output',str(root/'output.json'),
        '--sealed-rgb',str(frozen),'--sealed-sha256',file_identity(frozen/'manifest.json')['sha256'],
        '--evidence-dir',str(root/'evidence'),'--evidence-budget-mib','16','--scene-fp32']
    if runner:
        runner(command,root)
    else:
        with (root/'stdout.log').open('xb') as out,(root/'stderr.log').open('xb') as err:
            result = run_owned(command,env=inference_environment(root),cwd=root,stdout=out,stderr=err,timeout=180)
        if result.returncode:
            raise ValueError('photo_encoding_failed')
    evidence = json.loads(regular(root/'evidence/scene-evidence.json').read_text())
    if (evidence.get('status') != 'NATIVE_SCENE_STUDY_COMPLETED_UNQUALIFIED'
            or evidence.get('productionQualified') is not False
            or evidence.get('selectedImageGraph') != 'vision_model_fp32.onnx'
            or evidence.get('modelFiles') != pins or len(evidence.get('frames',[])) != 4):
        raise ValueError('photo_encoding_incomplete')
    record = next((r for r in evidence.get('tensors',[]) if r.get('event')=='normalized'
                   and r.get('ordinal')==0 and r.get('view')==0),None)
    name = 'scene-0000-view-0-normalized.f32le'
    if not record or record.get('shape') != [768] or record.get('file',{}).get('name') != name:
        raise ValueError('photo_encoding_incomplete')
    path = regular(root/'evidence'/name)
    if file_identity(path) != {k:record['file'][k] for k in ('bytes','sha256')} or path.stat().st_size != 768*4:
        raise ValueError('photo_encoding_changed')
    image = list(struct.unpack('<768f',path.read_bytes()))
    if any(not math.isfinite(v) for v in image) or abs(sum(v*v for v in image)-1) > .01:
        raise ValueError('invalid_photo_vector')
    text_profiles = json.loads(regular(root/'index/query-profiles.json').read_text())['profiles']
    if len(text_profiles) != 1:
        raise ValueError('photo_encoding_incomplete')
    text = text_profiles[0]['vector']
    if len(text) != 768 or any(type(v) not in (int,float) or not math.isfinite(v) for v in text):
        raise ValueError('invalid_photo_vector')
    query = request['queries'][0]
    profile = {'name':query['name'],'query':query['query'],'mode':query['mode'],
        'definitionFingerprint':profile_fingerprint(request),'vector':mix(image,text,weight),'excludedPanoIds':[]}
    destination = job/'profiles'
    destination.mkdir(mode=0o700,exist_ok=True)
    atomic_json(destination/'query-profiles.json',{'version':4,'runId':request['runId'],
        'modelIdentity':model_identity(models),'profiles':[profile]})
    return {'queryOnly':True,'imageSha256':hashlib.sha256(rgb).hexdigest(),
        'liveImageryRequests':0,'descriptionWeight':weight,'profileSha256':file_identity(destination/'query-profiles.json')['sha256']}
