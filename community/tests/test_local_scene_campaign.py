"""Offline approval, exclusive bulk allocation and unattended recovery contracts."""
import base64
from contextlib import nullcontext
import copy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
import zipfile
from unittest.mock import patch

from community.local_scene_packets import canonical, digest, prepare_catalog, allocate_packet, connection
from community.local_scene_campaign import (allocate_campaign, import_exclusions, load_manifest,
                                             campaign_packet, validate_manifest)
from community.local_scene_qualification import BOUNDS, approve, validate_approval
from community.local_scene_unattended import LocalSceneCampaign
from community.pc_canary import canary_reference
from community.tests.test_local_scene_pilot import catalog

DEVICE = 'd' * 64


def profile(threads=1):
    value = {'threads': {'VISION_ORT_THREADS': str(threads)}, 'synthetic': True}
    return {'sha256': digest(value), 'profile': value}


def approval(threads=1):
    value = {'contract': 'vision-local-scene-approval-v1', 'installationId': DEVICE,
             'runtimeProfile': profile(threads), 'inferenceThreads': threads,
             'bounds': BOUNDS, 'locations': 112, 'views': 448, 'scope': 'LOCAL_PROCESSING_ONLY',
             'metrics': {'cosine_similarity': {'min': 1}, 'relative_l2_error': {'max': 0}}}
    return {**value, 'sha256': digest(value)}


def excluded(root, registry, ids=()):
    p = root / 'excluded.txt'; p.write_text(''.join(i + '\n' for i in ids))
    authority = {'contract': 'vision-local-scene-exclusions-v1', 'complete': True,
        'ownerIndexed': 'synthetic', 'ownerReserved': 'synthetic', 'communityProduction': 'synthetic',
        'communityStaging': 'synthetic', 'cutoff': 'test-cutoff', 'rows': len(ids),
        'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
    with connection(registry) as db:
        authority['sources']=[r[0] for r in db.execute('SELECT sha FROM catalogs')]
    import_exclusions(registry, p, authority)


class CampaignTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.registry = self.root / 'issuer.sqlite'
        prepare_catalog(catalog(self.root, 400), self.registry)

    def assign(self, name='one', count=129, approvals=None, out=None):
        return allocate_campaign(self.registry, name, count, name, approvals or [approval()],
                                 out or self.root / name)

    def test_missing_complete_history_and_baseline_approval_stop_before_reservation(self):
        with self.assertRaisesRegex(ValueError, 'complete_exclusion'):
            self.assign()
        excluded(self.root, self.registry)
        with self.assertRaisesRegex(ValueError, 'approval_profiles'):
            self.assign(approvals=[approval(2)])

    def test_campaign_and_legacy_packets_share_exclusions_and_unique_reservations(self):
        excluded(self.root, self.registry, ['pano-0000', 'pano-0001'])
        first = self.assign()
        self.assertEqual([p['locations'] for p in first['packets']], [128, 1])
        rows = [row['line'].split('\t')[7] for i in range(2)
                for row in json.loads(campaign_packet(self.root/'one', first, i).read_text())['rows']]
        second = allocate_packet(self.registry, 'other', 5, 'old-client', self.root/'other.json')
        self.assertEqual(len(set(rows)), 129)
        self.assertNotIn('pano-0000', rows)
        self.assertFalse(set(rows) & {r['line'].split('\t')[7] for r in second['rows']})
        self.assertEqual(self.assign(), first)

    def test_failed_delivery_can_be_reexported_and_does_not_release_work(self):
        excluded(self.root, self.registry)
        with patch('community.local_scene_campaign.export_packet', side_effect=OSError('synthetic disk')):
            with self.assertRaises(OSError): self.assign()
        recovered = self.assign(out=self.root/'recovered')
        next_work = self.assign(name='two')
        self.assertTrue({e['packetId'] for e in recovered['packets']}.isdisjoint(
                        {e['packetId'] for e in next_work['packets']}))

    def test_short_inventory_rolls_back_every_partial_reservation(self):
        excluded(self.root, self.registry)
        with self.assertRaisesRegex(ValueError, 'not_enough'):
            self.assign(count=500)
        self.assertEqual(self.assign(count=400)['locations'], 400)

    def test_manifest_paths_duplicate_packets_and_changed_payloads_fail(self):
        excluded(self.root, self.registry); manifest = self.assign()
        for change in ('path', 'duplicate'):
            value = copy.deepcopy(manifest)
            if change == 'path': value['packets'][0]['path'] = '../private'
            else: value['packets'][1]['packetId'] = value['packets'][0]['packetId']
            value['sha256'] = digest({k:v for k,v in value.items() if k != 'sha256'})
            with self.assertRaises(ValueError): validate_manifest(value)
        path = self.root/'one/packets/000000.json'; path.write_text(path.read_text().replace('France','Spain'))
        with self.assertRaisesRegex(ValueError, 'changed'):
            campaign_packet(self.root/'one', manifest, 0)

    def test_five_million_manifest_is_bounded_without_loading_location_rows(self):
        value = {'contract': 'vision-local-scene-campaign-v1', 'campaignId':'capacity',
                 'participant':'synthetic', 'locations':5_000_000, 'packets':[],
                 'exclusionAuthoritySha256':'e'*64, 'approvals':[approval()]}
        for i, start in enumerate(range(0, 5_000_000, 128)):
            value['packets'].append({'path':f'packets/{i:06d}.json', 'sha256':digest(i),
                                    'packetId':digest(['packet',i]), 'locations':min(128,5_000_000-start)})
        value['sha256'] = digest(value)
        path=self.root/'capacity.json'; path.write_bytes(canonical(value))
        self.assertLess(path.stat().st_size,16*1024*1024)
        self.assertEqual(load_manifest(path)['locations'],5_000_000)


class QualificationTests(unittest.TestCase):
    def test_owner_recomputes_records_ignoring_client_pass_and_summary(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); reference,identity=canary_reference()
            p=profile(); policy=SimpleNamespace(document={'referenceSha256':identity['referenceSha256'],
                'runtimeProfileSha256':p['sha256']},pinned_inputs=lambda:{'referenceBytes':reference},
                evaluate=lambda _profile,_identity,m:(m['cosine_similarity']['min']>=.9999 and
                                                      m['relative_l2_error']['max']<=.02,'test'))
            body={'runtimeProfile':p,'records':[base64.b64encode(reference[i:i+3080]).decode()
                  for i in range(0,len(reference),3080)],'outputSha256':hashlib.sha256(reference).hexdigest(),**identity}
            report={'status':'COMPLETE','complete':True,'qualified':False,'locations':112,'views':448,
                    'inputIdentity':'SEALED_SYNTHETIC_RGB_BYTES','runtimeProfile':p,'identity':identity,
                    'payloadSha256':body['outputSha256'],'submission':{'canary':body}}
            gold={'contract':'vision-local-gold-correspondence-v1','verified':True,
                  'verificationScope':'INSTALLED_INDEX_CONSUMER','referenceRegeneratedByInstalledBinary':False,
                  'locations':112,'queries':3,
                  'referenceSha256':identity['referenceSha256'],'localVisionBinarySha256':'b'*64,'evidenceSha256':'e'*64}
            (root/'report.json').write_bytes(canonical(report)); (root/'gold.json').write_bytes(canonical(gold))
            with patch('community.local_scene_qualification.fixed_policy',return_value=policy):
                result=approve(root/'report.json',root/'policy','c'*64,root/'gold.json',DEVICE)
                self.assertEqual(result['metrics']['views'],448)
                validate_approval(result,DEVICE,p)
                report['submission']['canary']['records'][0]=base64.b64encode(b'\0'*3080).decode()
                (root/'report.json').write_bytes(canonical(report))
                with self.assertRaisesRegex(ValueError,'output_changed'):
                    approve(root/'report.json',root/'policy','c'*64,root/'gold.json',DEVICE)
                gold['verified']=False;(root/'gold.json').write_bytes(canonical(gold))
                with self.assertRaisesRegex(ValueError,'gold_correspondence'):
                    approve(root/'report.json',root/'policy','c'*64,root/'gold.json',DEVICE)

    def test_thresholds_device_profile_and_receipt_changes_invalidate_approval(self):
        for changed in ({'installationId':'f'*64},{'views':447},
                        {'metrics':{'cosine_similarity':{'min':.99989},'relative_l2_error':{'max':0}}},
                        {'metrics':{'cosine_similarity':{'min':1},'relative_l2_error':{'max':.02001}}}):
            value={**approval(),**changed};value['sha256']=digest({k:v for k,v in value.items() if k!='sha256'})
            with self.assertRaises(ValueError):validate_approval(value,DEVICE,profile())


class UnattendedTests(unittest.TestCase):
    def make(self, root, count=3, **kw):
        registry=root/'issuer.sqlite';prepare_catalog(catalog(root,count),registry);excluded(root,registry)
        allocate_campaign(registry,'one',count,'one',[approval(),approval(2)],root/'assigned')
        def verify(_root, *, inference_threads=1):return Path('test'),Path('models'),profile(inference_threads)
        return LocalSceneCampaign(root/'assigned/campaign.json',root/'data',root/'runtime',
            installation_id=DEVICE,runtime_verifier=verify,battery=lambda:False,
            disk=lambda _p:SimpleNamespace(free=10*1024**3),**kw)

    def test_explicit_pause_survives_reopen_and_schedule_changes_are_persisted(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);app=self.make(root)
            app.configure({'dayPace':'slow','nightPace':'max','dayStart':'07:00','nightStart':'23:00'})
            app.pause();self.assertFalse(app.settings['enabled'])
            self.assertEqual(json.loads(app.settings_path.read_text())['dayStart'],'07:00')
            app.resume_automatically();self.assertIsNone(app.thread)

    def test_owned_queue_survives_removal_of_the_downloaded_original(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);app=self.make(root)
            self.assertEqual(app.path,app.root/'campaign.json')
            (root/'assigned').rename(root/'moved-download')
            self.assertTrue(campaign_packet(app.path.parent,app.manifest,0).is_file())
            reopened=LocalSceneCampaign(app.path,root/'data',root/'runtime',installation_id=DEVICE,
                runtime_verifier=lambda _root,*,inference_threads=1:(Path('test'),Path('models'),profile(inference_threads)))
            self.assertEqual(reopened.path,app.path)

    def test_low_disk_preserves_resume_intent_and_does_not_start_native(self):
        with tempfile.TemporaryDirectory() as folder:
            app=self.make(Path(folder),pilot_factory=lambda *a,**k:self.fail('native must not start'))
            app.disk=lambda _p:SimpleNamespace(free=0)
            app.start();app.thread.join(5)
            self.assertEqual(app.phase,'low_disk');self.assertTrue(app.settings['enabled'])
            app.close()

    def test_full_campaign_uses_checked_night_threads_and_once_only_progress(self):
        with tempfile.TemporaryDirectory() as folder:
            calls=[]
            class Pilot:
                def __init__(self,*args,**kwargs):calls.append(kwargs['inference_threads'])
                def start(self):
                    import threading
                    self.thread=threading.Thread(target=lambda:None);self.thread.start()
                def close(self):self.thread.join()
                def pause(self):pass
                def status(self):return {'phase':'complete'}
            app=self.make(Path(folder),pilot_factory=Pilot,clock=lambda:datetime(2026,10,15,1))
            app.start();app.thread.join(5)
            self.assertEqual(app.status()['completed'],3);self.assertEqual(calls,[2])
            app.start();app.thread.join(5)
            self.assertEqual(app.status()['completed'],3);self.assertEqual(calls,[2])

    def test_real_local_indexer_shape_campaign_export_and_current_settings(self):
        from community.local_scene_pilot import LocalScenePilot
        from community.vision_index import index_locations_tsv
        from community.tests.test_vision_index import fake_runner
        class Pilot(LocalScenePilot):
            def __init__(self,*args,**kwargs):
                def indexer(tsv,**options):
                    options['runner']=fake_runner
                    return index_locations_tsv(tsv,**options)
                super().__init__(*args,indexer=indexer,**kwargs)
        with tempfile.TemporaryDirectory() as folder:
            app=self.make(Path(folder),count=129,pilot_factory=Pilot,clock=lambda:datetime(2026,10,15,12))
            with patch('community.background.keep_awake',return_value=nullcontext()):
                app.start();app.thread.join(5)
            self.assertEqual(app.phase,'complete',app.status())
            result=app.export_results()
            self.assertEqual(result['locations'],129)
            self.assertEqual(result['archives'],2)
            self.assertEqual(result['kind'],'local_directory')
            self.assertEqual(app.status()['completed'],129)
            self.assertEqual(app.export_results(),result)
            self.assertEqual(len(list(Path(result['path']).glob('*.zip'))),2)

    def test_battery_wait_can_be_explicitly_paused_without_launching_native(self):
        import threading
        with tempfile.TemporaryDirectory() as folder:
            app=self.make(Path(folder),pilot_factory=lambda *a,**k:self.fail('native on battery'))
            observed=threading.Event()
            def battery(): observed.set(); return True
            app.battery=battery
            app.start();self.assertTrue(observed.wait(3));app.pause();app.close()
            self.assertEqual(app.phase,'paused');self.assertFalse(app.settings['enabled'])

    def test_saved_retry_wait_and_held_groups_can_be_retried_explicitly(self):
        with tempfile.TemporaryDirectory() as folder:
            app=self.make(Path(folder))
            with app._db() as db:
                db.execute('UPDATE work SET failures=5,status="held",retry=?',(time.time()+9999,))
            app.disk=lambda _p:SimpleNamespace(free=0)
            app.start();app.thread.join(3)
            with app._db() as db:
                self.assertEqual(db.execute('SELECT status,failures,retry FROM work').fetchone(),('pending',0,0))
            self.assertEqual(app.phase,'low_disk')

    def test_startup_commands_are_scoped_and_watchdog_does_not_restart_normal_exit(self):
        from community.local_scene_startup import startup_config
        from community.local_scene_supervisor import supervise
        with tempfile.TemporaryDirectory() as folder:
            app=self.make(Path(folder));label,args=startup_config(app)
            self.assertTrue(label.startswith('org.visioncommunity.local-scenes.'))
            self.assertIn('--resume',args);self.assertIn(str(app.path),args)
            self.assertFalse(any('post-badcam' in a for a in args))
        sleeps=[];results=iter([SimpleNamespace(returncode=1),SimpleNamespace(returncode=1),SimpleNamespace(returncode=0)])
        self.assertEqual(supervise(['owned-child'],run=lambda *a,**k:next(results),sleep=sleeps.append),0)
        self.assertEqual(sleeps,[60,120])


if __name__=='__main__':unittest.main()
