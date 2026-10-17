"""Owner: import private Scene exports against the retained assignment authority.

This checks qualified-device provenance, hashes, exact assigned metadata, full
views and duplicates. It does not independently recompute contributed vectors or
alter the owner's existing VISION indexes. No network or native inference.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import sqlite3
import stat
import zipfile

from .local_scene_archive import ARTIFACTS, MAX_SOURCE_BYTES
from .local_scene_campaign import validate_manifest
from .local_scene_library import SceneLibrary
from .local_scene_packets import canonical, validate_packet, digest
from .local_scene_pilot import immutable
from .local_scene_qualification import validate_approval
from .mac_starter import regular


def read_archive(path):
    path = regular(path)
    if path.stat().st_size > MAX_SOURCE_BYTES+1024*1024:
        raise ValueError('scene_import_archive_too_large')
    raw = path.read_bytes()
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        names = [e.filename for e in entries]
        if (not 3<=len(entries)<=600 or len(names)!=len(set(names))
                or 'export-manifest.json' not in names
                or sum(e.file_size for e in entries)>MAX_SOURCE_BYTES+1024*1024
                or any(e.file_size>2*1024*1024 or e.flag_bits&1
                    or e.compress_type not in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED)
                    or stat.S_IFMT(e.external_attr>>16) not in (0,stat.S_IFREG) for e in entries)):
            raise ValueError('invalid_scene_import_archive')
        manifest = json.loads(archive.read('export-manifest.json'))
        if (manifest.get('contract') not in ('vision-local-scene-archive-v1','vision-local-scene-archive-v2')
                or manifest.get('qualityStatus')!='LOCAL_PROVISIONAL' or manifest.get('uploaded') is not False
                or manifest.get('creditsEarned')!=0 or not isinstance(manifest.get('files'),dict)
                or set(manifest['files'])|{'export-manifest.json'}!=set(names)):
            raise ValueError('invalid_scene_import_manifest')
        captured = {}
        for name,pin in manifest['files'].items():
            allowed = name in ('packet.json','runtime-profile.json','work-layout.json')
            match = re.fullmatch(r'part-([0-9]{4})/(complete\.json|attempt-[0-9]{4,10}/(.+))',name)
            if match and (match[2]=='complete.json' or match[3] in ARTIFACTS):
                allowed = True
            if not allowed:
                raise ValueError('invalid_scene_import_member')
            body = archive.read(name)
            if pin!={'bytes':len(body),'sha256':hashlib.sha256(body).hexdigest()}:
                raise ValueError('scene_import_hash_mismatch')
            captured[name] = body
        if not {'packet.json','runtime-profile.json'}<=set(captured):
            raise ValueError('scene_import_packet_missing')
        return raw,manifest,captured


class ImportAuthority:
    def __init__(self, registry, campaign_id):
        self.registry = regular(registry)
        self.campaign_id = campaign_id
        with self._db() as db:
            row = db.execute('SELECT body FROM campaigns WHERE id=?',(campaign_id,)).fetchone()
        if not row:
            raise ValueError('scene_import_assignment_missing')
        self.campaign = validate_manifest(json.loads(row[0]))
        self.packets = {entry['packetId']:(i,entry) for i,entry in enumerate(self.campaign['packets'])}
        self.profiles = {}
        for approval in self.campaign['approvals']:
            profile = approval['runtimeProfile']
            validate_approval(approval,approval['installationId'],profile)
            self.profiles[profile['sha256']] = profile

    def _db(self):
        return sqlite3.connect(self.registry.as_uri()+'?mode=ro',uri=True)

    def import_archive(self, archive_path, library):
        raw,manifest,files = read_archive(archive_path)
        packet = validate_packet(json.loads(files['packet.json']))
        profile = json.loads(files['runtime-profile.json'])
        if (packet['packetId']!=manifest.get('packetId') or packet['payloadSha256']!=manifest.get('packetSha256')
                or profile!=self.profiles.get(profile.get('sha256'))
                or profile['sha256']!=manifest.get('runtimeProfileSha256')
                or packet['packetId'] not in self.packets):
            raise ValueError('scene_import_unapproved_packet_or_runtime')
        ordinal,entry = self.packets[packet['packetId']]
        allocation = f'{self.campaign_id}:{ordinal}'
        with self._db() as db:
            original = db.execute('SELECT body FROM packets WHERE allocation=?',(allocation,)).fetchone()
            if (not original or json.loads(original[0])!=packet
                    or hashlib.sha256(canonical(packet)+b'\n').hexdigest()!=entry['sha256']
                    or any(db.execute('SELECT allocation FROM assigned WHERE pano=?',(r['line'].split('\t')[7],)).fetchone()!=(allocation,)
                           for r in packet['rows'])):
                raise ValueError('scene_import_assignment_changed')
        # Named bounded files only. No extractall, links, arbitrary paths or native
        # executable from the contributor. Completion validation precedes DB import.
        key = hashlib.sha256(raw).hexdigest()
        root = regular(library.root/'imports'/key,directory=True,missing=True)
        for name,body in files.items():
            immutable(root/name,body)
        from .local_scene_archive import _completed_parts
        parts = _completed_parts(root,packet)
        if (not parts or sum(len(rows) for _,rows in parts)!=manifest.get('locations')
                or [name for name,_ in parts]!=manifest.get('parts')
                or manifest.get('total')!=len(packet['rows'])
                or manifest.get('complete')!=(manifest['locations']==len(packet['rows']))):
            raise ValueError('scene_import_completion_changed')
        added = library.add_pilot(root)
        report = {'contract':'vision-local-scene-import-v1','archiveSha256':key,
            'campaignId':self.campaign_id,'packetId':packet['packetId'],
            'runtimeProfileSha256':profile['sha256'],
            'locations':manifest['locations'],'scope':'QUALIFIED_DEVICE_OUTPUT_NOT_RECOMPUTED',
            'existingOwnerIndexesChanged':False,'cloudCalls':0}
        immutable(root/'import-receipt.json',canonical(report)+b'\n')
        return {**report,'added':added}

    def import_collection(self, path, library):
        path = regular(path)
        if path.stat().st_size>16*1024*1024:
            raise ValueError('scene_import_collection_too_large')
        document = json.loads(path.read_text())
        if (document.get('contract')!='vision-local-scene-collection-v1'
                or document.get('campaignSha256')!=self.campaign['sha256']
                or document.get('uploaded') is not False or document.get('qualityStatus')!='LOCAL_PROVISIONAL'
                or not isinstance(document.get('archives'),list)
                or not 1<=len(document['archives'])<=len(self.campaign['packets'])
                or path.name!='collection-'+digest(document)+'.json'):
            raise ValueError('invalid_scene_import_collection')
        added,locations,seen = 0,0,set()
        for item in document['archives']:
            if (not isinstance(item,dict) or set(item)!={'path','packetId','runtimeProfileSha256','locations','sha256','bytes'}
                    or not re.fullmatch(r'[0-9]{6}\.zip',str(item.get('path')))
                    or item['packetId'] in seen or item['packetId'] not in self.packets):
                raise ValueError('invalid_scene_import_collection_member')
            ordinal,entry = self.packets[item['packetId']]
            if (item['path']!=f'{ordinal:06d}.zip' or item['locations']!=entry['locations']
                    or item['runtimeProfileSha256'] not in self.profiles):
                raise ValueError('invalid_scene_import_collection_member')
            archive = regular(path.parent/item['path'])
            from .vision_index import file_identity
            if file_identity(archive)!={'bytes':item['bytes'],'sha256':item['sha256']}:
                raise ValueError('scene_import_collection_hash_mismatch')
            result = self.import_archive(archive,library)
            if (result['packetId']!=item['packetId'] or result['locations']!=item['locations']
                    or result['runtimeProfileSha256']!=item['runtimeProfileSha256']):
                raise ValueError('scene_import_collection_member_changed')
            seen.add(item['packetId']);added+=result['added'];locations+=result['locations']
        if (locations!=document.get('locations') or document.get('total')!=self.campaign['locations']
                or document.get('complete')!=(locations==self.campaign['locations'])):
            raise ValueError('scene_import_collection_completion_changed')
        return {'added':added,'locations':locations,'archives':len(seen),'cloudCalls':0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--archive',type=Path)
    group.add_argument('--collection',type=Path)
    parser.add_argument('--registry',type=Path,required=True)
    parser.add_argument('--campaign',required=True)
    parser.add_argument('--library',type=Path,required=True)
    args = parser.parse_args()
    authority = ImportAuthority(args.registry,args.campaign)
    library = SceneLibrary(args.library)
    result = authority.import_archive(args.archive,library) if args.archive else authority.import_collection(args.collection,library)
    print(json.dumps(result))


if __name__=='__main__':
    main()
