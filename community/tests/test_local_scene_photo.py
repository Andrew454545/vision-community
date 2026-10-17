"""One offline boundary check for photo pixels, native cache and image/text mixing."""
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest

from community.local_scene_photo import prepare_profile, RGB_BYTES, MODEL_NAMES
from community.local_scene_packets import canonical
from community.vision_index import file_identity, search_input


class PhotoTests(unittest.TestCase):
    def test_sealed_local_pixels_mix_with_text_without_a_network_example(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);models=root/'models';models.mkdir();job=root/'job';job.mkdir()
            for name in MODEL_NAMES:(models/name).write_bytes(b'synthetic-model')
            profile={'profile':{'assets':{'models/'+name:file_identity(models/name)['sha256'] for name in MODEL_NAMES}}}
            query=search_input('a road',description_weight=100)
            query['queries'][0]['mode']='title50Contrastive50'
            def native(command,work):
                self.assertIn('--sealed-rgb',command);self.assertNotIn('--capture-rgb',command)
                spec=json.loads((work/'input.json').read_text())
                self.assertEqual(spec['queries'][0]['examples'],[])
                frozen=json.loads((work/'pixels/manifest.json').read_text())
                self.assertFalse(frozen['productionQualified']);self.assertEqual(len(frozen['frames']),4)
                (work/'evidence').mkdir();(work/'index').mkdir()
                tensor=work/'evidence/scene-0000-view-0-normalized.f32le'
                tensor.write_bytes(struct.pack('<768f',1,*([0]*767)))
                record={'ordinal':0,'view':0,'event':'normalized','shape':[768],
                    'file':{'name':tensor.name,**file_identity(tensor)}}
                (work/'evidence/scene-evidence.json').write_bytes(canonical({
                    'status':'NATIVE_SCENE_STUDY_COMPLETED_UNQUALIFIED','productionQualified':False,
                    'selectedImageGraph':'vision_model_fp32.onnx','modelFiles':frozen['modelFiles'],
                    'frames':frozen['frames'],'tensors':[record]}))
                (work/'index/query-profiles.json').write_bytes(canonical({'profiles':[{'vector':[0,1]+[0]*766}]}))
            report=prepare_profile(bytes([123])*RGB_BYTES,job,Path('unused-native'),models,profile,query,weight=50,runner=native)
            self.assertTrue(report['queryOnly']);self.assertEqual(report['liveImageryRequests'],0)
            cached=json.loads((job/'profiles/query-profiles.json').read_text())['profiles'][0]
            self.assertAlmostEqual(cached['vector'][0],2**-.5,places=6)
            self.assertAlmostEqual(cached['vector'][1],2**-.5,places=6)
            self.assertEqual(cached['excludedPanoIds'],[])
            self.assertEqual(query['queries'][0]['examples'],[])
            with self.assertRaisesRegex(ValueError,'invalid_photo_pixels'):
                prepare_profile(b'too short',job,Path('unused'),models,profile,query,runner=native)
            query['queries'][0]['examples']=[{'panoId':'never-fetch'}]
            with self.assertRaisesRegex(ValueError,'offline'):
                prepare_profile(bytes(RGB_BYTES),job,Path('unused'),models,profile,query,runner=native)
