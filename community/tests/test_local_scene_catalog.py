"""Synthetic additive publication, exact prefix, backup and writer guards."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from community import local_scene_catalog as catalog
from community.local_scene_library import SceneLibrary
from community.local_scene_packets import canonical
from community.tests.test_vision_index import sample_record
from community.vision_index import file_identity


class CatalogTests(unittest.TestCase):
    def test_prepare_and_additive_apply_keep_originals_and_require_paused_writers(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);library=SceneLibrary(root/'library')
            original=library.root/'imports'/('a'*64)
            attempt=original/'part-0000/attempt-0001';attempt.mkdir(parents=True)
            (original/'import-receipt.json').write_bytes(canonical({'contract':'vision-local-scene-import-v1',
                'archiveSha256':original.name,'scope':'QUALIFIED_DEVICE_OUTPUT_NOT_RECOMPUTED'}))
            with library._db() as db:db.execute('INSERT INTO sources VALUES(?,?,?)',('synthetic',str(attempt),'{}'))
            model=root/'models';model.mkdir();(model/'weight').write_bytes(b'synthetic-canonical-weight')
            runtime=root/'runtime.json';runtime.write_bytes(canonical({'files':[{'path':'models/weight',**file_identity(model/'weight')}]}))
            segment=root/'segment';(segment/'index').mkdir(parents=True)
            (segment/'locations.tsv').write_bytes(b'map\t0\t10\t20\t0\t0\t0\tpano-0000\tFrance\tgen4\tfalse\n')
            (segment/'index/shard-000000.i8').write_bytes(sample_record(1))
            (segment/'index/shard-000000.mask').write_bytes(b'\x0f')
            (segment/'index/manifest.json').write_bytes(canonical({'version':4,'totalLocations':1,'sourceBytes':(segment/'locations.tsv').stat().st_size}))
            base={'version':2,'sources':[{'id':'personal','processedLocations':100,'metadata':'preserve'}],'unrelated':True}
            base_path=root/'base.json';before=canonical(base)+b'\n';base_path.write_bytes(before)
            output=root/'published'
            with patch.object(catalog,'MANIFEST',runtime),patch.object(library,'_segments',return_value=([segment],1)):
                plan=catalog.prepare_catalog(library,model,base_path,hashlib.sha256(before).hexdigest(),output)
            self.assertEqual(base_path.read_bytes(),before)
            after=json.loads((output/'catalog.next.json').read_text())
            self.assertEqual(after['sources'][0],base['sources'][0]);self.assertTrue(after['unrelated'])
            self.assertEqual(after['processedLocations'],101)
            source=after['sources'][1]
            self.assertEqual((Path(source['indexDir'])/'shard-000000.i8').read_bytes(),sample_record(1))
            self.assertEqual(catalog.merge_catalog(after,[source],source['communityLibraryId']),after)
            smaller={**source,'processedLocations':0}
            with self.assertRaisesRegex(ValueError,'source_conflict'):catalog.merge_catalog(after,[smaller],source['communityLibraryId'])
            with self.assertRaisesRegex(ValueError,'pause_owner'):catalog.apply_catalog(plan,output)
            catalog.apply_catalog(plan,output,writers_paused=True)
            self.assertEqual((output/'catalog.before.json').read_bytes(),before)
            with self.assertRaisesRegex(ValueError,'catalog_changed'):catalog.apply_catalog(plan,output,writers_paused=True)
