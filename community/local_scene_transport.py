"""Conservative live downloads; numerical input/batch settings stay unchanged."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .local_scene_packets import canonical
from .mac_starter import regular

GROUP_PAUSE_SECONDS = 30
CONTRACT = 'vision-local-scene-network-execution-v1'


def planned_input(path):
    path = regular(path)
    if path.stat().st_size > 32*1024:
        raise ValueError('network_input_too_large')
    raw = path.read_bytes()
    document = json.loads(raw)
    if not isinstance(document,dict) or type(document.get('concurrency')) is not int or document['concurrency'] < 1:
        raise ValueError('invalid_network_input')
    return raw, document


def execution(path):
    raw, document = planned_input(path)
    actual = {**document,'concurrency':1}
    body = canonical(actual)+b'\n'
    return body, {'contract':CONTRACT,'plannedInputSha256':hashlib.sha256(raw).hexdigest(),
        'nativeInput':actual,'nativeInputSha256':hashlib.sha256(body).hexdigest(),
        'maximumConcurrentDownloads':1,'minimumSavedGroupPauseSeconds':GROUP_PAUSE_SECONDS}


def validate_execution(value, path):
    _, expected = execution(path)
    if canonical(value) != canonical(expected):
        raise ValueError('saved_network_execution_changed')


def prepare_command(argv):
    """Only the ordinary live index command is affected; frozen studies are not."""
    if 'index-four-views' not in argv:
        return list(argv), None
    position = argv.index('--input')+1
    source = Path(argv[position])
    body, record = execution(source)
    from .local_scene_pilot import immutable
    target = source.with_name('native-network-input.json')
    immutable(target, body)
    command = list(argv)
    command[position] = str(target)
    return command, record
