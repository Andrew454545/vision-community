"""Search separate contributed/personal libraries without mixing their authority."""
from __future__ import annotations

import json
import re

from .rank import prune_nearby
from .vision_index import finish_scene_coordinates


class LocalCollection:
    def __init__(self,community,personal):
        self.sources = [('community',community),('personal',personal)]
        self.personal = personal
        with personal._db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS personal_maps(map_id TEXT,pano TEXT,name TEXT,tags TEXT,PRIMARY KEY(map_id,pano))')
            db.execute('CREATE INDEX IF NOT EXISTS personal_maps_pano ON personal_maps(pano)')

    def status(self):
        values = [(kind,library.status()) for kind,library in self.sources]
        return {'locations':sum(s['locations'] for _,s in values),
            'countries':sorted({x for _,s in values for x in s['countries']}),
            'generations':sorted({x for _,s in values for x in s['generations'] if x in ('gen1','gen2','gen3','gen4','badcam')}),
            'sourceCounts':{kind:s['locations'] for kind,s in values},
            'path':str(self.sources[0][1].root.parent),'localOnly':True}

    def add_map_metadata(self,map_id,value):
        if (not re.fullmatch('[a-f0-9]{64}',map_id) or not isinstance(value,dict)
                or value.get('scope') != 'LOCAL_PERSONAL_ONLY' or value.get('communitySubmissionAllowed') is not False):
            raise ValueError('personal_map_metadata_required')
        rows = value.get('rows',[])
        if not isinstance(rows,list) or len(rows)>100_000:
            raise ValueError('personal_map_size_limit')
        name = value.get('name')
        if not isinstance(name,str) or len(name)>300 or any(ord(c)<32 for c in name):
            raise ValueError('personal_map_metadata_required')
        for row in rows:
            if (not isinstance(row,dict) or not isinstance(row.get('panoId'),str)
                    or not re.fullmatch('[A-Za-z0-9_-]{4,80}',row['panoId'])
                    or not isinstance(row.get('tags'),list) or len(row['tags'])>128
                    or any(not isinstance(t,str) or not 0<len(t)<=200 or any(ord(c)<32 for c in t) for t in row['tags'])):
                raise ValueError('personal_map_metadata_required')
        with self.personal._db() as db:
            db.executemany('INSERT OR IGNORE INTO personal_maps VALUES(?,?,?,?)',
                [(map_id,r['panoId'],value['name'],json.dumps(r['tags'])) for r in rows])

    def search(self,value,runtime_root,**kwargs):
        value = dict(value)
        scope = value.pop('libraryScope','all')
        if scope not in ('all','community','personal'):
            raise ValueError('invalid_library_scope')
        count = value.get('resultCount',50)
        if type(count) is not int or not 1<=count<=200:
            raise ValueError('invalid_library_result_count')
        rows, total, indexes, offset = [],0,0,0
        for kind,library in self.sources:
            if scope not in ('all',kind):
                continue
            info = library.status()
            total += info['locations']
            if not info['locations']:
                continue
            if ((value.get('country') and value['country'] not in info['countries'])
                    or (value.get('generation') and value['generation'] not in info['generations'])):
                offset += info['locations']
                continue
            result = library.search({**value,'resultCount':min(200,count*4)},runtime_root,**kwargs)
            indexes += result['indexes']
            for row in (result.get('map') or {}).get('customCoordinates',[]):
                row['extra']['visionSourceIndex'] += offset
                row['extra']['visionLocalLibrary'] = kind
                rows.append(row)
            offset += info['locations']
        if not total:
            raise ValueError('library_empty')
        rows.sort(key=lambda r:(-r['extra']['visionScore'],r['extra']['visionSourceIndex']))
        seen,unique = set(),[]
        with self.personal._db() as db:
            for row in rows:
                if row['panoId'] in seen:
                    continue
                seen.add(row['panoId'])
                metadata = db.execute('SELECT name,tags FROM personal_maps WHERE pano=? LIMIT 20',(row['panoId'],)).fetchall()
                if metadata:
                    tags = row['extra'].get('tags',[])
                    row['extra']['tags'] = list(dict.fromkeys([*tags,*(t for _,raw in metadata for t in json.loads(raw))]))
                    row['extra']['visionPersonalMaps'] = list(dict.fromkeys(name for name,_ in metadata))
                unique.append(row)
        document = finish_scene_coordinates(prune_nearby(unique),result_count=count,max_per_country=count,
            output_name='My VISION results',prompt=value.get('prompt',''),processed_locations=total)
        return {'ok':True,'locations':total,'indexes':indexes,'map':document,'localOnly':True,'uploads':0,
            'liveExampleImagery':bool(value.get('examples')),'localPhotoQuery':kwargs.get('photo_rgb') is not None}
