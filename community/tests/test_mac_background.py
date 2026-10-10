"""Owned registration/control fixtures. No accounts, service writes or imagery."""
import hashlib
from datetime import datetime, timezone
import http.client
import json
import os
from pathlib import Path
import plistlib
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer

from community.background import DesktopError, measure_storage, single_instance
from community.contribute import DEFAULT_URL
from community.mac_background import DEFAULT_SETTINGS, MacBackground, read_json, settings_config
from community.mac_background_control import Controls, handler_for
from community.mac_launch_guard import GUARD
from community.mac_runtime import PYTHON_FOLDER, PYTHON_RELATIVE, runtime_links
from community.mac_starter import copy_source
from community.tests.test_mac_starter import PERL, REPO


class Scheduler:
    def __init__(self):
        self.config = None
        self.running = False
        self.calls = []
        self.fail = None

    def __call__(self, arguments, **_kwargs):
        self.calls.append(arguments)
        action = arguments[1]
        if action == self.fail:
            return subprocess.CompletedProcess(arguments, 1, '', 'PRIVATE DIAGNOSTIC')
        if action == 'bootstrap':
            self.config = plistlib.loads(Path(arguments[3]).read_bytes())
        elif action == 'bootout':
            self.config = None
            self.running = False
        elif action == 'kickstart':
            self.running = True
        if action == 'print':
            if self.config is None:
                return subprocess.CompletedProcess(arguments, 113, '', '')
            text = ('program = ' + self.config['ProgramArguments'][0] + '\narguments = {\n' +
                '\n'.join(self.config['ProgramArguments']) + '\n}\nrun interval = '+str(self.config['StartInterval'])+' seconds\n')
            if self.running:
                text += 'pid = 1234\n'
            return subprocess.CompletedProcess(arguments, 0, text, '')
        return subprocess.CompletedProcess(arguments, 0, '', '')


class MacBackgroundTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.home = self.root / 'home'
        self.home.mkdir()
        self.source, _ = copy_source(REPO, self.root)
        python = self.root / PYTHON_FOLDER / PYTHON_RELATIVE
        python.parent.mkdir(parents=True)
        python.write_bytes(b'finite regular interpreter path fixture')
        self.scheduler = Scheduler()
        with patch('community.mac_background.sys.platform','darwin'):
            self.manager = MacBackground(self.root, self.source, home=self.home,
                runner=self.scheduler, uid=1001, handover_seconds=0)

    def enable(self):
        self.manager.enable(dict(DEFAULT_SETTINGS), accept=True, code='private synthetic recovery code')

    def test_enable_defaults_readback_and_cooperative_pause_resume_preserve_saved_files(self):
        checkpoint = self.root / 'checkpoint'
        checkpoint.write_bytes(b'saved progress')
        self.enable()
        self.assertFalse((self.root / 'STOP-AFTER-BATCH').exists())
        status = self.manager.status()
        self.assertTrue(status['enabled']); self.assertTrue(status['running'])
        self.assertNotIn('private synthetic recovery code', json.dumps(status))
        original = (self.root / 'account.json').read_bytes()
        self.manager.pause(True)
        self.assertTrue((self.root / 'PAUSE').exists())
        self.manager.pause(False)
        self.assertFalse((self.root / 'PAUSE').exists())
        self.assertEqual(checkpoint.read_bytes(),b'saved progress')
        self.assertEqual((self.root / 'account.json').read_bytes(),original)
        arguments = self.scheduler.config['ProgramArguments']
        self.assertIn(GUARD,arguments)
        self.assertIn('-i',arguments)
        self.assertNotIn('private synthetic recovery code',str(arguments))
        self.assertFalse(any('-k' in command for command in self.scheduler.calls))

    def test_stale_status_never_claims_a_current_running_worker(self):
        self.enable();self.scheduler.running=False
        (self.root / 'background-status.json').write_text(json.dumps({'state':'processing'}))
        value = self.manager.status()
        self.assertFalse(value['running'])
        self.assertIn('not running now',value['message'])
        self.assertIn('Last saved report: Processing',value['message'])
        self.assertNotIn('healthy',value['message'])

    def test_saved_report_time_is_validated_without_claiming_a_running_worker(self):
        self.enable();self.scheduler.running=False
        path=self.root/'background-status.json'
        stamp='2026-10-09T23:59:18Z'
        path.write_text(json.dumps({'state':'processing','updatedAt':stamp}))
        expected=datetime(2026,10,9,23,59,18,tzinfo=timezone.utc).astimezone().strftime('%Y-%m-%d %H:%M')
        value=self.manager.status()
        self.assertIn('Report time: '+expected+' (computer time).',value['message'])
        self.assertFalse(value['running'])
        self.assertIn('not running now',value['message'])
        self.assertNotIn('healthy',value['message'])
        for invalid in (None,123,[],{},'private saved code','2026-10-09T23:59:18',
                '2026-13-09T23:59:18Z','2026-10-39T23:59:18Z','2026-10-09T23:59:18Z extra'):
            with self.subTest(invalid=invalid):
                path.write_text(json.dumps({'state':'processing','updatedAt':invalid}))
                value=self.manager.status()
                self.assertFalse(value['running'])
                self.assertIn('Report time: unavailable.',value['message'])
                self.assertNotIn('private saved code',value['message'])

    def test_status_read_stays_bounded_when_a_prior_file_size_is_stale(self):
        path=self.root/'background-status.json'
        original=json.dumps({'state':'processing','padding':'x'*65536}).encode()
        path.write_bytes(original)
        real_stat=Path.stat
        def stale_size(file,*args,**kwargs):
            value=real_stat(file,*args,**kwargs)
            if file==path and kwargs.get('follow_symlinks',True):
                fields=list(value);fields[6]=1
                return os.stat_result(fields)
            return value
        with patch.object(Path,'stat',stale_size),self.assertRaisesRegex(ValueError,'saved_settings_need_review'):
            read_json(path)
        self.assertEqual(path.read_bytes(),original)

    def test_replacement_and_remove_preserve_account_pause_failure_and_history(self):
        self.enable();original = (self.root / 'account.json').read_bytes()
        (self.root / 'PAUSE').write_bytes(b'pause')
        (self.root / 'NEEDS-ATTENTION').write_bytes(b'failure')
        value = dict(DEFAULT_SETTINGS,storageLimitGb=20)
        self.manager.enable(value,accept=True,code='do not replace')
        self.assertEqual(self.manager.status()['settings'],value)
        self.assertEqual((self.root / 'account.json').read_bytes(),original)
        self.assertEqual((self.root / 'PAUSE').read_bytes(),b'pause')
        self.assertEqual((self.root / 'NEEDS-ATTENTION').read_bytes(),b'failure')
        with self.assertRaises(ValueError):self.manager.pause(False)
        self.manager.remove()
        self.assertFalse(self.manager.plist.exists())
        self.assertFalse(self.manager.status()['enabled'])
        self.assertTrue((self.root / 'STOP-AFTER-BATCH').exists())
        self.manager.remove()
        self.manager.enable(value,accept=True)
        self.assertEqual((self.root / 'account.json').read_bytes(),original)
        self.assertEqual(len(list((self.root / 'mac-background-history').glob('*.json'))),2)

    def test_no_registration_changes_while_an_owned_batch_or_guided_instance_holds_lock(self):
        self.enable();before=self.manager.plist.read_bytes()
        self.scheduler.calls.clear()
        with single_instance(self.root), self.assertRaisesRegex(ValueError,'finish_current_batch'):
            self.manager.enable(dict(DEFAULT_SETTINGS),accept=True)
        self.assertFalse(any(c[1] in {'bootout','bootstrap','kickstart'} for c in self.scheduler.calls))
        self.assertEqual(self.manager.plist.read_bytes(),before)
        self.assertTrue((self.root / 'STOP-AFTER-BATCH').exists())
        with self.assertRaises(ValueError):self.manager.pause(False)

    def test_bad_readback_or_bootstrap_keeps_stop_and_does_not_start(self):
        self.scheduler.fail='bootstrap'
        with self.assertRaises(ValueError):self.enable()
        self.assertTrue((self.root / 'STOP-AFTER-BATCH').exists())
        self.assertFalse(any(c[1]=='kickstart' for c in self.scheduler.calls))
        self.scheduler.fail=None
        self.enable()
        body = self.manager.plist.read_bytes()
        self.manager.plist.write_bytes(body+b' ')
        with self.assertRaisesRegex(ValueError,'unfamiliar'):self.manager.remove()
        self.assertTrue(self.manager.plist.exists())

    def test_unfamiliar_job_and_invalid_settings_do_not_touch_other_files(self):
        self.scheduler.config=dict(self.manager.config,WorkingDirectory='unrelated')
        with self.assertRaisesRegex(ValueError,'unfamiliar'):self.enable()
        self.assertFalse((self.root / 'STOP-AFTER-BATCH').exists())
        self.assertFalse((self.root / 'account.json').exists())
        self.scheduler.config=None
        for invalid in ({},dict(DEFAULT_SETTINGS,dayStart='00:00'),dict(DEFAULT_SETTINGS,retryMinutes=True)):
            with self.assertRaises(ValueError):self.manager.enable(invalid,accept=True)
        with self.assertRaisesRegex(ValueError,'consent'):self.manager.enable(DEFAULT_SETTINGS)
        self.assertFalse(self.manager.plist.exists())

    def test_work_choice_is_registered_and_legacy_settings_keep_the_original_arguments(self):
        legacy = {key:value for key,value in DEFAULT_SETTINGS.items() if key != 'workType'}
        self.assertNotIn('work_type', settings_config(legacy))
        self.manager.enable(legacy,accept=True,code='private synthetic recovery code')
        self.assertNotIn('--work-type', self.scheduler.config['ProgramArguments'])
        self.assertEqual(self.manager.status()['settings'],legacy)
        for choice in ('object', 'both', 'scene'):
            settings = dict(DEFAULT_SETTINGS,workType=choice)
            self.manager.enable(settings,accept=True)
            args = self.scheduler.config['ProgramArguments']
            self.assertEqual(args[args.index('--work-type')+1],choice)
            self.assertEqual(self.manager.status()['settings'],settings)
        for choice in ('unknown', [], True):
            with self.assertRaises(ValueError):settings_config(dict(DEFAULT_SETTINGS,workType=choice))

    def test_other_service_account_is_preserved_without_registration(self):
        body=json.dumps({'url':'https://staging.example','recoveryCode':'private'}).encode()
        (self.root / 'account.json').write_bytes(body)
        with self.assertRaisesRegex(ValueError,'account_needs_review'):self.enable()
        self.assertEqual((self.root / 'account.json').read_bytes(),body)
        self.assertFalse(self.manager.plist.exists())

    def test_actual_local_http_requires_token_host_origin_and_bounded_json(self):
        controls=Controls(self.manager)
        server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(controls))
        controls.server=server
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        def request(path,body=None,**headers):
            connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3)
            self.addCleanup(connection.close)
            connection.request('POST' if body is not None else 'GET',path,body=body,headers=headers)
            response=connection.getresponse();return response.status,response.read()
        self.assertEqual(request('/api/status')[0],403)
        self.assertEqual(request('/api/status',**{'X-Vision-Token':controls.token,'Origin':'https://other.example'})[0],403)
        self.assertEqual(request('/',**{'Host':'localhost'})[0],403)
        for path in ('/','/app.js','/style.css'):
            self.assertEqual(request(path)[0],200)
        headers={'X-Vision-Token':controls.token,'Content-Type':'application/json'}
        for invalid in ('x'*4097,'[]','{'):
            self.assertEqual(request('/api/enable',invalid,**headers)[0],400)
        self.assertFalse(self.manager.plist.exists())
        self.assertEqual(request('/api/enable',json.dumps({'settings':DEFAULT_SETTINGS,'accept':True,'code':'private-test-code'}),**headers)[0],200)
        status,body=request('/api/status',**headers)
        self.assertEqual(status,200);self.assertNotIn(b'private-test-code',body)
        with controls.busy:
            self.assertEqual(request('/api/pause','{}',**headers)[0],400)
        self.assertEqual(request('/api/pause','{}',**headers)[0],200)
        status, body = request('/api/quit','{}',**headers)
        self.assertEqual(status,200)
        self.assertEqual(json.loads(body), {'message':'Controls closed. Enabled automatic processing continues.'})
        thread.join(3)
        self.assertTrue(self.scheduler.running)


@unittest.skipUnless(PERL,'System POSIX Perl required')
class SourceGuardTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name).resolve()
        self.source,self.digest=copy_source(REPO,self.root)

    def check(self):
        return subprocess.run([PERL,str(REPO/'macos/verify-source.pl'),self.source.as_posix(),self.digest],
            capture_output=True,text=True,timeout=20)

    def test_full_tree_and_changed_missing_extra_files_or_directories_fail_closed(self):
        result=self.check();self.assertEqual(result.returncode,0,result.stderr)
        path=self.source/'community/mac_worker.py';original=path.read_bytes()
        path.write_bytes(b'changed');self.assertNotEqual(self.check().returncode,0)
        path.unlink();self.assertNotEqual(self.check().returncode,0)
        path.write_bytes(original)
        unexpected=self.source/'empty-unlisted';unexpected.mkdir()
        self.assertNotEqual(self.check().returncode,0)
        unexpected.rmdir()
        self.assertEqual(self.check().returncode,0)

    def test_guard_literal_is_single_line_and_cannot_inherit_runtime_options(self):
        self.assertNotIn('\n',GUARD)
        self.assertIn("system('/usr/bin/perl'",GUARD)
        self.assertIn('NEEDS-ATTENTION',GUARD)
        self.assertNotIn('BASH_ENV',GUARD)
        result=subprocess.run([PERL,'-c','-e',GUARD],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)


class MacStorageLinksTests(unittest.TestCase):
    def test_inventory_pin_and_missing_runtime(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve()
            self.assertEqual(runtime_links(root),{})
            (root/PYTHON_FOLDER).mkdir()
            approved=runtime_links(root)
            self.assertEqual(len(approved),9)
            self.assertTrue(all(name.startswith(PYTHON_FOLDER+'/python/') for name in approved))
            with patch('community.mac_runtime.INVENTORY_SHA256','0'*64),self.assertRaises(ValueError):runtime_links(root)

    def test_only_pinned_direct_regular_siblings_count_once_without_reading_private_contents(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();target=root/'library';target.write_bytes(b'private contents')
            link=root/'link'
            try:link.symlink_to('library')
            except OSError:self.skipTest('Symlink creation not permitted')
            with self.assertRaises(DesktopError):measure_storage(root)
            with patch.object(Path,'open',side_effect=AssertionError('Must not read private contents')):
                measurement=measure_storage(root,approved_links={'link':'library'})
            self.assertEqual(measurement['usedBytes'],target.stat().st_size+link.lstat().st_size)
            self.assertEqual((measurement['files'],measurement['links']),(1,1))
            for unsafe in ('../library','C:library','another','..'):
                with self.assertRaises(DesktopError):measure_storage(root,approved_links={'link':unsafe})
            target.unlink();target.mkdir()
            with self.assertRaises(DesktopError):measure_storage(root,approved_links={'link':'library'})


if __name__=='__main__':unittest.main()
