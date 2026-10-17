"""One saved-index/app flow; synthetic native output, no inference/downloads."""
import copy
import http.client
from http.server import ThreadingHTTPServer
import io
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch, Mock
import zipfile

from community import local_object_library as objects
from community.local_scene_library_ui import LibrarySession, page_with_library
from community.local_scene_ui import PAGE, handler_for
from community.tests.test_object_index import contract_bundle


class LocalObjectLibraryTest(unittest.TestCase):
    def test_private_import_search_integrity_and_app_authority(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);runtime=root/'runtime';runtime.mkdir()
            library=objects.ObjectLibrary(root/'objects')
            items=[{'locationId':1,'panoId':'synthetic-object-one','lat':10,'lng':20,'heading':90,
                'country':'Italy','cameraGeneration':'gen4'}]
            manifest,files,source=contract_bundle(items,'a'*32,root/'private-source.tsv')
            source=source.replace(b'\t0\n',b'\t1234\n')
            manifest.update(sourceBytes=len(source),sourceSha256=objects.sha(source),globalStart=1234,minimumGlobalLocation=1234,maximumGlobalLocation=1234)
            from community.object_index import global_id_record
            files['global-location-ids.bin']=global_id_record(1234)
            manifest['globalIds'].update(sha256=objects.sha(files['global-location-ids.bin']))
            manifest['sourceTsv']='locations.tsv'
            manifest['frozenViewsManifestSha256']='d'*64
            raw=objects.make_archive(manifest,files,source,'My private saved Objects')
            before={n:b for n,b in files.items()}
            calls=[]
            def verifier(path):
                return root/'unexecuted-vision-object',root/'unexecuted-models'
            def native(command,job):
                calls.append(command)
                if command[1]=='verify-index':
                    mounted=json.loads(Path(command[command.index('--manifest')+1]).read_text())
                    self.assertEqual(mounted['sourceTsv'],command[command.index('--source-tsv')+1])
                    self.assertEqual(mounted['frozenViewsManifestSha256'],'d'*64)
                    (job/'stdout.log').write_text(json.dumps({'valid':True,'full':True,'indexVersion':4,
                        'indexedLocations':1,'sourceId':manifest['sourceId']}))
                else:
                    spec=json.loads((job/'input.json').read_text())
                    self.assertEqual(spec['resultPruneMeters'],0)
                    self.assertEqual(spec['queries'][0]['route'],'common')
                    for entry in spec['sources']:
                        self.assertEqual(json.loads(Path(entry['manifestPath']).read_text())['sourceTsv'],entry['sourceTsv'])
                        for name,body in before.items():self.assertEqual((Path(entry['indexDir'])/name).read_bytes(),body)
                    hit={'locationIndex':1234,'similarity':.85,'viewOffset':2,
                        'location':{'lat':10.,'lng':20.,'heading':90.,'pitch':0.,'zoom':0.,
                            'panoId':'synthetic-object-one','country':'Italy','cameraGeneration':'gen4'},
                        'object':{'classId':3,'className':'car','lane':'common','confidence':.85,'supportCount':2,
                            'heading':135.,'pitch':-4.,'zoom':1.5,'bboxArea':.04}}
                    (job/'output.json').write_text(json.dumps({'contractVersion':2,'totalLocations':1,
                        'queries':[{'name':spec['queries'][0]['name'],'query':'car','mode':'objects','hits':[hit]}]}))
            result=library.import_archive(raw,runtime,runner=native,verifier=verifier)
            self.assertEqual(result['added'],1)
            self.assertEqual(library.status()['locations'],1)
            identity,*_=objects.read_archive(raw)
            receipt=json.loads((library.root/identity/'local-receipt.json').read_text())
            self.assertTrue(receipt['diagnostic']);self.assertFalse(receipt['processingApproved'])
            self.assertFalse(receipt['communitySubmissionAllowed'])
            self.assertTrue(library.import_archive(raw,runtime,runner=native,verifier=verifier)['alreadyPresent'])
            self.assertEqual(len(calls),1)
            query={'prompt':'car','confidence':'balanced','country':'Italy','generation':'gen4','resultCount':50}
            answer=library.search(query,runtime,runner=native,verifier=verifier)
            pose=answer['map']['customCoordinates'][0]
            self.assertEqual((pose['heading'],pose['pitch'],pose['zoom']),(135.,-4.,1.5))
            self.assertEqual(pose['extra']['visionObjectClass'],'car')
            self.assertEqual(pose['extra']['visionOriginalGlobalLocationId'],1234)
            self.assertEqual(answer['uploads'],0)
            for name,body in before.items():self.assertEqual((library.root/identity/name).read_bytes(),body)
            overlapping=copy.deepcopy(manifest);overlapping['sourceId']='another-local-source'
            with self.assertRaisesRegex(ValueError,'local_object_overlap'):
                library.import_archive(objects.make_archive(overlapping,files,source,'Overlapping'),runtime,runner=native,verifier=verifier)
            with self.assertRaisesRegex(ValueError,'invalid_local_object_query'):
                library.search({**query,'confidence':[]},runtime,runner=native,verifier=verifier)
            corrupt=io.BytesIO()
            with zipfile.ZipFile(io.BytesIO(raw)) as original,zipfile.ZipFile(corrupt,'w') as archive:
                for member in original.infolist():archive.writestr(member,original.read(member))
                archive.writestr('../outside',b'forbidden')
            with self.assertRaises(ValueError):objects.read_archive(corrupt.getvalue())
            (library.root/identity/'semantic-pq128.bin').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'local_object_saved_index_changed'):
                library.search(query,runtime,runner=native,verifier=verifier)
            self.assertEqual(library.status()['locations'],1)
            self.assertEqual(len(calls),2)
            # No empty/failed verification can publish a second index.
            other=[{**items[0],'locationId':2,'panoId':'synthetic-object-two'}]
            second,second_files,second_source=contract_bundle(other,'b'*32,root/'private-second.tsv')
            second['sourceTsv']='locations.tsv'
            def failed_native(command,job):
                (job/'stdout.log').write_text('{"valid":false}')
            with self.assertRaisesRegex(ValueError,'local_object_native_verification_failed'):
                library.import_archive(objects.make_archive(second,second_files,second_source,'Second'),runtime,
                    runner=failed_native,verifier=verifier)
            self.assertEqual(library.status()['locations'],1)
            # Setup consent and downloaded hashes are enforced separately.
            entry={'path':'object-runtime/vision-object','asset':'synthetic','sha256':objects.sha(b'expected'),'bytes':8,'executable':True}
            with patch.object(objects,'runtime_entries',return_value=[entry]):
                with self.assertRaisesRegex(ValueError,'local_object_setup_required'):
                    objects.setup_runtime(root/'setup')
                def wrong_download(url,path,item):path.write_bytes(b'incorrect')
                with self.assertRaisesRegex(ValueError,'local_object_runtime_changed'):
                    objects.setup_runtime(root/'setup',allow_downloads=True,downloader=wrong_download)
            # Existing loopback authentication guards the new app controls.
            app=SimpleNamespace(root=root,packet={'packetId':'e'*64},thread=None,runtime_root=runtime,pause=Mock())
            (root/'data').mkdir()
            session=LibrarySession(app,root/'data')
            app.library_session=session
            self.assertFalse(session.status()['objects']['processingEnabled'])
            page=page_with_library(PAGE)
            self.assertIn('Search my Objects',page)
            self.assertIn('function updateObjects',page)
            server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(app,'a'*64))
            worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
            client=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
            origin=f'http://127.0.0.1:{server.server_port}'
            try:
                with patch('community.local_object_ui.begin') as begin:
                    client.request('POST','/api/library/objects/setup',body='{"allowDownloads":true}',
                        headers={'Authorization':'Bearer '+'a'*64,'Origin':'https://untrusted.example'})
                    response=client.getresponse();self.assertEqual(response.status,403);response.read();begin.assert_not_called()
                    client.request('POST','/api/library/objects/setup',body='{"allowDownloads":false}',
                        headers={'Authorization':'Bearer '+'a'*64,'Origin':origin})
                    response=client.getresponse();self.assertEqual(response.status,409);response.read();begin.assert_not_called()
                    client.request('POST','/api/library/objects/setup',body='{"allowDownloads":true}',
                        headers={'Authorization':'Bearer '+'a'*64,'Origin':origin})
                    response=client.getresponse();self.assertEqual(response.status,202);response.read();begin.assert_called_once_with(session,'setup')
            finally:
                client.close();server.shutdown();server.server_close();worker.join(5);session.close()


if __name__=='__main__':unittest.main()
