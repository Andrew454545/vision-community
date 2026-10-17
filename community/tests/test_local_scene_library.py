"""Focused library, assignment import and private HTTP checks; no live providers."""
from contextlib import nullcontext
import hashlib
import http.client
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from community.local_scene_archive import export_saved_results
from community.local_scene_campaign import allocate_campaign
from community.local_scene_import import ImportAuthority, read_archive
from community.local_scene_library import SceneLibrary
from community.local_scene_library_ui import LibrarySession
from community.local_scene_packets import prepare_catalog, canonical, digest
from community.local_scene_pilot import LocalScenePilot
from community.local_scene_ui import handler_for
from community.tests import test_local_scene_archive as archive_helpers
from community.tests.test_local_scene_campaign import approval, excluded
from community.tests.test_local_scene_pilot import catalog
from community.tests.test_vision_index import fake_runner
from community.vision_index import index_locations_tsv, VisionIndexError

PROFILE = archive_helpers.PROFILE

def models(root):
    root.mkdir()
    for name in ('vision_model.onnx','vision_model_fp32.onnx','text_model.onnx','tokenizer.json'):
        (root/name).write_bytes(b'synthetic-unexecuted-model')
    return root


class LibraryTests(unittest.TestCase):
    def test_incremental_segments_copy_bytes_once_and_search_preserves_camera_filters(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            app=archive_helpers.ArchiveTest().make(root,count=17,pause=True)
            library=SceneLibrary(root/'library');self.assertEqual(library.add_pilot(app.root),16)
            model=models(root/'models')
            with patch('community.local_scene_library.SHARD_LOCATIONS',8):
                with library.writing(): before,total=library._segments(model)
                self.assertEqual(total,16)
                app.start();app.thread.join(10)
                self.assertEqual(app.phase,'complete')
                self.assertEqual(library.add_pilot(app.root),1)
                self.assertEqual(library.add_pilot(app.root),0)
                with library.writing(): after,total=library._segments(model)
                self.assertEqual(after[:2],before);self.assertEqual(total,17)
                expected=b''.join((app.root/f'part-{n:04d}/attempt-0001/index/shard-000000.i8').read_bytes() for n in range(2))
                self.assertEqual(b''.join((p/'index/shard-000000.i8').read_bytes() for p in after),expected)
                requests=[]
                def native(argv,job):
                    request=json.loads((job/'input.json').read_text());requests.append(request)
                    output={'version':4,'completed':True,'fetchErrors':0,'inferenceErrors':0,'incompleteLocations':0,
                        'queries':[{'name':'My VISION results','hits':[{'locationIndex':0,'similarity':0.8,'viewOffset':1}]}]}
                    Path(argv[argv.index('--output')+1]).write_text(json.dumps(output))
                result=library.search({'prompt':'a road','country':'France','generation':'gen2','viewDirection':'right'},
                    root/'runtime',runtime_verifier=lambda _: (Path('unused-native'),model,PROFILE),native_runner=native)
                self.assertEqual(result['locations'],17);self.assertEqual(result['indexes'],3)
                self.assertEqual(len(result['map']['customCoordinates']),1) # Cross-segment100m pruning.
                row=result['map']['customCoordinates'][0]
                self.assertEqual((row['heading'],row['pitch'],row['zoom']),(213.5,-2,1))
                self.assertIn('France',row['extra']['tags']);self.assertEqual(row['extra']['visionCameraGeneration'],'gen2')
                self.assertEqual(requests[0]['queries'][0]['includeCountries'],['France'])
                self.assertEqual(requests[0]['queries'][0]['cameraGenerations'],['gen2'])
                self.assertEqual(requests[0]['queries'][0]['viewOffsets'],[1])
                self.assertFalse(requests[0]['queries'][0]['examples'])

    def test_changed_original_and_missing_views_never_enter_the_library(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);app=archive_helpers.ArchiveTest().make(root,count=2)
            path=app.root/'part-0000/attempt-0001/index/shard-000000.mask'
            path.write_bytes(b'\x01\x01')
            receipt_path=app.root/'part-0000/complete.json';receipt=json.loads(receipt_path.read_text())
            receipt['files']['index/shard-000000.mask']={'bytes':2,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
            receipt_path.write_bytes(canonical(receipt))
            library=SceneLibrary(root/'library')
            with self.assertRaises(VisionIndexError):library.add_pilot(app.root)
            self.assertEqual(library.status()['locations'],0)

    def test_owner_import_requires_original_assignment_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);registry=root/'issuer.sqlite';prepare_catalog(catalog(root,3),registry);excluded(root,registry)
            accepted=approval();accepted['runtimeProfile']=PROFILE
            accepted['sha256']=digest({k:v for k,v in accepted.items() if k!='sha256'})
            campaign=allocate_campaign(registry,'tester',2,'assigned',[accepted],root/'queue')
            def indexer(tsv,**kwargs):kwargs['runner']=fake_runner;return index_locations_tsv(tsv,**kwargs)
            app=LocalScenePilot(root/'queue/packets/000000.json',root/'data',root/'runtime',indexer=indexer,
                runtime_verifier=lambda _: (Path('unused-native'),Path('unused-models'),PROFILE),group_size=128)
            with patch('community.background.keep_awake',return_value=nullcontext()):app.start();app.thread.join(10)
            self.assertEqual(app.phase,'complete')
            from community.local_scene_transport import execution
            receipt_path=app.root/'part-0000/complete.json'
            receipt=json.loads(receipt_path.read_text())
            _,receipt['networkExecution']=execution(app.root/'part-0000/attempt-0001/input.json')
            receipt_path.write_bytes(canonical(receipt)+b'\n')
            backup=export_saved_results(app.root,root/'results.zip',portable=True)
            before=hashlib.sha256(registry.read_bytes()).hexdigest()
            owner=SceneLibrary(root/'owner-library');authority=ImportAuthority(registry,'assigned')
            self.assertEqual(authority.import_archive(Path(backup['path']),owner)['added'],2)
            self.assertEqual(authority.import_archive(Path(backup['path']),owner)['added'],0)
            collection={'contract':'vision-local-scene-collection-v1','campaignSha256':campaign['sha256'],
                'locations':2,'total':2,'complete':True,'uploaded':False,'qualityStatus':'LOCAL_PROVISIONAL',
                'archives':[{'path':'000000.zip','packetId':app.packet['packetId'],
                    'runtimeProfileSha256':PROFILE['sha256'],'locations':2,'sha256':backup['sha256'],'bytes':backup['bytes']}]}
            (root/'000000.zip').write_bytes(Path(backup['path']).read_bytes())
            collection_path=root/f'collection-{digest(collection)}.json';collection_path.write_bytes(canonical(collection))
            self.assertEqual(authority.import_collection(collection_path,owner)['added'],0)
            self.assertEqual(hashlib.sha256(registry.read_bytes()).hexdigest(),before)
            with self.assertRaisesRegex(ValueError,'assignment_missing'):ImportAuthority(registry,'not-assigned')
            with zipfile.ZipFile(root/'results.zip') as original,zipfile.ZipFile(root/'bad.zip','w') as changed:
                for name in original.namelist():changed.writestr(name,original.read(name))
                changed.writestr('../escape',b'not allowed')
            with self.assertRaises(ValueError):read_archive(root/'bad.zip')
            self.assertFalse((root/'escape').exists())

    def test_library_api_uses_token_origin_and_returns_only_a_private_map(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);app=SimpleNamespace(thread=None,runtime_root=root/'runtime',
                status=lambda:{'packetId':'test','phase':'ready'})
            session=LibrarySession(app,root,searcher=lambda *_a,**_k:{'locations':0,'map':None})
            app.library_session=session
            server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(app,'private-token'))
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                client=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
                client.request('GET','/api/library');response=client.getresponse();self.assertEqual(response.status,403);response.read()
                headers={'Authorization':'Bearer private-token','Origin':'https://untrusted.example','Content-Type':'application/json'}
                client.request('POST','/api/library/refresh','{}',headers);response=client.getresponse();self.assertEqual(response.status,403);response.read()
                headers['Origin']=f'http://127.0.0.1:{server.server_port}'
                client.request('POST','/api/library/refresh','{}',headers);response=client.getresponse();self.assertEqual(response.status,202);response.read()
                session.thread.join(5)
                client.request('GET','/api/library',headers={'Authorization':'Bearer private-token'})
                response=client.getresponse();self.assertEqual(response.status,200);self.assertTrue(json.loads(response.read())['localOnly'])
                client.request('GET','/',headers={});response=client.getresponse();page=response.read().decode()
                self.assertIn('My Scene library',page);self.assertIn('originalAxis',page)
                from community.local_scene_mma import MMAConnection
                calls=[]
                def transport(path,key,**kwargs):
                    calls.append(path)
                    return [{'id':'selected-map','name':'Private map'}] if path=='/api/maps' else {}
                session.mma=MMAConnection(session.library.root,transport=transport)
                session.result={'map':{'name':'Saved results','customCoordinates':[{'lat':10,'lng':20,'panoId':'test-pano'}]}}
                headers['Origin']='https://untrusted.example'
                client.request('POST','/api/mma/connect',json.dumps({'apiKey':'test-private-key'}),headers)
                response=client.getresponse();self.assertEqual(response.status,403);response.read();self.assertEqual(calls,[])
                headers['Origin']=f'http://127.0.0.1:{server.server_port}'
                for action,body in [('connect',{'apiKey':'test-private-key'}),('send',{'mapId':'selected-map'}),('disconnect',{})]:
                    client.request('POST','/api/mma/'+action,json.dumps(body),headers)
                    response=client.getresponse();self.assertEqual(response.status,200);response.read()
                self.assertEqual(calls,['/api/maps','/api/maps/selected-map/locations'])
                self.assertFalse(session.mma.status()['connected'])
                from community.local_scene_photo import RGB_BYTES
                headers['Origin']='https://untrusted.example'
                client.request('POST','/api/library/photo',b'p'*RGB_BYTES,headers)
                response=client.getresponse();self.assertEqual(response.status,403);response.read()
                self.assertIsNone(session.photo_rgb)
                headers['Origin']=f'http://127.0.0.1:{server.server_port}'
                client.request('POST','/api/library/photo',b'p'*RGB_BYTES,headers)
                response=client.getresponse();self.assertEqual(response.status,200);self.assertFalse(json.loads(response.read())['storedOnDisk'])
                self.assertEqual(session.photo_rgb,b'p'*RGB_BYTES)
                forwarded=[]
                def searcher(query,_runtime,**kwargs):
                    forwarded.append((query,kwargs['photo_rgb']))
                    return {'locations':0,'map':None}
                session.searcher=searcher
                session.begin({'prompt':'local photo','usePhoto':True});session.thread.join(5)
                self.assertEqual(forwarded,[({'prompt':'local photo'},b'p'*RGB_BYTES)])
                client.request('POST','/api/library/photo',b'',headers)
                response=client.getresponse();self.assertEqual(response.status,200);response.read()
                self.assertIsNone(session.photo_rgb)

            finally:
                client.close();server.shutdown();server.server_close();thread.join(5);session.close()


if __name__=='__main__':unittest.main()
