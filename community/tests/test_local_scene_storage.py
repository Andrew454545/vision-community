"""Metadata-only checks for storage identity, existing queues and missing disks."""
import json
from pathlib import Path
import tempfile
import unittest

from community.local_scene_storage import configure_storage, resolve_storage, queue_storage, FOLDER


class StorageTests(unittest.TestCase):
    def test_new_storage_keeps_identity_and_existing_queue(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);app=root/'app';app.mkdir();default=app/'results'
            old,roots=resolve_storage(app,default)
            identity=(old/'installation-id.json').read_bytes()
            key='a'*64;(old/key).mkdir();(old/key/'campaign.json').write_text('{}')
            disk=root/'external';disk.mkdir();configure_storage(app,disk)
            selected,roots=resolve_storage(app,default)
            self.assertEqual(selected,disk/FOLDER)
            self.assertEqual((selected/'installation-id.json').read_bytes(),identity)
            self.assertEqual(queue_storage(app,selected,roots,key),old)
            self.assertEqual(queue_storage(app,selected,roots,'b'*64),selected)
            (old/key).rename(old/'disconnected-queue')
            with self.assertRaisesRegex(ValueError,'saved_queue_storage_missing'):
                queue_storage(app,selected,roots,key)
            self.assertTrue((old/'disconnected-queue/campaign.json').exists())

    def test_foreign_identity_and_missing_drive_never_fall_back(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);app=root/'app';app.mkdir();default=app/'results';resolve_storage(app,default)
            disk=root/'disk';disk.mkdir();foreign=disk/FOLDER;foreign.mkdir()
            path=foreign/'installation-id.json';path.write_text(json.dumps({'id':'f'*64}))
            original=path.read_bytes();configure_storage(app,disk)
            with self.assertRaisesRegex(ValueError,'another_installation'):resolve_storage(app,default)
            self.assertEqual(path.read_bytes(),original)
            disk.rename(root/'unplugged-disk')
            with self.assertRaisesRegex(ValueError,'storage_drive_unavailable'):resolve_storage(app,default)
            self.assertFalse(disk.exists())
