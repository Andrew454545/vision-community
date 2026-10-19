"""Offline transport evidence, numerical input preservation and cancellable waits."""
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from community.local_scene_pilot import LocalScenePilot
from community.local_scene_transport import prepare_command, validate_execution
from community.vision_index import four_view_input, VisionIndexError


class TransportTests(unittest.TestCase):
    def test_actual_serial_input_is_bound_and_wait_is_interruptible_without_requests(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);spec=four_view_input(total=16,pace='max',run_id='synthetic')
            source=root/'input.json';source.write_text(json.dumps(spec))
            before=source.read_bytes()
            argv=['unused-native','index-four-views','--input',str(source)]
            command,record=prepare_command(argv)
            actual=json.loads(Path(command[3]).read_text())
            self.assertEqual(actual,{**spec,'concurrency':1});self.assertEqual(source.read_bytes(),before)
            validate_execution(record,source)
            changed=json.loads(json.dumps(record));changed['nativeInput']['embeddingBatchSize']=8
            with self.assertRaisesRegex(ValueError,'changed'):validate_execution(changed,source)
            study,metadata=prepare_command(['native','study-four-views','--input',str(source)])
            self.assertIsNone(metadata);self.assertEqual(study[-1],str(source))
            waits=[];cancel=[False]
            stop=SimpleNamespace(wait=lambda delay:(waits.append(delay) or cancel[0]))
            pilot=SimpleNamespace(pace='medium',stop=stop,_last_network_end=time.monotonic())
            with patch('community.local_scene_pilot.run_owned',return_value=SimpleNamespace(returncode=0)) as native:
                self.assertEqual(LocalScenePilot._runner(pilot,argv,{},root)[0],0)
                self.assertEqual(native.call_count,1);self.assertTrue(29<waits[0]<=30)
                self.assertEqual(pilot.network_execution['maximumConcurrentDownloads'],1)
                cancel[0]=True
                with self.assertRaises(VisionIndexError):LocalScenePilot._runner(pilot,argv,{},root)
                self.assertEqual(native.call_count,1)
