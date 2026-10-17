"""Local library controls shared by the processing window and its HTTP API."""
from __future__ import annotations

import json
from pathlib import Path
import re
import sqlite3
import threading

from .local_scene_library import SceneLibrary
from .local_scene_pilot import atomic_json
from .mac_starter import regular


class LibraryWindow:
    def __init__(self,data_dir,runtime_root):
        from .local_scene_packets import digest
        self.root = regular(Path(data_dir)/'library',directory=True,missing=True)
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.runtime_root = Path(runtime_root)
        self.thread = None
        self.packet = {'packetId':digest(['local-library',str(self.root)])}

    def status(self):
        return {'phase':'ready','participant':'My library','completed':0,'total':0,
            'packetId':self.packet['packetId'],'outputDirectory':str(self.root),
            'message':'Open your personal queue from the launcher to process more Scenes.',
            'exportAvailable':False,'libraryOnly':True,'localOnly':True}

    def start(self):
        raise ValueError('open_personal_queue_to_process')

    def pause(self):
        pass

    def close(self):
        pass


class LibrarySession:
    def __init__(self, app, data_dir, *, searcher=None, source_roots=None):
        self.app = app
        self.data_dir = regular(data_dir, directory=True)
        self.source_roots = list(dict.fromkeys([self.data_dir, *(source_roots or [])]))
        self.library = SceneLibrary(self.data_dir/'library')
        self.personal_library = SceneLibrary(self.data_dir/'personal-library',personal=True)
        from .local_scene_collection import LocalCollection
        self.collection = LocalCollection(self.library,self.personal_library)
        self.searcher = searcher or self.collection.search
        self.guard = threading.RLock()
        self.thread = None
        self.stop = threading.Event()
        self.phase, self.message = 'ready', 'Your completed Scenes appear here. Refresh to recover saved work.'
        self.result = None
        self.mma = None
        self.photo_rgb = None
        self.personal_queue = None
        self._personal_metadata = set()
        self.countries = regular(Path(__file__).with_name('country-names.txt')).read_text().splitlines()
        # The callback adds only metadata/references. Vector compaction waits
        # until a search, so every128-location batch does not rewrite a segment.
        app.on_completed_pilot = self.add_completed

    def add_completed(self, root):
        try:
            target = self.library
            for parent in Path(root).parents[:4]:
                if (parent/'campaign.json').exists():
                    from .local_scene_campaign import load_manifest,PERSONAL_CONTRACT
                    manifest = load_manifest(parent/'campaign.json')
                    if manifest['contract'] == PERSONAL_CONTRACT:
                        target = self.personal_library
                        self._add_personal_metadata(parent,manifest['sha256'])
                    break
            target.add_pilot(root)
        except Exception as error:
            atomic_json(self.library.root/'failure.json', {'errorClass':type(error).__name__,
                'code':'library_refresh_needed','originalWorkPreserved':True})

    def _add_personal_metadata(self,root,map_id):
        if map_id in self._personal_metadata:
            return
        path = regular(root/'personal-map.json')
        if path.stat().st_size > 64*1024**2:
            raise ValueError('personal_map_size_limit')
        self.collection.add_map_metadata(map_id,json.loads(path.read_text()))
        self._personal_metadata.add(map_id)

    def _recover(self):
        from .local_scene_recover import recover
        recover(self.data_dir,self.source_roots,self.library,stop=self.stop)

    def _recover_inline(self, *, heartbeat=lambda:None):
        heartbeat()
        with self.library.guard, self.library._db() as db:
            known = {Path(row[0]).parents[1] for row in db.execute('SELECT path FROM sources')}
        with self.personal_library._db() as db:
            known.update(Path(row[0]).parents[1] for row in db.execute('SELECT path FROM sources'))
        for data_dir in self.source_roots:
            data_dir = regular(data_dir, directory=True, missing=True)
            if data_dir.exists():
                heartbeat()
                self._recover_root(data_dir, known, heartbeat=heartbeat)

    def _recover_root(self, data_dir, known, *, heartbeat=lambda:None):
        for root in sorted(data_dir.iterdir()):
            heartbeat()
            if self.stop.is_set():
                return
            if not re.fullmatch('[a-f0-9]{64}', root.name):
                continue
            regular(root, directory=True)
            if (root/'campaign.json').exists():
                from .local_scene_campaign import load_manifest, campaign_packet
                manifest = load_manifest(root/'campaign.json')
                from .local_scene_campaign import PERSONAL_CONTRACT
                target = self.library
                if manifest['contract'] == PERSONAL_CONTRACT:
                    target = self.personal_library
                    self._add_personal_metadata(root,manifest['sha256'])
                progress = regular(root/'progress.sqlite', missing=True)
                if not progress.exists():
                    continue
                with sqlite3.connect(progress.as_uri()+'?mode=ro',uri=True) as db:
                    completed = db.execute('SELECT ordinal,profile FROM work WHERE status="complete" ORDER BY ordinal').fetchall()
                for ordinal, profile in completed:
                    heartbeat()
                    if self.stop.is_set():
                        return
                    if not re.fullmatch('[a-f0-9]{64}',str(profile)) or not 0<=ordinal<len(manifest['packets']):
                        raise ValueError('library_progress_changed')
                    pilot = root/'work'/profile/manifest['packets'][ordinal]['packetId']
                    if pilot not in known:
                        campaign_packet(root,manifest,ordinal)
                        target.add_pilot(pilot)
            elif (root/'packet.json').exists() and (root/'runtime-profile.json').exists():
                self.library.add_pilot(root)

    def status(self):
        with self.guard:
            return {**self.collection.status(),'phase':self.phase,'message':self.message,
                'busy':bool(self.thread and self.thread.is_alive()),
                'results':(self.result.get('map') or {}).get('customCoordinates',[]) if self.result else [],
                'mapAvailable':bool(self.result and self.result.get('map')),
                'personalQueueAvailable':bool(self.personal_queue),
                'personalQueueLocations':(self.personal_queue or {}).get('locations',0)}

    def prepare_personal(self,document,country=''):
        from .local_scene_personal import sanitized_map
        with self.guard:
            if self.thread and self.thread.is_alive():
                raise ValueError('library_busy')
            if self.app.thread and self.app.thread.is_alive():
                raise ValueError('pause_processing_before_search')
            cleaned,duplicates = sanitized_map(document,country)
            self.stop.clear()
            self.personal_queue = None
            self.phase,self.message = 'preparing','Checking saved compatibility results and preparing your private queue…'
            self.thread = threading.Thread(target=self._prepare_personal,args=(cleaned,duplicates),
                name='personal-map-prepare',daemon=False)
            self.thread.start()

    def _prepare_personal(self,document,duplicates):
        from .local_scene_recover import metadata_task
        from .local_scene_readiness import installation_identity
        try:
            result = metadata_task(self.data_dir,self.source_roots,self.library,stop=self.stop,
                personal={'document':document,'runtimeRoot':str(self.app.runtime_root),
                    'installationId':installation_identity(self.data_dir)})
            with self.guard:
                self.personal_queue = result if result.get('archivePath') else None
                self.phase = 'ready'
                if result['locations']:
                    self.message = (f'{result["locations"]:,} Scenes ready; {result["duplicatesSkipped"]+duplicates:,} duplicates skipped. '
                        'Save your personal queue, extract the ZIP, then open campaign.json from the launcher.')
                elif self.personal_queue:
                    self.message = 'These Scenes already have a private queue. Save it to resume the existing work.'
                else:
                    self.message = 'These Scenes are already in your library. Their map names and tags are now saved too.'
        except Exception as error:
            code = str(error)
            with self.guard:
                self.phase = 'error'
                self.message = {
                    'personal_computer_check_required':'Open Check this computer from the current kit and finish or resume its saved check, then import your map again.',
                    'personal_computer_check_failed':'This computer’s saved results did not match the fixed reference. Keep the reports for the maintainer.',
                    'library_recovery_stalled':'Preparing the queue took too long. Your private reservations are kept. Make files available locally and import the same map again.',
                    'library_search_cancelled':'Queue preparation stopped. Saved work and reservations are kept.'}.get(code,
                    'The private queue could not be prepared. Your saved indexes are kept. Import the same map to resume.')
            atomic_json(self.library.root/'personal-failure.json',{'errorClass':type(error).__name__,
                'code':code if re.fullmatch('[a-z_]{1,70}',code) else 'personal_queue_failed','originalWorkPreserved':True})

    def begin(self, query=None):
        with self.guard:
            if self.thread and self.thread.is_alive():
                raise ValueError('library_busy')
            if query is not None and self.app.thread and self.app.thread.is_alive():
                raise ValueError('pause_processing_before_search')
            photo = None
            if query is not None:
                query = dict(query)
                use_photo = query.pop('usePhoto',False)
                if type(use_photo) is not bool or (use_photo and self.photo_rgb is None):
                    raise ValueError('library_photo_missing')
                photo = self.photo_rgb if use_photo else None
            self.phase = 'refreshing' if query is None else 'searching'
            self.message = ('Finding your completed Scenes…' if query is None else
                'Searching your saved Scenes on this computer. Your queue stays paused.')
            self.result = None
            self.stop.clear()
            self.thread = threading.Thread(target=self._run,args=(query,photo),name='local-scene-library',daemon=False)
            self.thread.start()

    def _run(self, query, photo=None):
        try:
            # Existing libraries search immediately; explicit Refresh recovers
            # old work. Do not rescan tens of thousands of packets per query.
            if query is None or self.collection.status()['locations'] == 0:
                self._recover()
            if query is not None and not self.stop.is_set():
                kwargs = {'stop':self.stop}
                if photo is not None:
                    kwargs['photo_rgb'] = photo
                result = self.searcher(query,self.app.runtime_root,**kwargs)
                with self.guard:
                    self.result = result
                    self.phase = 'complete'
                    count = len((result.get('map') or {}).get('customCoordinates',[]))
                    self.message = f'{count} results from {result["locations"]:,} saved Scenes.'
            elif not self.stop.is_set():
                with self.guard:
                    self.phase, self.message = 'ready', 'Library updated. Pause processing before searching.'
        except Exception as error:
            code = str(error) if isinstance(error,ValueError) and re.fullmatch('[a-z_]{1,70}',str(error)) else 'library_action_failed'
            with self.guard:
                self.phase = 'error'
                self.message = ({'library_empty':'No completed Scenes yet. Process your personal queue first.',
                    'imagery_access_denied':'Google refused the reference imagery. Use text search or wait for normal imagery access.',
                    'library_storage_required':'Free some storage space before preparing the searchable library.',
                    'photo_encoding_failed':'The local photo could not be encoded. Your saved library is unchanged.',
                    'photo_profile_not_used':'The runtime could not use this local photo. Your saved indexes are unchanged.',
                    'library_recovery_stalled':'A saved file is taking too long to read. Your work is kept. Connect the disk and make cloud-stored files available locally, then Refresh.',
                    'library_recovery_failed':'Saved-work recovery stopped. Your original files are kept; check the local report before refreshing.',
                    'library_search_cancelled':'Search stopped. Saved Scenes are kept.'}).get(code,
                    'The library action stopped safely. Your original indexes are kept. Refresh or ask the maintainer for help.')
            atomic_json(self.library.root/'failure.json',{'code':code,'errorClass':type(error).__name__,
                'originalWorkPreserved':True})

    def close(self):
        self.stop.set()
        self.photo_rgb = None
        if self.thread:
            self.thread.join(200)
            if self.thread.is_alive():
                raise RuntimeError('library_child_not_stopped')
        if self.mma:
            self.mma.disconnect()


HTML = r'''<section id="library-panel" hidden>
<h1>My Scene library</h1><p>Search the Scenes you have saved on this computer.</p>
<details class="card"><summary>Add my own MMA map</summary>
<p>1. Export your map as JSON from MMA, then choose it here. Up to 100,000 locations or 20 MB; panorama IDs are required.</p>
<input id="personal-map-file" type="file" accept=".json,application/json">
<p><label>Country for locations without a country <select id="personal-map-country"><option value="">Use each location’s saved country</option></select></label></p>
<p>Only choose a country if it applies to every location missing one. Unknown camera generations stay unknown.</p>
<button id="personal-map-prepare">2. Prepare my private queue</button>
<button id="personal-map-save" disabled>3. Save my personal queue</button>
<p id="personal-map-note" role="status">Finish Check this computer from the launcher first. Your map and results stay local.</p>
<p>Extract the saved ZIP, open the VISION launcher, choose your queue and select campaign.json. Set your day and night speeds, then Start. Reopen the same queue to continue after an interruption.</p>
</details>
<div class="card"><p id="library-count">Loading your library…</p>
<button id="library-refresh">Refresh library</button>
<p id="library-message" role="status"></p>
<label for="library-prompt">What are you looking for?</label><br>
<input id="library-prompt" placeholder="For example: a narrow road through pine trees" maxlength="2000" style="width:95%;font:inherit;padding:10px"><br>
<p><label>Search <select id="library-scope"><option value="all">All my Scenes</option><option value="personal">My MMA maps</option><option value="community">Community assignments</option></select></label></p>
<p><label>Country <select id="library-country"><option value="">All countries</option></select></label>
<label>Generation <select id="library-generation"><option value="">All generations</option></select></label>
<label>View <select id="library-view"><option value="bestOfFour">Any direction</option><option value="original">Forward</option><option value="right">Right</option><option value="opposite">Backward</option><option value="left">Left</option><option value="originalAxis">Forward or backward</option><option value="sideAxis">Either side</option></select></label></p>
<details><summary>Use a photo from this computer</summary>
<p>Your photo stays on this computer. It is resized locally for the VISION encoder; its filename and metadata are not sent.</p>
<input id="library-photo-file" type="file" accept="image/jpeg,image/png,image/webp">
<button id="library-photo-clear">Clear photo</button>
<p id="library-photo-note" role="status">Choose a JPEG, PNG or WebP image, up to 20 MB.</p>
<canvas id="library-photo-preview" width="224" height="224" hidden aria-label="Selected search photo"></canvas>
<p><label>Include the description <select id="library-photo-weight"><option value="0">Photo only</option><option value="25">Mostly photo</option><option value="50" selected>Photo and description equally</option><option value="75">Mostly description</option></select></label></p>
</details>
<details id="library-street-example"><summary>Use a Street View example</summary>
<p>This retrieves the reference view from Google. Text-only searches use saved indexes without imagery requests.</p>
<label>Or choose a small MMA reference map <input id="library-reference-file" type="file" accept=".json,application/json"></label>
<p id="library-reference-note">Up to eight evenly spaced panorama views from a JSON map, at most 2 MB.</p>
<label>Panorama ID <input id="library-pano" maxlength="80"></label><br>
<label>Heading <input id="library-heading" type="number" min="0" max="359.99" value="0"></label>
<label>Pitch <input id="library-pitch" type="number" min="-90" max="90" value="0"></label>
<label>Zoom <input id="library-zoom" type="number" min="0" max="5" value="0" step="0.1"></label>
</details>
<p>Pause processing before searching. Unknown metadata stays unknown.</p>
<button id="library-search">Search my Scenes</button>
<button id="library-save" disabled>Save results as a map</button>
<p>For local MMA, open a map and drop the saved JSON file onto its window.</p>
<details><summary>Send to an online MMA map (optional)</summary>
<p>Use your own map-making.app API key. It stays in memory until you disconnect or exit. It is never sent to Community.</p>
<label>API key <input id="mma-key" type="password" autocomplete="off" maxlength="2048"></label>
<button id="mma-connect">Connect</button><button id="mma-disconnect">Disconnect</button>
<p><label>Destination map <select id="mma-map"><option value="">Connect to choose a map</option></select></label></p>
<button id="mma-send" disabled>Send these results to this map</button>
<p id="mma-message" role="status"></p></details></div>
<div id="library-results"></div><p id="library-folder" style="overflow-wrap:anywhere"></p>
</section>'''

SCRIPT = r'''
let libraryTimer=null,libraryFilterKey='',libraryOpened=false,mmaConnected=false,referenceExamples=[],photoSelected=false,personalCountriesLoaded=false;
function fillLibrarySelect(id,values,title){const el=document.getElementById(id),prior=el.value;
el.replaceChildren();const all=document.createElement('option');all.value='';all.textContent=title;el.append(all);
for(const v of values){const option=document.createElement('option');option.value=v;option.textContent=v;el.append(option);}el.value=values.includes(prior)?prior:'';}
async function libraryUpdate(){try{const s=await request('/api/library');
document.getElementById('library-count').textContent=s.locations.toLocaleString()+' Scenes in your local library';
document.getElementById('library-message').textContent=s.message;
document.getElementById('library-folder').textContent='Library folder: '+s.path;
document.getElementById('library-search').disabled=s.busy;
document.getElementById('library-refresh').disabled=s.busy;
document.getElementById('personal-map-prepare').disabled=s.busy;
document.getElementById('personal-map-save').disabled=s.busy||!s.personalQueueAvailable;
if(!personalCountriesLoaded){personalCountriesLoaded=true;try{const countries=await request('/api/library/countries');
fillLibrarySelect('personal-map-country',countries,'Use each location’s saved country');}catch(e){personalCountriesLoaded=false;}}
document.getElementById('library-save').disabled=s.busy||!s.mapAvailable;
document.getElementById('mma-send').disabled=s.busy||!s.mapAvailable||!mmaConnected;
const key=JSON.stringify([s.countries,s.generations]);if(key!==libraryFilterKey){
fillLibrarySelect('library-country',s.countries,'All countries');fillLibrarySelect('library-generation',s.generations,'All generations');libraryFilterKey=key;}
if(!s.busy){const output=document.getElementById('library-results');output.replaceChildren();
for(const row of s.results){const card=document.createElement('div');card.className='card';
const meta=row.extra||{},tags=meta.tags||[];const title=document.createElement('p');
title.textContent=(tags.join(' · ')||'Country unknown')+' · '+(meta.visionCameraGeneration||'Generation unknown')+' · heading '+Math.round(row.heading)+'°';
const pose=document.createElement('small');pose.textContent=row.lat.toFixed(5)+', '+row.lng.toFixed(5)+' · '+row.panoId;
const link=document.createElement('a');const url=new URL('https://www.google.com/maps/@');
url.search=new URLSearchParams({api:'1',map_action:'pano',pano:row.panoId,viewpoint:row.lat+','+row.lng,heading:String(row.heading),pitch:String(row.pitch)}).toString();
link.href=url.href;link.target='_blank';link.rel='noopener noreferrer';link.textContent='Open Street View';link.style.color='#79decc';
const example=document.createElement('button');example.textContent='Use as example';example.onclick=async()=>{
await clearPhoto();referenceExamples=[];document.getElementById('library-reference-file').value='';
for(const [id,v] of [['pano',row.panoId],['heading',row.heading],['pitch',row.pitch],['zoom',row.zoom]])document.getElementById('library-'+id).value=v;
document.getElementById('library-street-example').open=true;document.getElementById('library-prompt').focus();};
card.append(title,pose,document.createElement('br'),link,document.createElement('br'),example);output.append(card);}}
if(libraryTimer)clearTimeout(libraryTimer);libraryTimer=s.busy?setTimeout(libraryUpdate,1500):null;
}catch(e){document.getElementById('library-message').textContent='The library window is unavailable. Saved work is kept.';}}
document.getElementById('process-nav').onclick=()=>{document.getElementById('process-panel').hidden=false;document.getElementById('library-panel').hidden=true;};
document.getElementById('library-nav').onclick=()=>{document.getElementById('process-panel').hidden=true;document.getElementById('library-panel').hidden=false;libraryUpdate();};
async function libraryAction(path,body){try{const r=await fetch(path,{method:'POST',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},body:JSON.stringify(body)});
if(!r.ok){const error=await r.json();document.getElementById('library-message').textContent=error.error==='pause_processing_before_search'?'Choose Process Scenes, pause processing, then search again.':'The library action could not start. Your saved work is kept.';return;}
await libraryUpdate();}catch(e){document.getElementById('library-message').textContent='The library action could not start.';}}
document.getElementById('library-refresh').onclick=()=>libraryAction('/api/library/refresh',{});
document.getElementById('library-search').onclick=()=>{const prompt=document.getElementById('library-prompt').value,pano=document.getElementById('library-pano').value.trim();
const examples=photoSelected?[]:pano?[{panoId:pano,heading:Number(document.getElementById('library-heading').value),pitch:Number(document.getElementById('library-pitch').value),zoom:Number(document.getElementById('library-zoom').value)}]:referenceExamples;
libraryAction('/api/library/search',{prompt,libraryScope:document.getElementById('library-scope').value||'all',country:document.getElementById('library-country').value,generation:document.getElementById('library-generation').value,viewDirection:document.getElementById('library-view').value,examples,usePhoto:photoSelected,descriptionWeight:photoSelected?(prompt.trim()?Number(document.getElementById('library-photo-weight').value):0):examples.length?(prompt.trim()?50:0):100,resultCount:50});};
document.getElementById('personal-map-prepare').onclick=async()=>{const note=document.getElementById('personal-map-note');
try{const file=document.getElementById('personal-map-file').files[0];if(!file||file.size>20*1024*1024)throw Error('Choose an MMA JSON file up to 20 MB.');
const documentValue=JSON.parse(await file.text());note.textContent='Preparing your private queue. Follow the library status below…';
const r=await fetch('/api/library/personal-map',{method:'POST',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},
body:JSON.stringify({document:documentValue,country:document.getElementById('personal-map-country').value})});
if(!r.ok){const v=await r.json();throw Error(({personal_map_country_required:'Some locations have no country. Choose their country or add countries in MMA first.',
personal_map_requires_panorama_ids:'Export a map with panorama IDs. This app will not fetch missing IDs automatically.',
pause_processing_before_search:'Pause processing before importing a map.',library_busy:'Wait for the current library action to finish.'})[v.error]||'The map could not be prepared. Check its coordinates and size.');}
await libraryUpdate();}catch(e){note.textContent=e.message||'This map could not be read.';}};
document.getElementById('personal-map-save').onclick=async()=>{try{const r=await fetch('/api/library/personal-queue',{headers:{Authorization:'Bearer '+token}});if(!r.ok)throw Error();
const url=URL.createObjectURL(await r.blob()),link=document.createElement('a');link.href=url;link.download='VISION-Personal-Map.zip';link.click();setTimeout(()=>URL.revokeObjectURL(url),60000);
document.getElementById('personal-map-note').textContent='Extract the ZIP, then open campaign.json using the VISION launcher. Keep that queue to resume your work.';
}catch(e){document.getElementById('personal-map-note').textContent='The queue could not be saved. Import the same map again to recover it.';}};
document.getElementById('library-save').onclick=async()=>{try{const r=await fetch('/api/library/map',{headers:{Authorization:'Bearer '+token}});if(!r.ok)throw Error();
const url=URL.createObjectURL(await r.blob()),link=document.createElement('a');link.href=url;link.download='VISION-search-results.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),60000);
}catch(e){document.getElementById('library-message').textContent='Map results could not be saved.';}};
async function mmaAction(action,value){const message=document.getElementById('mma-message');
if(action==='connect'){mmaConnected=false;document.getElementById('mma-map').replaceChildren();document.getElementById('mma-send').disabled=true;}
message.textContent=action==='send'?'Sending to your selected map…':'Connecting to your MMA account…';
try{const r=await fetch('/api/mma/'+action,{method:'POST',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},body:JSON.stringify(value)});
const result=await r.json();if(!r.ok){message.textContent=result.error==='mma_delivery_needs_check'?'Delivery is uncertain. Check the destination map before importing again. Automatic retry is stopped.':'MMA could not finish. Check your key and connection; your local results are kept.';return;}
if(action==='connect'){mmaConnected=result.connected;const select=document.getElementById('mma-map');select.replaceChildren();
for(const map of result.maps){const option=document.createElement('option');option.value=map.id;option.textContent=map.name;select.append(option);}
message.textContent=result.maps.length?'Connected. Choose the destination map.':'Connected, but no maps were found. Create a map in MMA first.';
}else if(action==='disconnect'){mmaConnected=false;document.getElementById('mma-map').replaceChildren();message.textContent='Disconnected. The API key is no longer held.';
}else message.textContent=result.alreadySent?'These exact results were already sent. Nothing was added again.':result.added+' locations sent to your selected map.';
await libraryUpdate();}catch(e){message.textContent='The MMA request could not finish. If sending, check the destination map before trying again.';}}
document.getElementById('mma-connect').onclick=()=>{const key=document.getElementById('mma-key').value;document.getElementById('mma-key').value='';return mmaAction('connect',{apiKey:key});};
document.getElementById('mma-disconnect').onclick=()=>mmaAction('disconnect',{});
document.getElementById('mma-send').onclick=()=>{const select=document.getElementById('mma-map'),mapId=select.value;
if(!mapId)return;if(confirm('Add the current search results to '+select.options[select.selectedIndex].text+'?'))return mmaAction('send',{mapId});};
document.getElementById('library-reference-file').onchange=async()=>{await clearPhoto();referenceExamples=[];
const note=document.getElementById('library-reference-note'),file=document.getElementById('library-reference-file').files[0];if(!file)return;
if(file.size>2*1024*1024){note.textContent='Choose a reference JSON map smaller than 2 MB.';return;}
try{const map=JSON.parse(await file.text()),rows=Array.isArray(map)?map:(map.customCoordinates||map.locations||map.coordinates||[]);
const usable=rows.filter(r=>r&&typeof r.panoId==='string'&&/^[A-Za-z0-9_-]{4,80}$/.test(r.panoId));
if(!usable.length)throw Error();const count=Math.min(8,usable.length),seen=new Set();
for(let i=0;i<count;i++){const row=usable[Math.round(i*(usable.length-1)/Math.max(1,count-1))];
const pose={panoId:row.panoId,heading:((Number(row.heading||0)%360)+360)%360,pitch:Number(row.pitch||0),zoom:Number(row.zoom||0)};
if(Object.values(pose).slice(1).some(n=>!Number.isFinite(n))||pose.pitch< -90||pose.pitch>90||pose.zoom<0||pose.zoom>5)throw Error();
const key=JSON.stringify(pose);if(!seen.has(key)){referenceExamples.push(pose);seen.add(key);}}
document.getElementById('library-pano').value='';note.textContent=referenceExamples.length+' reference views selected. Choose Search my Scenes to retrieve those views and search.';
}catch(e){referenceExamples=[];note.textContent='This file has no usable panorama views. Choose an MMA JSON map.';}};
async function clearPhoto(){if(photoSelected){const r=await fetch('/api/library/photo',{method:'POST',headers:{Authorization:'Bearer '+token}});if(!r.ok)throw Error('photo_clear_failed');}
photoSelected=false;document.getElementById('library-photo-file').value='';document.getElementById('library-photo-preview').hidden=true;
document.getElementById('library-photo-note').textContent='Photo cleared. Text-only searches need no imagery requests.';}
document.getElementById('library-photo-clear').onclick=()=>clearPhoto().catch(()=>{document.getElementById('library-photo-note').textContent='Could not clear the photo. Exit the app to discard it.';});
document.getElementById('library-photo-file').onchange=async()=>{const input=document.getElementById('library-photo-file'),file=input.files[0],note=document.getElementById('library-photo-note');
try{await clearPhoto();if(!file)return;
if(file.size>20*1024*1024||!['image/jpeg','image/png','image/webp'].includes(file.type))throw Error('Choose a JPEG, PNG or WebP smaller than 20 MB.');
const bitmap=await createImageBitmap(file,{resizeWidth:224,resizeHeight:224,resizeQuality:'high',imageOrientation:'from-image'});
const canvas=document.getElementById('library-photo-preview'),context=canvas.getContext('2d',{willReadFrequently:true});
context.fillStyle='#fff';context.fillRect(0,0,224,224);context.drawImage(bitmap,0,0,224,224);bitmap.close();
const rgba=context.getImageData(0,0,224,224).data,rgb=new Uint8Array(224*224*3);
for(let p=0,q=0;p<rgba.length;p+=4){rgb[q++]=rgba[p];rgb[q++]=rgba[p+1];rgb[q++]=rgba[p+2];}
const r=await fetch('/api/library/photo',{method:'POST',headers:{Authorization:'Bearer '+token,'Content-Type':'application/octet-stream'},body:rgb});
if(!r.ok)throw Error('The local photo could not be selected. Pause a running search and try again.');
photoSelected=true;referenceExamples=[];document.getElementById('library-pano').value='';document.getElementById('library-reference-file').value='';
canvas.hidden=false;note.textContent='Photo ready. Choose Search my Scenes. No Google request is needed.';
}catch(e){photoSelected=false;note.textContent=e.message||'This image could not be read.';}};

'''


def page_with_library(page):
    page = page.replace('<h1>Process Scenes on your computer</h1>',
        '<nav><button id="process-nav">Process Scenes</button><button id="library-nav" hidden>My library</button></nav>'
        '<section id="process-panel"><h1>Process Scenes on your computer</h1>')
    page = page.replace('Uploads, search and credit earning are not enabled.',
        'Your saved Scenes can be searched in My library. Uploads and credit earning are not enabled.')
    page = page.replace('</main><script', '</section>'+HTML+'</main><script')
    page = page.replace("if(s.readiness){", "document.getElementById('library-nav').hidden=!s.libraryAvailable;if(s.readiness){")
    page = page.replace("if(s.readiness){", "if(s.libraryOnly){document.getElementById('process-panel').hidden=true;document.getElementById('library-panel').hidden=false;document.getElementById('process-nav').hidden=true;if(!libraryOpened){libraryOpened=true;libraryUpdate();}}if(s.readiness){")
    return page.replace('</script></html>',SCRIPT+'</script></html>')
