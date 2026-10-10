"""Real finite exporter protocol with tiny synthetic bytes; no Arrow or cloud."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

TOOL=Path(__file__).resolve().parents[2]/'deploy/cloudflare/tools/pool-publish.py'
EXPORTER='''import json,sys
from pathlib import Path
out=Path(sys.argv[4]);out.mkdir();name='shard-000000.tsv';(out/name).write_bytes(b'synthetic metadata\\n')
print(json.dumps(dict(file=name,shard=0,rows=1,totalRows=1)),flush=True)
assert sys.stdin.readline().strip()=='VERIFIED '+name
print(json.dumps(dict(done=True,totalRows=1,sourceRows=1,shards=1)),flush=True)
'''


class PoolPublisherGuards(unittest.TestCase):
    def exercise(self,change=None,at_manifest=False):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source';source.write_bytes(b'sealed synthetic source')
            mask=root/'mask';mask.write_bytes(b'\x01')
            authority=root/'authority';authority.write_text(json.dumps(dict(sourceRows=1,malformedInputIds=0,
                identityComparison='complete-22-byte-panorama-id',eligibleUnique=1,maskSha256=hashlib.sha256(mask.read_bytes()).hexdigest())))
            countries=root/'countries';countries.write_text('1\tCanada\n')
            exporter=root/'export.py';exporter.write_text(EXPORTER)
            selected=dict(mask=mask,authority=authority,countries=countries,exporter=exporter,source=source).get(change)
            adapter=root/'adapter.py'
            adapter.write_text('from pathlib import Path\nstore={}\n'
                'def put(key,data):\n    store[key]=data\n'+
                (f'    if key.endswith({"manifest.json" if at_manifest else "shard-000000.tsv"!r}): Path({str(selected)!r}).write_bytes(b"changed")\n' if selected else '')+
                'def get(key): return store[key]\n')
            args=SimpleNamespace(output=root/'publication',source=source,source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                source_rows=1,identity_report=authority,adapter=adapter,mask=mask,countries=countries,exporter=exporter,
                prefix='catalog/offline-protocol-fixture',shard_id_start=-100000)
            spec=importlib.util.spec_from_file_location('publisher_guard_fixture',TOOL)
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            original=subprocess.Popen
            def launch(argv,**kwargs):return original([sys.executable,*argv],**kwargs)
            with patch.object(module.subprocess,'Popen',side_effect=launch):
                if change:
                    with self.assertRaisesRegex(RuntimeError,'Publication input changed|Source changed'):
                        module.publish(args)
                    self.assertFalse((args.output/'complete.private.json').exists())
                    self.assertTrue((args.output/'verified-shards.private.jsonl').exists())
                else:
                    module.publish(args)
                    self.assertEqual(json.loads((args.output/'complete.private.json').read_bytes())['totalRows'],1)

    def test_unchanged_protocol_completes(self):self.exercise()
    def test_every_sealed_input_is_rechecked_before_manifest(self):
        for change in ('mask','authority','countries','exporter','source'):
            with self.subTest(change=change):self.exercise(change)
    def test_input_change_during_final_remote_call_cannot_create_completion(self):
        self.exercise('countries',at_manifest=True)
