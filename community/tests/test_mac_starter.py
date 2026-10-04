"""Private Mac setup/source guards; no model, account or imagery access."""
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from community import mac_starter as starter
from community.desktop import DesktopApp

REPO=Path(__file__).resolve().parents[2]
# macOS executes its POSIX system Perl. Native Windows Perl distributions do
# not necessarily implement the POSIX Fcntl stat predicates this verifier uses.
# Exercise the Windows fixtures with Git's POSIX Perl, never an arbitrary PATH
# interpreter. Actual Mac CI independently exercises /usr/bin/perl without skips.
GIT_PERL=Path(os.environ.get('ProgramFiles','C:/Program Files'))/'Git/usr/bin/perl.exe'
PERL=(str(GIT_PERL) if GIT_PERL.is_file() else None) if sys.platform=='win32' else shutil.which('perl')

class MacStarterTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name).resolve()
        self.app=self.root/'private';self.app.mkdir()

    def test_checked_in_interpreter_inventory_matches_launcher_and_archive_pins(self):
        body=(REPO/'macos/python-arm64-inventory.json').read_bytes()
        script=(REPO/'macos/Start-Vision.command').read_text(encoding='utf-8')
        self.assertNotIn(b'\r',body)
        self.assertEqual(re.search(r'^inventory_sha=([a-f0-9]{64})$',script,re.M).group(1),hashlib.sha256(body).hexdigest())
        pins=json.loads(body)
        self.assertEqual(pins['archiveSha256'],re.search(r'^archive_sha=([a-f0-9]{64})$',script,re.M).group(1))
        self.assertEqual((pins['platform'],pins['archiveBytes'],len(pins['files']),len(pins['links'])),
            ('darwin-arm64',26798928,1689,9))

    def test_public_source_only_snapshot_is_verified_and_reused(self):
        target,digest=starter.copy_source(REPO,self.app)
        original={p.relative_to(target).as_posix():p.read_bytes() for p in target.rglob('*') if p.is_file()}
        self.assertEqual(starter.copy_source(REPO,self.app),(target,digest))
        self.assertEqual(original,{p.relative_to(target).as_posix():p.read_bytes() for p in target.rglob('*') if p.is_file()})
        self.assertNotIn('.git',str(target.relative_to(self.app)))
        self.assertEqual(set(original)-{'source-inventory.json'},set(starter.source_inventory(REPO)))

    def test_missing_changed_and_extra_snapshot_files_stop_without_overwrite(self):
        target,_=starter.copy_source(REPO,self.app)
        path=target/'community/desktop.py';original=path.read_bytes()
        for mutation in ('changed','missing','extra'):
            with self.subTest(mutation=mutation):
                if mutation=='changed':path.write_bytes(b'changed')
                elif mutation=='missing':path.unlink()
                else:(target/'unexpected.py').write_bytes(b'unknown')
                with self.assertRaises((starter.SnapshotError,FileNotFoundError)):
                    starter.copy_source(REPO,self.app)
                if mutation=='extra':(target/'unexpected.py').unlink()
                else:path.write_bytes(original)

    def test_snapshot_receipt_cannot_be_changed(self):
        target,_=starter.copy_source(REPO,self.app)
        (target/'source-inventory.json').write_bytes(b'{}')
        with self.assertRaisesRegex(starter.SnapshotError,'receipt_changed'):starter.copy_source(REPO,self.app)

    def test_linked_source_or_private_folder_is_rejected(self):
        source=self.root/'source';source.mkdir()
        link=self.root/'link'
        try:link.symlink_to(source,target_is_directory=True)
        except OSError:self.skipTest('Symlink creation not permitted')
        with self.assertRaises(starter.SnapshotError):starter.source_inventory(link)
        (self.app/'apps').symlink_to(source,target_is_directory=True)
        with self.assertRaises(starter.SnapshotError):starter.copy_source(REPO,self.app)
        self.assertEqual(list(source.iterdir()),[])

    def test_required_source_missing_does_not_publish_snapshot(self):
        source=self.root/'empty';source.mkdir()
        with self.assertRaisesRegex(starter.SnapshotError,'source_download_incomplete'):
            starter.copy_source(source,self.app)
        self.assertFalse((self.app/'apps').exists())

    def test_copy_interruption_preserves_existing_account_and_incomplete_stage(self):
        account=self.app/'account.json';account.write_bytes(b'private-saved-account')
        original=Path.read_bytes
        def interrupted(path):
            if path==REPO/'community/desktop.py':raise OSError('simulated interruption')
            return original(path)
        with patch.object(Path,'read_bytes',interrupted),self.assertRaises(OSError):starter.copy_source(REPO,self.app)
        self.assertEqual(account.read_bytes(),b'private-saved-account')
        self.assertTrue(any((self.app/'apps').glob('staging-*')))
        self.assertFalse(any((self.app/'apps').glob('[a-f0-9]'*64)))

    def test_mac_binary_path_has_no_windows_suffix(self):
        with patch('community.vision_index.sys.platform','darwin'):
            app=DesktopApp(self.app)
            self.assertEqual(app.assets['binary'],self.app/'runtime/bin/mma-vision')
            self.assertFalse(app.snapshot()['backgroundAvailable'])

    def test_windows_binary_path_stays_executable(self):
        with patch('community.vision_index.sys.platform','win32'):
            app=DesktopApp(self.app)
            self.assertEqual(app.assets['binary'],self.app/'runtime/bin/mma-vision.exe')
            self.assertTrue(app.snapshot()['backgroundAvailable'])

    def test_mac_prepare_uses_scene_assets_and_does_not_create_an_account(self):
        with patch('community.vision_index.sys.platform','darwin'),patch('community.desktop.runtime_platform',return_value='darwin-arm64'), \
                patch('community.desktop.install_runtime') as install,patch('community.desktop.default_runner',return_value=(0,'{}','')), \
                patch('community.desktop.require_layout'),patch.object(DesktopApp,'release_pc_check'):
            app=DesktopApp(self.app);app.prepare()
            self.assertEqual(install.call_args.kwargs['lane'],'scene')
            self.assertTrue(app.snapshot()['ready']);self.assertFalse(app.snapshot()['qualified'])
            self.assertIsNone(app.client);self.assertFalse((self.app/'account.json').exists())

@unittest.skipUnless(PERL,'Mac POSIX verifier fixture requires system Perl or Windows Git Perl')
class PrivatePythonGuards(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name).resolve();self.runtime=self.root/'runtime';self.runtime.mkdir()
        (self.runtime/'python').mkdir()
        self.body=self.runtime/'python/library.py';self.body.write_bytes(b'pinned source')
        self.pins={'version':1,'files':{'python/library.py':{'bytes':13,'sha256':hashlib.sha256(b'pinned source').hexdigest(),'executable':False}},
            'links':{},'directories':['python']}
        self.manifest=self.root/'inventory.json'

    def check(self,expected=None):
        self.manifest.write_text(json.dumps(self.pins),encoding='utf-8')
        digest=hashlib.sha256(self.manifest.read_bytes()).hexdigest()
        return subprocess.run([PERL,str(REPO/'macos/verify-python.pl'),self.manifest.as_posix(),expected or digest,self.runtime.as_posix()],
            capture_output=True,text=True,timeout=20)

    def test_full_tree_verifies_before_python_execution(self):
        result=self.check();self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout,'private_python_verified\n')

    def test_untrusted_manifest_and_changed_missing_extra_files_are_rejected(self):
        self.assertNotEqual(self.check('0'*64).returncode,0)
        self.body.write_bytes(b'changed bytes');self.assertNotEqual(self.check().returncode,0)
        self.body.unlink();self.assertNotEqual(self.check().returncode,0)
        self.body.write_bytes(b'pinned source')
        (self.runtime/'python/unexpected.py').write_bytes(b'unknown');self.assertNotEqual(self.check().returncode,0)

    def test_unexpected_or_escaping_symlinks_do_not_read_external_files(self):
        external=self.root/'private.py';external.write_bytes(b'private external')
        link=self.runtime/'python/link.py'
        try:link.symlink_to(external)
        except OSError:self.skipTest('Symlink creation not permitted')
        self.assertNotEqual(self.check().returncode,0)
        self.pins['links']['python/link.py']='../../private.py'
        self.assertNotEqual(self.check().returncode,0)
        self.assertEqual(external.read_bytes(),b'private external')

    def test_pinned_internal_links_verify_but_retargeting_stops(self):
        link=self.runtime/'python/link.py'
        try:link.symlink_to('library.py')
        except OSError:self.skipTest('Symlink creation not permitted')
        self.pins['links']['python/link.py']='library.py'
        result=self.check();self.assertEqual(result.returncode,0,result.stderr)
        link.unlink();link.symlink_to('unlisted.py')
        self.assertNotEqual(self.check().returncode,0)

    def test_metadata_cannot_claim_an_escaping_path_or_cross_type_identity(self):
        self.pins['directories'].append('python/../../outside')
        self.assertNotEqual(self.check().returncode,0)
        self.pins['directories']=['python','python/library.py']
        self.assertNotEqual(self.check().returncode,0)

if __name__=='__main__':unittest.main()
