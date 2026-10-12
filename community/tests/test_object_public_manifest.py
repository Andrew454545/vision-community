"""Public metadata parity, using synthetic records and the existing Node runtime."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from community.object_snapshot import public_manifest
from community.process_owner import run_owned
from community.search_snapshot import SnapshotError

REPO = Path(__file__).resolve().parents[2]


class ObjectPublicManifestParityTests(unittest.TestCase):
    def test_public_projection_and_quality_decisions_match_offline_snapshot(self):
        node = os.environ.get('VISION_TEST_NODE') or shutil.which('node')
        if not node:
            self.skipTest('existing private Node runtime not supplied')
        document = json.loads((REPO/'community/tests/fixtures/object-feature-content-v1.json').read_text(encoding='utf-8'))
        baseline = copy.deepcopy(document['baseline']['manifest'])
        baseline['viewQuality'].update(policy='vision-per-view-quality-v1', implementationIdentity='1'*64,
            viewCount=6, blurAreaFractionExclusive=0.5, tileGrid=8, tunnelVisionProbabilityInclusive=0.85,
            tunnelEvidencePolicy='none-darkness-never-rejects-v1', protectedAuthorityManifestSha256='2'*64)
        inputs = [baseline]
        private = copy.deepcopy(baseline)
        private['sourceTsv'] = 'C:/SYNTHETIC-PRIVATE/source.tsv'
        private['privateExtension'] = {'account': 'SYNTHETIC-PRIVATE'}
        private['contractVersions']['private'] = 'SYNTHETIC-PRIVATE'
        for key in ('offsets','metadata','globalIds','semantic','viewQuality'):
            private[key]['privateExtension'] = {'path': 'SYNTHETIC-PRIVATE'}
        for row in private['classes'] + private['hotConcepts']:
            row['privateExtension'] = {'account': 'SYNTHETIC-PRIVATE'}
        inputs.append(private)
        for changes in ({'policy':'old'}, {'implementationIdentity':''}, {'protectedAuthorityManifestSha256':None},
                {'viewCount':5}, {'blurAreaFractionExclusive':0.51}, {'tileGrid':2},
                {'tunnelVisionProbabilityInclusive':0.8}, {'tunnelEvidencePolicy':'none-darkness-kept-v1'},
                {'darkTunnelRejectedViews':1,'keptViews':11}, {'keptViews':13}, {'keptViews':True},
                {'fullyRejectedLocations':3}, {'tunnelEvidenceQualifiedViews':1},
                {'tunnelEvidenceManifestSha256':'3'*64}, {'permanentlyInvalidLocations':None},
                {'invalidLocationPolicy':'old'}, {'tunnelEvidenceVisualScoreRecords':0.5}):
            changed = copy.deepcopy(baseline)
            changed['viewQuality'].update(changes)
            inputs.append(changed)
        for key,value in (('frozenViewsManifestSha256',None),('version',{}),('fetchErrors',True),
                ('inferenceErrors',-1),('countries',['x'*101]),('countries',['country\nprivate']),
                ('classes',[None]),('metadata',None),('viewQuality',{}),('viewQuality',None)):
            changed = copy.deepcopy(baseline)
            changed[key] = value
            inputs.append(changed)
        sealed = copy.deepcopy(baseline)
        sealed['viewQuality'].update(tunnelEvidencePolicy='sealed-external-map-plus-tunnel-vision-exact-pano-coordinate-v1',
            tunnelEvidenceManifestSha256='3'*64, tunnelEvidenceQualifiedViews=1, tunnelEvidenceMapMatchRecords=1,
            tunnelEvidenceVisualScoreRecords=1, darkTunnelRejectedViews=1, keptViews=11)
        inputs.append(sealed)
        missing = copy.deepcopy(sealed)
        del missing['viewQuality']['tunnelEvidenceMapMatchRecords']
        inputs.append(missing)
        unicode = copy.deepcopy(baseline)
        unicode['countries'] = ['\U0001f30d'*100]
        inputs.append(unicode)
        expected = []
        for value in inputs:
            try:
                expected.append({'valid':True,'manifest':public_manifest(value)})
            except SnapshotError:
                expected.append({'valid':False})
        script = ("import {readFileSync} from 'node:fs'; import {publicObjectManifest} from "
            + json.dumps((REPO/'deploy/cloudflare/src/objectPublicManifest.js').as_uri()) + ";"
            "const values=JSON.parse(readFileSync(process.argv[1],'utf8'));console.log(JSON.stringify(values.map(value=>{"
            "try{return {valid:true,manifest:publicObjectManifest(value)};}catch{return {valid:false};}})));")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source,stdout,stderr = (root/name for name in ('input.json','stdout.log','stderr.log'))
            source.write_text(json.dumps(inputs,ensure_ascii=False,allow_nan=False),encoding='utf-8')
            with stdout.open('xb') as outgoing,stderr.open('xb') as errors:
                result = run_owned([node,'--input-type=module','--eval',script,str(source)],cwd=REPO,
                    env=dict(os.environ),stdout=outgoing,stderr=errors,timeout=30,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            self.assertEqual(result.returncode,0,stderr.read_text(encoding='utf-8'))
            actual = json.loads(stdout.read_text(encoding='utf-8'))
        self.assertEqual(len(actual),32)
        for index,(wanted,received) in enumerate(zip(expected,actual)):
            with self.subTest(case=index):
                self.assertEqual(received,wanted)
                if received['valid']:
                    self.assertNotIn('SYNTHETIC-PRIVATE',json.dumps(received))


if __name__ == '__main__':
    unittest.main()
