"""Optional saved Object search in the existing private library window."""
from __future__ import annotations

import json
from pathlib import Path
import re
import threading

from .local_object_library import ObjectLibrary, MAX_ARCHIVE, runtime_entries, task
from .local_scene_pilot import atomic_json


def begin(session,action,*,raw=None,query=None):
    with session.guard:
        if session.thread and session.thread.is_alive():raise ValueError('library_busy')
        if session.app.thread and session.app.thread.is_alive():raise ValueError('pause_processing_before_search')
        session.stop.clear()
        session.phase='searching' if action=='search' else 'preparing'
        session.message={'setup':'Preparing private Object search files. The first download is about 900 MB; this does not index locations.',
            'import':'Checking this saved Object index. Its original packed records stay unchanged.',
            'search':'Preparing and searching saved Objects. The first description search can take a few minutes; no imagery is retrieved.'}[action]
        session.result=None
        session.thread=threading.Thread(target=run,args=(session,action,raw,query),name='local-object-library',daemon=False)
        session.thread.start()


def run(session,action,raw,query):
    try:
        result=task(session.data_dir,session.app.runtime_root,action,raw=raw,query=query,stop=session.stop)
        with session.guard:
            session.phase='complete'
            if action=='search':
                session.result=result
                session.message=f'{len(result["map"]["customCoordinates"])} results from {result["locations"]:,} saved Object locations.'
            elif action=='setup':
                session.message='Object search files are ready. Choose a saved Object library ZIP to import.'
            else:
                session.message=('This Object index is already in your library.' if result['alreadyPresent'] else
                    f'{result["added"]:,} saved Object locations imported. You can search them below.')
    except Exception as error:
        code=str(error)
        with session.guard:
            session.phase='error'
            session.message={'local_object_setup_required':'Choose Set up Object search first. Its private files need to be downloaded once.',
                'local_object_overlap':'This index overlaps locations already saved here. It was not added; the existing library is kept.',
                'local_object_library_empty':'Import a saved Object library ZIP first. New Object processing is still awaiting compatibility checks.',
                'library_search_cancelled':'The Object action stopped. Your saved indexes are kept.',
                'runtime_download_failed':'Setup could not finish its download. Choose Set up Object search to resume.',
                'local_object_runtime_changed':'An Object program or model did not match its expected hash. Run setup again.',
                'local_object_saved_index_changed':'A saved Object file changed. Your original ZIP and other work are kept.'}.get(code,
                    'The Object action could not finish. Keep the original ZIP and ask the maintainer for help.')
        atomic_json(session.object_library.root/'failure.json',{'code':code if re.fullmatch('[a-z_]{1,70}',code) else 'local_object_action_failed',
            'errorClass':type(error).__name__,'originalWorkPreserved':True})


def handle_post(handler,session):
    """Return True only for this feature's exact authenticated routes."""
    route=handler.path
    if route not in ('/api/library/objects/setup','/api/library/objects/import','/api/library/objects/search'):
        return False
    if not handler.allowed(action=True) or handler.headers.get('Transfer-Encoding') is not None:
        handler.send(403,{'error':'local_access_denied'});handler.close_connection=True
        return True
    try:
        if session is None:raise ValueError('library_unavailable')
        size=int(handler.headers.get('Content-Length','0'))
        maximum=MAX_ARCHIVE if route.endswith('/import') else 8192
        if not 0<size<=maximum:raise ValueError('local_object_request_limit')
        body=handler.rfile.read(size)
        if len(body)!=size:raise ValueError('invalid_local_object_request')
        if route.endswith('/import'):
            begin(session,'import',raw=body)
        else:
            value=json.loads(body)
            if not isinstance(value,dict):raise ValueError('invalid_local_object_request')
            if route.endswith('/setup'):
                if value!={'allowDownloads':True} or type(value['allowDownloads']) is not bool:
                    raise ValueError('local_object_download_consent_required')
                begin(session,'setup')
            else:
                begin(session,'search',query=value)
        handler.send(202,{'ok':True,'processingApproved':False,'communitySubmissionAllowed':False})
    except Exception as error:
        handler.send(409,{'error':str(error) if str(error) in ('pause_processing_before_search','library_busy',
            'local_object_download_consent_required','local_object_request_limit') else 'local_object_action_failed'})
    handler.close_connection=True
    return True


HTML=r'''<details class="card" id="objects-panel"><summary>Search saved Objects</summary>
<p>Search an Object index you already have. This uses VISION’s existing Object search engine. New Object processing is awaiting its compatibility check.</p>
<p id="objects-count">Your Object library is separate from your Scenes.</p>
<p>1. Prepare the search files once, then import an Object library ZIP from the maintainer or your own VISION export. Regular MMA maps contain locations, not Object indexes.</p>
<button id="objects-setup">Set up Object search</button>
<label>Object library ZIP <input id="objects-file" type="file" accept=".zip,application/zip"></label>
<button id="objects-import">Import saved Objects</button>
<p id="objects-note" role="status">Files and results stay on this computer. No locations are indexed or uploaded by these controls.</p>
<p><label>Find an object <input id="objects-prompt" maxlength="1000" placeholder="For example: a clock or a blue sculpture"></label></p>
<p><label>Country <select id="objects-country"><option value="">All countries</option></select></label>
<label>Generation <select id="objects-generation"><option value="">All generations</option></select></label>
<label>Confidence <select id="objects-confidence"><option value="balanced">Balanced</option><option value="highRecall">Find more</option><option value="precise">Higher confidence</option></select></label></p>
<button id="objects-search">Search my Objects</button>
<p>Object results appear below. Use the same Save results as a map or optional MMA connection. Country and generation use the index’s saved metadata; unknown stays unknown.</p>
</details>'''

SCRIPT=r'''
function updateObjects(s){if(!s)return;
document.getElementById('objects-count').textContent=s.locations.toLocaleString()+' saved Object locations';
const busy=document.getElementById('library-search').disabled;
for(const id of ['objects-setup','objects-import','objects-search'])document.getElementById(id).disabled=busy;
fillLibrarySelect('objects-country',s.countries,'All countries');fillLibrarySelect('objects-generation',s.generations,'All generations');}
document.getElementById('objects-setup').onclick=async()=>{
if(!confirm('Prepare private Object search files? The first download is about 900 MB. Existing verified files are reused. This does not process locations.'))return;
await libraryAction('/api/library/objects/setup',{allowDownloads:true});};
document.getElementById('objects-import').onclick=async()=>{const note=document.getElementById('objects-note');try{
const file=document.getElementById('objects-file').files[0];if(!file||file.size>40*1024*1024)throw Error('Choose an Object library ZIP up to 40 MB.');
const response=await fetch('/api/library/objects/import',{method:'POST',headers:{Authorization:'Bearer '+token,'Content-Type':'application/zip'},body:await file.arrayBuffer()});
if(!response.ok){const error=await response.json();throw Error(error.error==='pause_processing_before_search'?'Pause processing before importing Objects.':'The import could not start. Wait for the current library action, then try again.');}
note.textContent='Checking the index. Follow the library status above.';await libraryUpdate();
}catch(error){note.textContent=error.message||'The ZIP could not be opened.';}};
document.getElementById('objects-search').onclick=()=>libraryAction('/api/library/objects/search',{
prompt:document.getElementById('objects-prompt').value,confidence:document.getElementById('objects-confidence').value,
country:document.getElementById('objects-country').value,generation:document.getElementById('objects-generation').value,resultCount:50});
'''
