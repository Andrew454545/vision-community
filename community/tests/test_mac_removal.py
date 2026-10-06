"""Saved registration/writer boundaries for application removal, no inference."""
import hashlib
import json
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch

from community.background import single_instance
from community.mac_background import DEFAULT_SETTINGS, MacBackground
from community.mac_remove import prepare_removal
from community.mac_runtime import PYTHON_FOLDER, PYTHON_RELATIVE
from community.mac_starter import copy_source
from community.tests.test_mac_background import Scheduler

REPO = Path(__file__).resolve().parents[2]


class MacRemovalTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.home = self.root / 'home'; self.home.mkdir()
        self.source, _ = copy_source(REPO, self.root)
        python = self.root / PYTHON_FOLDER / PYTHON_RELATIVE
        python.parent.mkdir(parents=True); python.write_bytes(b'regular interpreter path fixture')
        self.scheduler = Scheduler()
        self.platform = patch('sys.platform', 'darwin'); self.platform.start()
        self.addCleanup(self.platform.stop)
        self.manager = MacBackground(self.root, self.source, home=self.home,
            runner=self.scheduler, uid=1001, handover_seconds=0)

    def prepare(self):
        return prepare_removal(self.root, home=self.home, runner=self.scheduler,
                               uid=1001, handover_seconds=0)

    def enable(self):
        self.manager.enable(dict(DEFAULT_SETTINGS), accept=True, code='synthetic saved code')

    def test_owned_idle_removal_and_repeat_keep_work_receipt_and_source(self):
        self.enable()
        keep = ['account.json', 'object/checkpoint.json', 'scene/checkpoint.json',
                'indexes/submissions.sqlite', 'setup-failures/retained.json', 'PAUSE']
        for name in keep[1:]:
            path = self.root / name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'private saved work fixture')
        before = {name:(self.root / name).read_bytes() for name in keep}
        source = {path.relative_to(self.source):path.read_bytes()
                  for path in self.source.rglob('*') if path.is_file()}
        result = self.prepare()
        self.assertEqual(result['status'], 'MAC_REMOVAL_READY')
        self.assertFalse(self.manager.plist.exists())
        self.assertIsNone(self.scheduler.config)
        receipt = self.manager.receipt.read_bytes()
        self.assertTrue(json.loads(receipt)['removed'])
        self.assertEqual(self.prepare(), result)
        self.assertEqual(self.manager.receipt.read_bytes(), receipt)
        self.assertEqual({name:(self.root / name).read_bytes() for name in keep}, before)
        self.assertEqual({path.relative_to(self.source):path.read_bytes()
                          for path in self.source.rglob('*') if path.is_file()}, source)
        self.assertTrue((self.root / 'STOP-AFTER-BATCH').exists())
        self.assertFalse(any('-k' in arguments for arguments in self.scheduler.calls))

    def test_active_writer_is_not_unloaded_and_stop_survives_for_retry(self):
        self.enable(); before = self.manager.plist.read_bytes()
        account = (self.root / 'account.json').read_bytes()
        self.scheduler.calls.clear()
        with single_instance(self.root):
            with self.assertRaisesRegex(ValueError, 'finish_current_batch'):
                self.prepare()
        self.assertEqual(self.manager.plist.read_bytes(), before)
        self.assertEqual((self.root / 'account.json').read_bytes(), account)
        self.assertTrue((self.root / 'STOP-AFTER-BATCH').exists())
        self.assertFalse(any(c[1] == 'bootout' for c in self.scheduler.calls))
        self.assertEqual(self.prepare()['status'], 'MAC_REMOVAL_READY')

    def test_no_registration_still_waits_for_a_guided_writer(self):
        with single_instance(self.root):
            with self.assertRaisesRegex(ValueError, 'finish_current_batch'):
                self.prepare()
        self.assertFalse(self.manager.plist.exists())
        self.assertFalse(self.manager.receipt.exists())
        self.assertEqual(self.prepare()['status'], 'MAC_REMOVAL_READY')

    def test_foreign_loaded_job_or_saved_plist_without_receipt_is_never_stopped(self):
        self.scheduler.config = dict(self.manager.config, WorkingDirectory='unrelated')
        with self.assertRaisesRegex(ValueError, 'unfamiliar'):
            self.prepare()
        self.scheduler.config = None
        self.manager.plist.parent.mkdir(parents=True)
        self.manager.plist.write_bytes(b'foreign plist')
        with self.assertRaisesRegex(ValueError, 'unfamiliar'):
            self.prepare()
        self.assertEqual(self.manager.plist.read_bytes(), b'foreign plist')
        self.assertFalse((self.root / 'STOP-AFTER-BATCH').exists())
        self.assertFalse(any(c[1] == 'bootout' for c in self.scheduler.calls))

    def test_matching_hash_and_loaded_text_cannot_authorize_a_foreign_program(self):
        self.enable()
        config = plistlib.loads(self.manager.plist.read_bytes())
        config['ProgramArguments'][5] = '/different/program'
        body = plistlib.dumps(config)
        self.manager.plist.write_bytes(body); self.scheduler.config = config
        receipt = json.loads(self.manager.receipt.read_bytes())
        receipt['plistSha256'] = hashlib.sha256(body).hexdigest()
        self.manager.receipt.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(ValueError, 'unfamiliar'):
            self.prepare()
        self.assertFalse((self.root / 'STOP-AFTER-BATCH').exists())
        self.assertFalse(any(c[1] == 'bootout' for c in self.scheduler.calls))

    def test_registration_changed_after_verification_refuses_before_handover(self):
        self.enable()
        with self.assertRaisesRegex(ValueError, 'controls_busy'):
            self.manager.remove(expected_plist_sha='0'*64)
        self.assertTrue(self.manager.plist.exists())
        self.assertFalse((self.root / 'STOP-AFTER-BATCH').exists())

    def test_removed_receipt_cannot_hide_reappearing_foreign_job(self):
        self.enable(); self.prepare()
        self.scheduler.config = dict(self.manager.config)
        with self.assertRaisesRegex(ValueError, 'unfamiliar'):
            self.prepare()
        self.assertIsNotNone(self.scheduler.config)

    def test_absent_worker_does_not_create_private_folder_or_account(self):
        missing = self.root / 'never-used'
        result = prepare_removal(missing, home=self.home, runner=self.scheduler, uid=1001)
        self.assertEqual(result['status'], 'MAC_REMOVAL_READY')
        self.assertFalse(missing.exists())
        self.assertTrue(all(c[1] == 'print' for c in self.scheduler.calls))


if __name__ == '__main__':
    unittest.main()
