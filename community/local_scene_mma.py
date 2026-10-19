"""Optional user-directed MMA export; memory-only key and no automatic retries."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import urllib.error
import urllib.request

from .local_scene_packets import canonical
from .mac_starter import regular
from .mma_cloud import CLOUD_URL, BATCH, EDIT_TYPE_IMPORT, cloud_locations, normalize_maps


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def request_mma(path, key, *, method='GET', body=None):
    if not re.fullmatch(r'/api/maps(?:/[A-Za-z0-9_-]{1,100}/locations)?', path):
        raise ValueError('invalid_mma_destination')
    request = urllib.request.Request(CLOUD_URL+path, data=None if body is None else canonical(body), method=method,
        headers={'accept':'application/json', 'content-type':'application/json', 'authorization':'API '+key})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=15) as response:
            raw = response.read(2*1024**2+1)
        if len(raw) > 2*1024**2:
            raise ValueError('mma_response_too_large')
        return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as error:
        raise ValueError('mma_unauthorized' if error.code in (401,403) else 'mma_request_failed') from None
    except (urllib.error.URLError, TimeoutError):
        raise ValueError('mma_unreachable') from None


class MMAConnection:
    def __init__(self, root, *, transport=request_mma):
        self.root = regular(root, directory=True)
        self.transport = transport
        self.key, self.maps = '', []
        self.guard = threading.RLock()

    def status(self):
        with self.guard:
            return {'connected':bool(self.key), 'maps':list(self.maps), 'keyStoredOnDisk':False}

    def connect(self, key):
        with self.guard:
            self.key, self.maps = '', []
            if (not isinstance(key, str) or not 1 <= len(key.strip()) <= 2048
                    or any(not 32 <= ord(c) < 127 for c in key)):
                raise ValueError('invalid_mma_key')
            key = key.strip()
            maps = normalize_maps(self.transport('/api/maps', key))
            if (len(maps) > 2048 or any(not re.fullmatch('[A-Za-z0-9_-]{1,100}', m['id'])
                    or len(m['name']) > 500 for m in maps)):
                raise ValueError('invalid_mma_maps')
            self.key, self.maps = key, maps
            return self.status()

    def disconnect(self):
        with self.guard:
            self.key, self.maps = '', []

    def send(self, map_id, document):
        with self.guard:
            if not self.key or map_id not in {m['id'] for m in self.maps}:
                raise ValueError('select_connected_mma_map')
            rows = cloud_locations(document)
            if not 1 <= len(rows) <= 200:
                raise ValueError('mma_result_limit')
            intent = hashlib.sha256(canonical([map_id, document])).hexdigest()
            path = regular(self.root/'mma-deliveries.sqlite', missing=True)
            with sqlite3.connect(path, timeout=10) as db:
                db.execute('CREATE TABLE IF NOT EXISTS deliveries(intent TEXT PRIMARY KEY,map_id TEXT NOT NULL,locations INTEGER NOT NULL,status TEXT NOT NULL)')
                prior = db.execute('SELECT status,locations FROM deliveries WHERE intent=?', (intent,)).fetchone()
                if prior:
                    if prior[0] == 'complete':
                        return {'added':0, 'alreadySent':True, 'locations':prior[1], 'url':CLOUD_URL+'/maps/'+map_id}
                    raise ValueError('mma_delivery_needs_check')
                db.execute('INSERT INTO deliveries VALUES(?,?,?,?)', (intent, map_id, len(rows), 'pending'))
                db.commit()  # Durable before the first write: never replay an ambiguous delivery.
                try:
                    for start in range(0, len(rows), BATCH):
                        self.transport('/api/maps/'+map_id+'/locations', self.key, method='POST', body={
                            'edits':[{'action':{'type':EDIT_TYPE_IMPORT},'create':rows[start:start+BATCH],'remove':[]}]})
                    db.execute('UPDATE deliveries SET status="complete" WHERE intent=?', (intent,))
                    db.commit()
                except Exception:
                    db.execute('UPDATE deliveries SET status="unknown" WHERE intent=?', (intent,))
                    db.commit()
                    raise ValueError('mma_delivery_needs_check') from None
            return {'added':len(rows), 'alreadySent':False, 'locations':len(rows), 'url':CLOUD_URL+'/maps/'+map_id}
