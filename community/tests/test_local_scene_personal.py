"""Focused offline personal-map boundaries; no provider or inference calls."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from community.local_scene_packets import canonical,digest
from community.local_scene_personal import (RECEIPT,personal_approval,validate_personal_approval,
    create_queue,queue_zip,sanitized_map,prepare_map)
from community.local_scene_campaign import PERSONAL_CONTRACT,load_manifest,campaign_packet
from community.local_scene_qualification import validate_approval
from community.local_scene_library import SceneLibrary
from community.local_scene_collection import LocalCollection
from community.local_scene_unattended import LocalSceneCampaign
from community.pc_canary import canary_reference
from community.tests.test_local_scene_campaign import DEVICE,approval,profile


def receipt():
    value={**approval(),'contract':RECEIPT,'scope':'LOCAL_PERSONAL_ONLY','productionQualified':False}
    value['sha256']=digest({k:v for k,v in value.items() if k!='sha256'})
    return value


def document(*panos):
    return {'name':'My map','apiKey':'must-not-persist','customCoordinates':[
        {'lat':10+i*.01,'lng':20,'heading':370,'panoId':p,'country':'France',
         'extra':{'tags':['forest'],'secret':'must-not-persist'}} for i,p in enumerate(panos)]}


class PersonalTests(unittest.TestCase):
    def test_saved_records_are_compared_and_personal_receipt_never_grants_owner_authority(self):
        reference,identity=canary_reference();p=profile()
        policy=SimpleNamespace(document={'runtimeProfileSha256':p['sha256']},
            pinned_inputs=lambda:{'referenceBytes':reference},
            evaluate=lambda _p,_i,m:(m['cosine_similarity']['min']>=.9999 and m['relative_l2_error']['max']<=.02,'test'))
        body={'runtimeProfile':p,'records':[base64.b64encode(reference[i:i+3080]).decode()
              for i in range(0,len(reference),3080)],'outputSha256':hashlib.sha256(reference).hexdigest(),**identity}
        report={'status':'COMPLETE','complete':True,'qualified':False,'locations':112,'views':448,
            'inputIdentity':'SEALED_SYNTHETIC_RGB_BYTES','runtimeProfile':p,'identity':identity,
            'payloadSha256':body['outputSha256'],'submission':{'canary':body}}
        value=personal_approval(report,policy,DEVICE,p,1,'a'*64)
        self.assertEqual(value['metrics']['views'],448)
        validate_personal_approval(value,DEVICE,p)
        with self.assertRaises(ValueError):validate_approval(value,DEVICE,p)
        body['records'][0]=base64.b64encode(b'\0'*3080).decode()
        report['payloadSha256']=body['outputSha256']=hashlib.sha256(b''.join(base64.b64decode(r) for r in body['records'])).hexdigest()
        with self.assertRaises(ValueError):personal_approval(report,policy,DEVICE,p,1,'a'*64)

    def test_private_reservations_recover_delivery_and_skip_overlapping_maps(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=document('pano-one','pano-two','pano-one')
            cleaned,duplicates=sanitized_map(source)
            self.assertEqual(duplicates,1);self.assertNotIn('must-not-persist',json.dumps(cleaned))
            with patch('community.local_scene_personal.immutable',side_effect=OSError('synthetic disk')):
                with self.assertRaises(OSError):create_queue(cleaned,root,[receipt()])
            first=create_queue(cleaned,root,[receipt()]);self.assertEqual(first['locations'],2)
            self.assertEqual(create_queue(cleaned,root,[receipt()]),first)
            manifest=load_manifest(first['path']);self.assertEqual(manifest['contract'],PERSONAL_CONTRACT)
            packet=json.loads(campaign_packet(Path(first['path']).parent,manifest,0).read_text())
            self.assertEqual(packet['rows'][0]['line'].split('\t')[4],'10')
            archive=queue_zip(Path(first['path']).parent)
            with zipfile.ZipFile(archive) as saved:
                self.assertEqual(set(saved.namelist()),{'campaign.json','personal-map.json','packets/000000.json'})
                self.assertNotIn(b'must-not-persist',b''.join(saved.read(n) for n in saved.namelist()))
            next_queue=create_queue(document('pano-two','pano-three'),root,[receipt()])
            self.assertEqual((next_queue['locations'],next_queue['duplicatesSkipped']),(1,1))
            # The existing processing engine accepts the private family but still
            # requires the exact device/profile. No native command is started.
            app=LocalSceneCampaign(first['path'],root/'data',root/'runtime',installation_id=DEVICE,
                runtime_verifier=lambda *_a,**_k:(Path('unused'),Path('models'),profile()),
                battery=lambda:False,disk=lambda _:SimpleNamespace(free=10*1024**3))
            self.assertTrue(app.status()['personalOnly']);app.close()
            overlap=create_queue(document('pano-two'),root,[receipt()])
            self.assertIsNone(overlap['path']);self.assertEqual(overlap['existingQueueId'],first['queueId'])
            with patch('community.local_scene_personal.checked_profiles',return_value=[receipt()]):
                prepared=prepare_map(cleaned,root,[root],root/'runtime',DEVICE)
            self.assertEqual(prepared['archivePath'],str(archive))

    def test_collection_deduplicates_scopes_and_preserves_tags_without_mutating_sources(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);community=SceneLibrary(root/'library');personal=SceneLibrary(root/'personal-library',personal=True)
            collection=LocalCollection(community,personal)
            collection.add_map_metadata('a'*64,{'scope':'LOCAL_PERSONAL_ONLY','communitySubmissionAllowed':False,
                'name':'Forest walk','rows':[{'panoId':'pano-one','tags':['forest']}]})
            row={'panoId':'pano-one','lat':10,'lng':20,'heading':0,'pitch':0,'zoom':0,
                 'extra':{'tags':['France'],'visionScore':.8,'visionSourceIndex':0,'visionCameraGeneration':'unknown'}}
            calls=[]
            def search(value,*_a,**_k):
                calls.append(value);return {'indexes':1,'map':{'customCoordinates':[copy.deepcopy(row)]}}
            info={'locations':1,'countries':['France'],'generations':['unknown']}
            with patch.object(community,'status',return_value=info),patch.object(personal,'status',return_value=info),\
                 patch.object(community,'search',side_effect=search),patch.object(personal,'search',side_effect=search):
                result=collection.search({'prompt':'forest','libraryScope':'all'},root)
                self.assertEqual(collection.status()['generations'],[])
                self.assertEqual(len(result['map']['customCoordinates']),1)
                self.assertIn('forest',result['map']['customCoordinates'][0]['extra']['tags'])
                self.assertTrue(all('libraryScope' not in c for c in calls))
                calls.clear();collection.search({'prompt':'forest','libraryScope':'personal'},root)
                self.assertEqual(len(calls),1)
            self.assertEqual(row['extra']['tags'],['France'])


if __name__=='__main__':unittest.main()
