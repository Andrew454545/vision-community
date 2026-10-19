"""Deterministic, non-photographic RGB inputs for a future immutable PC check.

No imagery requests, location indexing, account operations or qualification.
The existing native sealed-input boundary checks the resulting inventory.
"""
import hashlib
import json
import math
from pathlib import Path
import re
import struct

VERSION = 1
DIMENSION = 224
RGB_BYTES = DIMENSION * DIMENSION * 3
MODELS = ('text_model.onnx', 'tokenizer.json', 'vision_model.onnx', 'vision_model_fp32.onnx')
DOMAIN = b'VISION synthetic PC readiness pixels v1\0'


def image_bytes(ordinal, view):
    if type(ordinal) is not int or not 0 <= ordinal < 112 or type(view) is not int or not 0 <= view < 4:
        raise ValueError('invalid_synthetic_canary_view')
    seed = hashlib.sha256(DOMAIN + ordinal.to_bytes(2, 'little') + bytes([view])).digest()
    family = (ordinal * 4 + view) % 8
    if family == 0:
        return hashlib.shake_256(DOMAIN + seed).digest(RGB_BYTES)
    if family == 1:
        return seed[:3] * (DIMENSION * DIMENSION)
    output = bytearray()
    palette = [seed[i:i+3] for i in range(0, 24, 3)]
    for y in range(DIMENSION):
        for x in range(DIMENSION):
            if family == 2:
                color = (x, y, (x + y) // 2)
            elif family == 3:
                color = palette[((x // 16) + (y // 16)) % 2]
            elif family == 4:
                color = palette[((x // 32) * 3 + (y // 32) * 5) % 8]
            elif family == 5:
                color = palette[(x >= 112) + 2 * (y >= 112)]
            elif family == 6:
                value = (x + y + seed[0]) % 256
                color = (value, value, value)
            else:
                color = ((x * 7 + seed[0]) % 256, (y * 11 + seed[1]) % 256, ((x ^ y) + seed[2]) % 256)
            output.extend(color)
    return bytes(output)


def create_sealed_inputs(root, fixture, model_files, *, expected_fixture_sha256):
    """Create a new native manifest, refusing changed source or invalid model pins.

    The expected source checksum and eventual manifest checksum must be pinned
    by the caller's trusted release. Self-generated pins are not approval.
    """
    if not isinstance(fixture, bytes) or hashlib.sha256(fixture).hexdigest() != expected_fixture_sha256:
        raise ValueError('synthetic_canary_fixture_pin_mismatch')
    rows = fixture.decode('utf-8').splitlines()
    parsed = [row.split('\t') for row in rows]
    if not 1 <= len(rows) <= 112 or any(len(row) != 11 for row in parsed) or len({r[7] for r in parsed}) != len(rows):
        raise ValueError('invalid_synthetic_canary_source')
    for row in parsed:
        try:
            numeric = [float(row[i]) for i in (2, 3, 4, 5, 6)]
        except (ValueError, OverflowError):
            raise ValueError('invalid_synthetic_canary_pose') from None
        if (not all(math.isfinite(v) for v in numeric) or not -90 <= numeric[0] <= 90
                or not -180 <= numeric[1] <= 180 or not re.fullmatch(r'[A-Za-z0-9_-]{22}', row[7])):
            raise ValueError('invalid_synthetic_canary_pose')
    if (not isinstance(model_files, list) or len(model_files) != 4
            or any(not isinstance(v, dict) or set(v) != {'name','bytes','sha256'}
                   or v['name'] not in MODELS or type(v['bytes']) is not int or v['bytes'] <= 0
                   or not isinstance(v['sha256'], str) or not re.fullmatch(r'[a-f0-9]{64}',v['sha256']) for v in model_files)
            or len({v['name'] for v in model_files}) != 4):
        raise ValueError('invalid_synthetic_canary_model_pins')
    ordered = {v['name']:dict(v) for v in model_files}
    manifest = {'schemaVersion':1,'status':'COMPLETE_RGB_BOUNDARY_ONLY','productionQualified':False,
        'boundary':'native-four-view-thumbnail-rgb224','totalLocations':len(rows),
        'sourceTsv':{'name':'locations.tsv','bytes':len(fixture),'sha256':expected_fixture_sha256},
        'modelFiles':[ordered[name] for name in MODELS],'frames':[]}
    root = Path(root)
    root.mkdir(exist_ok=False)
    bits = lambda value: struct.pack('>d',value).hex()
    for ordinal,row in enumerate(parsed):
        heading,pitch,zoom = (float(row[i]) for i in (4,5,6))
        for view in range(4):
            # Match Rust f64::rem_euclid, including negative zero's bit pattern.
            view_heading = math.fmod(heading + view * 90.0, 360.0)
            if view_heading < 0:
                view_heading += 360.0
            rgb = image_bytes(ordinal,view)
            name = f'scene-{ordinal:04}-view-{view}.rgb'
            (root/name).write_bytes(rgb)
            manifest['frames'].append({'ordinal':ordinal,'view':view,'panoId':row[7],
                'headingBits':bits(view_heading),'pitchBits':bits(pitch),'zoomBits':bits(zoom),
                'rgb':{'name':name,'bytes':len(rgb),'sha256':hashlib.sha256(rgb).hexdigest()}})
    raw = (json.dumps(manifest,indent=2,allow_nan=False)+'\n').encode('utf-8')
    (root/'manifest.json').write_bytes(raw)
    return {'version':VERSION,'locations':len(rows),'views':len(rows)*4,'photographicImagery':False,
            'liveImageryRetrieved':False,'manifestSha256':hashlib.sha256(raw).hexdigest(),
            'productionQualified':False}
