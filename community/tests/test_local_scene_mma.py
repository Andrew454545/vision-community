"""Fake-provider check: memory-only keys and no replay of uncertain writes."""
from pathlib import Path
import tempfile
import unittest

from community.local_scene_mma import MMAConnection


class MMATests(unittest.TestCase):
    def test_explicit_target_key_privacy_and_ambiguous_delivery(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);calls=[];fail=[False]
            def transport(path,key,*,method='GET',body=None):
                calls.append((path,method))
                if method=='GET':return [{'id':'my-map','name':'Private test map'}]
                if fail[0]:raise TimeoutError('synthetic ambiguous provider response')
                return {}
            connection=MMAConnection(root,transport=transport);key='private-key-never-on-disk'
            self.assertTrue(connection.connect(key)['connected'])
            document={'name':'Private results','customCoordinates':[{'lat':10,'lng':20,'panoId':'test-pano','heading':123,'pitch':-2,'zoom':1}]}
            with self.assertRaisesRegex(ValueError,'select_connected'):connection.send('other-map',document)
            self.assertEqual(connection.send('my-map',document)['added'],1)
            self.assertTrue(connection.send('my-map',document)['alreadySent'])
            self.assertEqual(sum(method=='POST' for _,method in calls),1)
            changed={**document,'name':'Different export'};fail[0]=True
            for _ in range(2):
                with self.assertRaisesRegex(ValueError,'needs_check'):connection.send('my-map',changed)
            self.assertEqual(sum(method=='POST' for _,method in calls),2)
            self.assertNotIn(key,str(connection.status()))
            self.assertFalse(any(key.encode() in p.read_bytes() for p in root.rglob('*') if p.is_file()))
            connection.disconnect();self.assertFalse(connection.status()['connected'])
