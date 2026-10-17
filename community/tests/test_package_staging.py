"""Public-only native packaging and immutable source guard checks."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

REPO=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO/'packaging'))
from stage import archive, inventory, source_state, stage
from build_mac import build as build_mac


class PackageStagingTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name).resolve()

    def test_complete_public_payload_excludes_checkout_accounts_and_machine_files(self):
        for platform in ('mac','windows'):
            destination=self.root/platform
            digest=stage(destination,platform,'a'*40)
            manifest=json.loads((destination/'release-inventory.json').read_bytes())
            self.assertEqual(digest,hashlib.sha256((destination/'release-inventory.json').read_bytes()).hexdigest())
            self.assertIn('community/work_plan.py',manifest['files'])
            self.assertIn('community/object_index.py',manifest['files'])
            self.assertIn('community/object_features.py',manifest['files'])
            self.assertFalse(any(part in name for name in manifest['files'] for part in ('.git/','account.json','private','node_modules','__pycache__')))
            for name,pin in manifest['files'].items():
                self.assertEqual(pin['sha256'],hashlib.sha256((destination/name).read_bytes()).hexdigest())
            output=self.root/(platform+'.zip');archive(destination,output)
            with zipfile.ZipFile(output) as package:
                self.assertEqual(set(package.namelist()),set(manifest['files'])|{'release-inventory.json'})
            with self.assertRaises(ValueError):stage(destination,platform,'a'*40)

    def test_staging_refuses_linked_output_and_invalid_revision_before_writing(self):
        link = self.root / 'linked'
        linked_supported = True
        try:
            link.symlink_to(self.root, target_is_directory=True)
        except OSError as error:
            if os.name != 'nt' or getattr(error, 'winerror', None) != 1314:
                raise
            # A Windows junction exercises the same reparse-point refusal
            # without enabling Developer Mode or changing a security policy.
            temporary = Path(tempfile.gettempdir()).resolve()
            self.root.relative_to(temporary)
            self.assertEqual(link.parent, self.root)
            quote = lambda value: "'" + str(value).replace("'", "''") + "'"
            command = ("$ErrorActionPreference='Stop'; New-Item -ItemType Junction -Path "
                       + quote(link) + " -Target " + quote(self.root) + " | Out-Null")
            powershell = os.environ.get('VISION_TEST_POWERSHELL') or 'powershell.exe'
            try:
                subprocess.run([powershell, '-NoProfile', '-NonInteractive', '-Command', command],
                               check=True, capture_output=True, text=True, timeout=30)
            except subprocess.CalledProcessError as junction_error:
                if os.name != 'nt':
                    raise
                linked_supported = False
            else:
                self.assertTrue(link.lstat().st_file_attributes & 0x400)
        if linked_supported:
            with self.assertRaises(ValueError):
                stage(self.root/'linked'/'out','mac','a'*40)
            self.assertFalse((self.root/'out').exists())
        for target,revision in ((self.root/'out','not-a-revision'),):
            with self.assertRaises(ValueError):stage(target,'mac',revision)
            self.assertFalse((self.root/'out').exists())

    def test_public_signing_refuses_dirty_source_wrong_revision_and_incomplete_credentials(self):
        with patch('stage.subprocess.check_output',side_effect=['a'*40+'\n',' M public.py\n']):
            with self.assertRaisesRegex(ValueError,'clean_source'):source_state('a'*40,signing=True)
        with patch('stage.subprocess.check_output',return_value='b'*40+'\n'):
            with self.assertRaisesRegex(ValueError,'match_checkout'):source_state('a'*40)
        for identity,profile in (('-', 'profile'),('Developer ID Application: fixture',None),(None,'profile')):
            with self.assertRaises(ValueError):build_mac(self.root/'never-created','a'*40,identity,profile)
            self.assertFalse((self.root/'never-created').exists())


if __name__=='__main__':unittest.main()
