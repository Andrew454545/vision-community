"""Offline configured runner/provisioner checks; no live credentials or activation."""
from contextlib import ExitStack
import copy
import ctypes
import io
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from community import owner_object_service as service
from community import owner_object_credential_provision as setup
from community import owner_credential_provision as shared
from community import owner_object_credentials as vault
from community import owner_search_credentials as search_vault
from community.owner_search_agent import _exclusive, OwnerSearchError
from community.search_snapshot import digest, encoded
from community.tests import test_owner_object_agent as fixtures
from community.tests import test_owner_credential_provision as credential_fixtures
from community.tests import test_owner_object_retirement as retirement_fixtures


class ConfigFixture(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup);self.root=Path(folder.name).resolve()
        self.state=self.root/'state';self.state.mkdir()
        self.config={'version':1,'scope':service.SCOPE,'origin':'https://coordinator.example','environment':'staging',
            'state':str(self.state),'binding':copy.deepcopy(fixtures.BINDING),
            'native':{'binary':str(self.root/'runtime/native'),'models':str(self.root/'runtime/models'),
                'policy':str(self.root/'policy/policy.json'),'policySha256':fixtures.BINDING['policySha256'],
                'registry':str(self.root/'assignment/registry.json'),'registrySha256':'8'*64,'spool':str(self.root/'spool')}}
        self.path=self.root/'service.private.json';self.save()
    def save(self,activate=True):
        self.path.write_bytes(encoded(self.config));self.pin=digest(self.path.read_bytes())
        if activate:
            (self.state/service.ACTIVATION).write_bytes(encoded({'version':1,'scope':'explicit-owner-object-audit-activation',
                'approved':True,'configSha256':self.pin,'origin':self.config['origin'],'environment':self.config['environment']}))


class ObjectServiceTests(ConfigFixture):
    def setUp(self):
        super().setUp();self.coordinator=fixtures.Coordinator();self.engine=fixtures.Engine()
        self.coordinator.job['claimUntil']=int(time.time())+1200;self.engine.now=int(time.time())
        self.stack=self.enterContext(ExitStack())
        self.credentials=self.stack.enter_context(patch.object(service.HTTPSObjectCoordinator,'from_os_credentials',return_value=self.coordinator))
        self.native=self.stack.enter_context(patch.object(service.LazyVerifier,'_get',return_value=self.engine))
    def run_once(self):return service.run_service(self.path,self.pin,once=True)
    def next(self):
        path=self.state/'supervisor.json';doc=json.loads(path.read_bytes());doc['nextAttemptAt']=0;path.write_bytes(encoded(doc))

    def test_configured_finite_service_delivers_exact_binding_and_closes_without_activation_changes(self):
        original=(self.state/service.ACTIVATION).read_bytes()
        self.assertEqual(self.run_once()['status'],'completed')
        self.credentials.assert_called_once_with(self.config['origin'])
        self.assertEqual(self.coordinator.calls[0],('claim',{'binding':self.config['binding']}))
        self.assertEqual((self.state/service.ACTIVATION).read_bytes(),original)
        self.assertEqual(self.run_once()['status'],'deferred')

    def test_lost_ack_restart_needs_neither_native_assets_nor_native_spool(self):
        self.coordinator.error=OwnerSearchError('coordinator_unavailable',503)
        self.assertEqual(self.run_once()['status'],'retry_wait')
        saved=(self.state/'object-outbox.json').read_bytes();self.next();self.native.reset_mock()
        self.coordinator.error=None
        self.assertEqual(self.run_once()['status'],'completed');self.native.assert_not_called()
        self.assertEqual(self.coordinator.calls[-1][1],json.loads(saved)['body'])
        self.assertFalse(Path(self.config['native']['spool']).exists())

    def test_pause_stop_and_missing_or_other_purpose_activation_never_read_key_or_native(self):
        for marker in ('PAUSE','STOP'):
            path=self.state/marker;path.touch()
            self.assertIn(self.run_once()['status'],{'paused','stopped'});path.unlink()
        activation=self.state/service.ACTIVATION;activation.unlink()
        with self.assertRaises(service.OwnerObjectServiceError):self.run_once()
        activation.write_bytes(encoded({'version':1,'scope':'explicit-owner-search-activation','approved':True,
            'configSha256':self.pin,'origin':self.config['origin'],'environment':self.config['environment']}))
        with self.assertRaises(service.OwnerObjectServiceError):self.run_once()
        self.credentials.assert_not_called();self.native.assert_not_called()

    def test_native_spool_pause_is_preserved_and_stops_before_credential_access(self):
        spool=Path(self.config['native']['spool']);spool.mkdir();(spool/'PAUSE').touch()
        self.assertEqual(self.run_once(),{'status':'paused'});self.credentials.assert_not_called();self.native.assert_not_called()
        self.assertTrue((spool/'PAUSE').exists())

    def test_wrong_resource_binding_private_paths_or_source_state_fail_closed(self):
        original=copy.deepcopy(self.config)
        changes=(lambda d:d.update(environment='production'),lambda d:d.update(version=True),
            lambda d:d.update(secret='PRIVATE'),lambda d:d['native'].update(policySha256='0'*64),
            lambda d:d['native'].update(registrySha256=True),lambda d:d['native'].update(binary='relative.exe'),
            lambda d:d['native'].update(spool=str(self.state/'spool')),lambda d:d['native'].update(policy=str(self.state/'policy.json')),
            lambda d:d['native'].update(spool=str(Path(service.__file__).resolve().parents[1]/'spool')),
            lambda d:d.update(origin='https://coordinator.example/private'))
        for change in changes:
            self.config=copy.deepcopy(original);change(self.config);self.save()
            with self.assertRaises(service.OwnerObjectServiceError):service.load_configuration(self.path,self.pin)
        self.credentials.assert_not_called();self.native.assert_not_called()

    def test_configuration_pin_and_activation_cannot_be_retargeted(self):
        self.path.write_bytes(self.path.read_bytes()+b' ')
        with self.assertRaises(service.OwnerObjectServiceError):self.run_once()
        self.save();activation=self.state/service.ACTIVATION;doc=json.loads(activation.read_bytes());doc['approved']=1
        activation.write_bytes(encoded(doc))
        with self.assertRaises(service.OwnerObjectServiceError):self.run_once()
        self.credentials.assert_not_called()

    def test_retirement_is_explicit_only_and_invalid_flag_cannot_activate_it(self):
        self.config['retirement']=True;self.save()
        self.assertIs(service.load_configuration(self.path,self.pin)['retirement'],True)
        for value in (False,1,'true',{}):
            self.config['retirement']=value;self.save()
            with self.assertRaises(service.OwnerObjectServiceError):service.load_configuration(self.path,self.pin)
        self.credentials.assert_not_called()

    def test_explicit_retirement_mode_polls_then_reuses_same_connection_for_finite_audit(self):
        coordinator=retirement_fixtures.Coordinator();coordinator.command=None
        coordinator.job['claimUntil']=int(time.time())+1200
        engine=retirement_fixtures.Engine();engine.now=int(time.time())
        self.config['retirement']=True;self.save()
        with patch.object(service.HTTPSObjectCoordinator,'from_os_credentials',return_value=coordinator) as credentials,\
                patch.object(service.LazyVerifier,'_get',return_value=engine):
            self.assertEqual(self.run_once()['status'],'completed');credentials.assert_called_once()
        self.assertEqual([c[0] for c in coordinator.calls],['retirement','claim','candidate','complete'])
        self.assertEqual(engine.cleanups,0)

    def test_shared_service_lock_refuses_overlapping_runner_and_keeps_saved_work(self):
        (self.state/'object-outbox.pending').write_bytes(b'preserved incomplete')
        with _exclusive(self.state,name='service.lock'):self.assertEqual(self.run_once(),{'status':'busy'})
        self.credentials.assert_not_called();self.native.assert_not_called()
        self.assertEqual((self.state/'object-outbox.pending').read_bytes(),b'preserved incomplete')

    def test_authentication_latch_stays_across_configured_restarts_without_probes(self):
        self.coordinator.error=OwnerSearchError('coordinator_unavailable',401)
        self.assertEqual(self.run_once()['status'],'operator_required');calls=len(self.coordinator.calls)
        self.assertEqual(self.run_once()['status'],'operator_required');self.assertEqual(len(self.coordinator.calls),calls)
        self.assertTrue((self.state/'object-outbox.json').exists())

    def test_lazy_constructor_passes_exact_pins_never_caches_wrong_binding_and_closes_owned_spool(self):
        self.stack.close()
        n=self.config['native'];b=self.config['binding'];guard=MagicMock()
        verifier=SimpleNamespace(document={'policyId':b['policyId'],'qualityImplementationIdentity':b['qualityImplementationIdentity'],
            'protectedAuthority':{'sha256':b['protectedAuthoritySha256']},'protectedOriginHandoffSha256':b['protectedOriginHandoffSha256'],
            'profiles':b['profiles'],'resource':b['resource']},policy_sha256=b['policySha256'],profile={'sha256':b['runtimeProfileSha256']})
        jobs=SimpleNamespace(close=MagicMock());engine=SimpleNamespace(jobs=jobs)
        lazy=service.LazyVerifier(self.config,guard)
        with patch.object(service,'NativeObjectVerifier',return_value=verifier) as native,\
                patch.object(service,'ObjectAuditJobs',return_value=jobs) as queue,\
                patch.object(service,'OwnerObjectVerifier',return_value=engine) as wrapped:
            self.assertIs(lazy._get(),engine);self.assertIs(lazy._get(),engine)
            native.assert_called_once_with(Path(n['binary']),Path(n['models']),Path(n['policy']),n['policySha256'])
            queue.assert_called_once_with(verifier,Path(n['registry']),n['registrySha256'],Path(n['spool']))
            wrapped.assert_called_once_with(jobs,guard=guard);lazy.close();jobs.close.assert_called_once()
            verifier.profile['sha256']='0'*64
            with self.assertRaises(service.OwnerObjectServiceError):lazy._get()
            self.assertIsNone(lazy.engine);self.assertEqual(queue.call_count,1)

    def test_guard_change_after_jobs_open_closes_owned_spool_and_does_not_cache_engine(self):
        self.stack.close()
        b=self.config['binding'];verifier=SimpleNamespace(document={'policyId':b['policyId'],'qualityImplementationIdentity':b['qualityImplementationIdentity'],
            'protectedAuthority':{'sha256':b['protectedAuthoritySha256']},'protectedOriginHandoffSha256':b['protectedOriginHandoffSha256'],
            'profiles':b['profiles'],'resource':b['resource']},policy_sha256=b['policySha256'],profile={'sha256':b['runtimeProfileSha256']})
        jobs=SimpleNamespace(close=MagicMock());guard=MagicMock(side_effect=[None,ValueError('PRIVATE')])
        lazy=service.LazyVerifier(self.config,guard)
        with patch.object(service,'NativeObjectVerifier',return_value=verifier),patch.object(service,'ObjectAuditJobs',return_value=jobs):
            with self.assertRaises(ValueError):lazy._get()
        self.assertIsNone(lazy.engine);jobs.close.assert_called_once()

    def test_cli_bad_arguments_or_private_exception_return_fixed_message_without_echo(self):
        out=io.StringIO();err=io.StringIO()
        with patch.object(service.sys,'stdout',out),patch.object(service.sys,'stderr',err):
            self.assertEqual(service.main(['--secret','PRIVATE']),1)
        self.assertNotIn('PRIVATE',out.getvalue()+err.getvalue())
        self.assertEqual(json.loads(out.getvalue())['error'],'owner_object_operator_required')


class ObjectProvisionTests(ConfigFixture):
    def setUp(self):
        super().setUp();self.memory=credential_fixtures.MemoryVault()
        self.patcher=patch.object(setup,'_backend',return_value=self.memory)
        self.backend=self.enterContext(self.patcher)
    def provision(self,**kwargs):return setup.provision_credential(self.path,self.pin,'a'*64,**kwargs)

    def test_dedicated_setup_preserves_pause_and_activation_and_never_uses_search_scope(self):
        (self.state/'PAUSE').touch();before=(self.state/service.ACTIVATION).read_bytes()
        self.assertEqual(self.provision(),{'status':'stored','activation':'unchanged'})
        self.backend.assert_called_once_with(vault.credential_target(self.config['origin']))
        self.assertNotEqual(vault.credential_target(self.config['origin']),search_vault.credential_target(self.config['origin']))
        self.assertTrue((self.state/'PAUSE').exists());self.assertEqual((self.state/service.ACTIVATION).read_bytes(),before)
        self.assertEqual(self.memory.writes,[('a'*64,False)])
        self.assertNotIn(b'a'*64,self.path.read_bytes()+b''.join(p.read_bytes() for p in self.state.iterdir()))

    def test_existing_key_rotation_requires_independent_old_pin_and_readback(self):
        self.memory.value='b'*64
        with self.assertRaises(shared.CredentialProvisionError):self.provision()
        with self.assertRaises(shared.CredentialProvisionError):self.provision(replace_sha256='0'*64)
        self.assertFalse(self.memory.writes)
        self.assertEqual(self.provision(replace_sha256=digest(b'b'*64))['status'],'stored')
        self.assertEqual(self.memory.writes,[('a'*64,True)])

    def test_wrong_configuration_or_service_lock_refuses_vault_access(self):
        with _exclusive(self.state,name='service.lock'):
            with self.assertRaisesRegex(shared.CredentialProvisionError,'owner_service_busy'):self.provision()
        self.path.write_bytes(self.path.read_bytes()+b' ')
        with self.assertRaises(shared.CredentialProvisionError):self.provision()
        self.backend.assert_not_called()

    def test_config_change_or_ambiguous_readback_preserves_possibly_written_key(self):
        reads=iter([None,'b'*64]);self.memory.read=lambda:next(reads)
        with self.assertRaisesRegex(shared.CredentialProvisionError,'owner_credential_readback_required'):self.provision()
        self.assertEqual(self.memory.value,'a'*64);self.assertEqual(len(self.memory.writes),1)

    def test_backend_selects_only_dedicated_account_on_both_platforms(self):
        # Undo the high-level fixture only; both native classes remain mocked.
        self.patcher.__exit__(None,None,None)
        for platform,kind in (('win32','WindowsVault'),('darwin','MacVault')):
            with patch.object(setup.sys,'platform',platform),patch.object(shared,kind) as factory:
                setup._backend(vault.credential_target(self.config['origin']))
                factory.assert_called_once_with(vault.credential_target(self.config['origin']),account=vault.ACCOUNT)

    def test_cli_requires_two_hidden_prompts_and_never_accepts_redirected_secret(self):
        for tty in (False,True):
            stdin=io.StringIO();stdin.isatty=lambda:tty;err=io.StringIO();err.isatty=lambda:tty;out=io.StringIO()
            with patch.object(setup.sys,'stdin',stdin),patch.object(setup.sys,'stderr',err),patch.object(setup.sys,'stdout',out),\
                    patch.object(setup.getpass,'getpass',side_effect=['a'*64,'a'*64]) as prompt:
                status=setup.main(['--config',str(self.path),'--config-sha256',self.pin])
            self.assertEqual(status,0 if tty else 1);self.assertEqual(prompt.call_count,2 if tty else 0)
            self.assertNotIn('a'*64,out.getvalue()+err.getvalue())


class DedicatedVaultAPITests(unittest.TestCase):
    def test_windows_write_uses_dedicated_account_and_reader_accepts_only_that_scope(self):
        target=vault.credential_target('https://coordinator.example');captured={}
        def write(pointer,_):captured['item']=pointer._obj;captured['raw']=ctypes.string_at(pointer._obj.CredentialBlob,128);return 1
        api=SimpleNamespace(CredReadW=MagicMock(),CredWriteW=MagicMock(side_effect=write),CredFree=MagicMock())
        with patch.object(shared.ctypes,'WinDLL',return_value=api,create=True):
            with shared.WindowsVault(target,account=vault.ACCOUNT) as selected:selected.write('a'*64,replace=False)
        item=captured['item'];self.assertEqual((item.TargetName,item.UserName,item.Persist),(target,vault.ACCOUNT,2))
        self.assertEqual(captured['raw'],('a'*64).encode('utf-16-le'));self.assertEqual(ctypes.string_at(item.CredentialBlob,128),bytes(128))

    def test_mac_add_and_read_use_dedicated_account_in_memory_preserving_normal_consent(self):
        target=vault.credential_target('https://coordinator.example');captured={}
        api=SimpleNamespace(**{k:MagicMock(return_value=0) for k in ('SecKeychainOpen','SecKeychainFindGenericPassword',
            'SecKeychainItemFreeContent','SecKeychainAddGenericPassword','SecKeychainItemModifyAttributesAndData')})
        core=SimpleNamespace(CFRelease=MagicMock())
        def open_keychain(_,out):ctypes.cast(out,ctypes.POINTER(ctypes.c_void_p))[0]=11;return 0
        def find(keychain,slen,name,alen,account,*_):
            self.assertEqual((name,account),(target.encode(),vault.ACCOUNT.encode()));return -25300
        def add(keychain,slen,name,alen,account,size,password,item):
            self.assertEqual((name,account),(target.encode(),vault.ACCOUNT.encode()))
            captured['blob']=password;captured['raw']=ctypes.string_at(password,size)
            ctypes.cast(item,ctypes.POINTER(ctypes.c_void_p))[0]=22;return 0
        api.SecKeychainOpen.side_effect=open_keychain;api.SecKeychainFindGenericPassword.side_effect=find
        api.SecKeychainAddGenericPassword.side_effect=add
        with patch.object(shared,'plain_path',side_effect=lambda p:p),patch.object(shared.ctypes,'CDLL',side_effect=[api,core]),\
                patch.object(search_vault.subprocess,'Popen') as popen:
            with shared.MacVault(target,account=vault.ACCOUNT) as selected:
                self.assertIsNone(selected.read());selected.write('a'*64,replace=False)
        self.assertEqual(captured['raw'],b'a'*64);self.assertEqual(bytes(captured['blob']),bytes(64));popen.assert_not_called()
