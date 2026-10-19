"""Choose Scene storage without moving, deleting, or duplicating existing work."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .local_scene_pilot import atomic_json, immutable
from .local_scene_readiness import installation_identity
from .mac_starter import regular
from .vision_index import assert_not_live_vision_path

CHOICE = 'local-scene-storage-choice.json'
HISTORY = 'local-scene-storage-history.json'
QUEUES = 'local-scene-queue-storage.json'
FOLDER = 'VISION Local Scenes Data'


def _document(path, limit=32*1024):
    path = regular(path)
    if path.stat().st_size > limit:
        raise ValueError('invalid_storage_choice')
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError('invalid_storage_choice')
    return value


def configure_storage(app_root, selected):
    app_root = regular(app_root, directory=True, missing=True)
    app_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    selected = regular(selected, directory=True)
    atomic_json(app_root/CHOICE, {'version':1, 'selected':str(selected)})


def resolve_storage(app_root, default_data):
    app_root = regular(app_root, directory=True)
    default_data = regular(default_data, directory=True, missing=True)
    choice = regular(app_root/CHOICE, missing=True)
    destination = default_data
    if choice.exists():
        value = _document(choice)
        if (set(value) != {'version','selected'} or value['version'] != 1
                or not isinstance(value['selected'], str) or not Path(value['selected']).is_absolute()):
            raise ValueError('invalid_storage_choice')
        parent = regular(Path(value['selected']), directory=True, missing=True)
        if not parent.exists():
            raise ValueError('storage_drive_unavailable')
        destination = parent if parent == default_data or parent.name == FOLDER else parent/FOLDER
    destination = regular(destination, directory=True, missing=True)
    assert_not_live_vision_path(destination)
    canonical_id = regular(app_root/'local-scene-installation-id.json', missing=True)
    installation = _document(canonical_id).get('id') if canonical_id.exists() else installation_identity(default_data)
    if not re.fullmatch('[a-f0-9]{64}', str(installation)):
        raise ValueError('invalid_storage_installation')
    encoded = json.dumps({'id':installation}, sort_keys=True, separators=(',',':')).encode()+b'\n'
    immutable(canonical_id, encoded)
    immutable(default_data/'installation-id.json', encoded)
    identity_path = regular(destination/'installation-id.json', missing=True)
    if identity_path.exists() and _document(identity_path) != {'id':installation}:
        raise ValueError('storage_belongs_to_another_installation')
    if destination.exists() and not identity_path.exists() and any(destination.iterdir()):
        raise ValueError('storage_folder_not_empty')
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    immutable(identity_path, encoded)
    history = regular(app_root/HISTORY, missing=True)
    roots = [str(default_data)]
    if history.exists():
        value = _document(history, 128*1024)
        if (set(value) != {'version','paths'} or value['version'] != 1
                or not isinstance(value['paths'], list) or len(value['paths']) > 32
                or any(not isinstance(p, str) or not Path(p).is_absolute() for p in value['paths'])):
            raise ValueError('invalid_storage_history')
        roots.extend(value['paths'])
    roots = list(dict.fromkeys([*roots, str(destination)]))
    if len(roots) > 32:
        raise ValueError('too_many_storage_locations')
    atomic_json(history, {'version':1, 'paths':roots})
    return destination, [Path(p) for p in roots]


def queue_storage(app_root, selected, roots, campaign_sha):
    """A changed preference cannot create a fresh copy of an existing queue."""
    if not isinstance(campaign_sha, str) or not re.fullmatch('[a-f0-9]{64}', campaign_sha):
        raise ValueError('invalid_storage_queue')
    path = regular(Path(app_root)/QUEUES, missing=True)
    value = _document(path, 2*1024*1024) if path.exists() else {'version':1, 'queues':{}}
    if (set(value) != {'version','queues'} or value['version'] != 1
            or not isinstance(value['queues'], dict) or len(value['queues']) > 256
            or any(not re.fullmatch('[a-f0-9]{64}', k) or not isinstance(v,str) or not Path(v).is_absolute()
                   for k,v in value['queues'].items())):
        raise ValueError('invalid_queue_storage_history')
    if campaign_sha in value['queues']:
        destination = regular(Path(value['queues'][campaign_sha]), directory=True, missing=True)
        if not regular(destination/campaign_sha/'campaign.json', missing=True).exists():
            raise ValueError('saved_queue_storage_missing')
        return destination
    matches = [regular(p, directory=True) for p in roots if
               regular(Path(p)/campaign_sha/'campaign.json', missing=True).exists()]
    if len(set(matches)) > 1:
        raise ValueError('multiple_saved_queue_copies')
    destination = matches[0] if matches else selected
    if len(value['queues']) >= 256:
        raise ValueError('too_many_saved_queues')
    value['queues'][campaign_sha] = str(destination)
    atomic_json(path, value)
    return destination
