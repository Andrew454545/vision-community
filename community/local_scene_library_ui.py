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
    def __init__(self, app, data_dir, *, searcher=None):
        self.app = app
        self.data_dir = regular(data_dir, directory=True)
        self.library = SceneLibrary(self.data_dir/'library')
        self.searcher = searcher or self.library.search
        self.guard = threading.RLock()
        self.thread = None
        self.stop = threading.Event()
        self.phase, self.message = 'ready', 'Your completed Scenes appear here. Refresh to recover saved work.'
        self.result = None
        # The callback adds only metadata/references. Vector compaction waits
        # until a search, so every128-location batch does not rewrite a segment.
        app.on_completed_pilot = self.add_completed

    def add_completed(self, root):
        try:
            self.library.add_pilot(root)
        except Exception as error:
            atomic_json(self.library.root/'failure.json', {'errorClass':type(error).__name__,
                'code':'library_refresh_needed','originalWorkPreserved':True})

    def _recover(self):
        with self.library.guard, self.library._db() as db:
            known = {Path(row[0]).parents[1] for row in db.execute('SELECT path FROM sources')}
        for root in sorted(self.data_dir.iterdir()):
            if self.stop.is_set():
                return
            if not re.fullmatch('[a-f0-9]{64}', root.name):
                continue
            regular(root, directory=True)
            if (root/'campaign.json').exists():
                from .local_scene_campaign import load_manifest, campaign_packet
                manifest = load_manifest(root/'campaign.json')
                progress = regular(root/'progress.sqlite', missing=True)
                if not progress.exists():
                    continue
                with sqlite3.connect(progress.as_uri()+'?mode=ro',uri=True) as db:
                    completed = db.execute('SELECT ordinal,profile FROM work WHERE status="complete" ORDER BY ordinal').fetchall()
                for ordinal, profile in completed:
                    if self.stop.is_set():
                        return
                    if not re.fullmatch('[a-f0-9]{64}',str(profile)) or not 0<=ordinal<len(manifest['packets']):
                        raise ValueError('library_progress_changed')
                    pilot = root/'work'/profile/manifest['packets'][ordinal]['packetId']
                    if pilot not in known:
                        campaign_packet(root,manifest,ordinal)
                        self.library.add_pilot(pilot)
            elif (root/'packet.json').exists() and (root/'runtime-profile.json').exists():
                self.library.add_pilot(root)

    def status(self):
        with self.guard:
            return {**self.library.status(),'phase':self.phase,'message':self.message,
                'busy':bool(self.thread and self.thread.is_alive()),
                'results':(self.result.get('map') or {}).get('customCoordinates',[]) if self.result else [],
                'mapAvailable':bool(self.result and self.result.get('map'))}

    def begin(self, query=None):
        with self.guard:
            if self.thread and self.thread.is_alive():
                raise ValueError('library_busy')
            if query is not None and self.app.thread and self.app.thread.is_alive():
                raise ValueError('pause_processing_before_search')
            self.phase = 'refreshing' if query is None else 'searching'
            self.message = ('Finding your completed Scenes…' if query is None else
                'Searching your saved Scenes on this computer. Your queue stays paused.')
            self.result = None
            self.stop.clear()
            self.thread = threading.Thread(target=self._run,args=(query,),name='local-scene-library',daemon=False)
            self.thread.start()

    def _run(self, query):
        try:
            self._recover()
            if query is not None and not self.stop.is_set():
                result = self.searcher(query,self.app.runtime_root,stop=self.stop)
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
                    'library_search_cancelled':'Search stopped. Saved Scenes are kept.'}).get(code,
                    'The library action stopped safely. Your original indexes are kept. Refresh or ask the maintainer for help.')
            atomic_json(self.library.root/'failure.json',{'code':code,'errorClass':type(error).__name__,
                'originalWorkPreserved':True})

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(200)
            if self.thread.is_alive():
                raise RuntimeError('library_child_not_stopped')


HTML = '''<section id="library-panel" hidden>
<h1>My Scene library</h1><p>Search the Scenes you have saved on this computer.</p>
<div class="card"><p id="library-count">Loading your library…</p>
<button id="library-refresh">Refresh library</button>
<p id="library-message" role="status"></p>
<label for="library-prompt">What are you looking for?</label><br>
<input id="library-prompt" placeholder="For example: a narrow road through pine trees" maxlength="2000" style="width:95%;font:inherit;padding:10px"><br>
<p><label>Country <select id="library-country"><option value="">All countries</option></select></label>
<label>Generation <select id="library-generation"><option value="">All generations</option></select></label>
<label>View <select id="library-view"><option value="bestOfFour">Any direction</option><option value="original">Forward</option><option value="right">Right</option><option value="opposite">Backward</option><option value="left">Left</option><option value="originalAxis">Forward or backward</option><option value="sideAxis">Either side</option></select></label></p>
<details><summary>Use a Street View example</summary>
<p>This retrieves the reference view from Google. Text-only searches use saved indexes without imagery requests.</p>
<label>Panorama ID <input id="library-pano" maxlength="80"></label><br>
<label>Heading <input id="library-heading" type="number" min="0" max="359.99" value="0"></label>
<label>Pitch <input id="library-pitch" type="number" min="-90" max="90" value="0"></label>
<label>Zoom <input id="library-zoom" type="number" min="0" max="5" value="0" step="0.1"></label>
</details>
<p>Pause processing before searching. Unknown metadata stays unknown.</p>
<button id="library-search">Search my Scenes</button>
<button id="library-save" disabled>Save results as a map</button></div>
<div id="library-results"></div><p id="library-folder" style="overflow-wrap:anywhere"></p>
</section>'''

SCRIPT = '''
let libraryTimer=null,libraryFilterKey='',libraryOpened=false;
function fillLibrarySelect(id,values,title){const el=document.getElementById(id),prior=el.value;
el.replaceChildren();const all=document.createElement('option');all.value='';all.textContent=title;el.append(all);
for(const v of values){const option=document.createElement('option');option.value=v;option.textContent=v;el.append(option);}el.value=values.includes(prior)?prior:'';}
async function libraryUpdate(){try{const s=await request('/api/library');
document.getElementById('library-count').textContent=s.locations.toLocaleString()+' Scenes in your local library';
document.getElementById('library-message').textContent=s.message;
document.getElementById('library-folder').textContent='Library folder: '+s.path;
document.getElementById('library-search').disabled=s.busy;
document.getElementById('library-refresh').disabled=s.busy;
document.getElementById('library-save').disabled=s.busy||!s.mapAvailable;
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
const example=document.createElement('button');example.textContent='Use as example';example.onclick=()=>{
for(const [id,v] of [['pano',row.panoId],['heading',row.heading],['pitch',row.pitch],['zoom',row.zoom]])document.getElementById('library-'+id).value=v;
document.querySelector('#library-panel details').open=true;document.getElementById('library-prompt').focus();};
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
const examples=pano?[{panoId:pano,heading:Number(document.getElementById('library-heading').value),pitch:Number(document.getElementById('library-pitch').value),zoom:Number(document.getElementById('library-zoom').value)}]:[];
libraryAction('/api/library/search',{prompt,country:document.getElementById('library-country').value,generation:document.getElementById('library-generation').value,viewDirection:document.getElementById('library-view').value,examples,descriptionWeight:examples.length?(prompt.trim()?50:0):100,resultCount:50});};
document.getElementById('library-save').onclick=async()=>{try{const r=await fetch('/api/library/map',{headers:{Authorization:'Bearer '+token}});if(!r.ok)throw Error();
const url=URL.createObjectURL(await r.blob()),link=document.createElement('a');link.href=url;link.download='VISION-search-results.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),60000);
}catch(e){document.getElementById('library-message').textContent='Map results could not be saved.';}};
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
