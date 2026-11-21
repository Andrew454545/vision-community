"""Finite synthetic retirement transport tests. No real model/cloud/vault."""
import copy
from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock,patch

from community import owner_object_retirement as cleanup
from community.owner_object_agent import OwnerObjectAuditAgent
from community.owner_search_agent import OwnerSearchError,_exclusive
from community.search_snapshot import encoded
from community.tests import test_owner_object_agent as fixtures


def command():
    audit=fixtures.audit()
    return {'version':1,'policyId':audit['policyId'],'profileId':audit['profileId'],'leaseId':audit['leaseId'],
        'jobId':audit['jobId'],'requestSha256':'9'*64,'body':{'version':1,'leaseId':audit['leaseId'],
            **{k:audit[k] for k in ('assignmentSha256','submissionSha256','candidateManifestSha256','receiptSha256','attempts')},
            'acceptanceSha256':'a'*64}}


class Coordinator(fixtures.Coordinator):
    def __init__(self):super().__init__();self.command=command();self.ack_error=None;self.ack_reply=None
    def post(self,action,value):
        if action not in {'retirement','retirement-ack'}:return super().post(action,value)
        self.calls.append((action,copy.deepcopy(value)))
        if action=='retirement':return {'command':copy.deepcopy(self.command)} if self.command else {'command':None,'retryAfterSeconds':30}
        if self.ack_error:raise self.ack_error
        return self.ack_reply or {'acknowledged':True,'leaseId':value['command']['leaseId'],
            'requestSha256':value['command']['requestSha256'],'privacyPending':False}


class Engine(fixtures.Engine):
    def __init__(self):super().__init__();self.cleanups=0;self.cleanup_state='retired';self.cleanup_hook=None
    def handle(self,method,path,raw=None):
        if path.endswith('/retire'):self.state='retiring'
        if path.endswith('/retire') or method=='GET' and self.state in {'retiring','retired','erasing','erased'}:
            self.calls.append((method,path,raw));value=fixtures.audit(self.state)
            if self.state in {'retiring','retired'}:value['receiptSha256']='4'*64
            return 200,value
        return super().handle(method,path,raw)
    def cleanup_once(self):
        self.cleanups+=1;self.state=self.cleanup_state
        if self.cleanup_hook:self.cleanup_hook()
        return {'status':'worked' if self.state in {'retired','erased'} else 'idle'}


class OwnerObjectRetirementTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);self.root=Path(temporary.name).resolve()
        self.coordinator=Coordinator();self.engine=Engine();self.guard=MagicMock()
    def owner(self):return OwnerObjectAuditAgent(self.coordinator,self.engine,self.root,fixtures.BINDING,guard=self.guard,clock=lambda:fixtures.NOW)
    def agent(self):return cleanup.OwnerObjectRetirementAgent(self.owner())
    def ready(self):
        self.coordinator.ack_error=OwnerSearchError('coordinator_unavailable',503)
        with self.assertRaisesRegex(OwnerSearchError,'coordinator_unavailable'):self.agent().run_once()
        return (self.root/'retirement-outbox.json').read_bytes()

    def test_one_cleanup_only_step_requires_completed_native_state_before_ack(self):
        self.engine.work_once=MagicMock(side_effect=AssertionError('no inference fallback'))
        self.assertEqual(self.agent().run_once(),{'status':'completed','retired':True,'privacyPending':False})
        self.engine.work_once.assert_not_called();self.assertEqual(self.engine.cleanups,1)
        self.assertEqual([c[0] for c in self.coordinator.calls],['retirement','retirement-ack'])
        self.assertEqual([c[0] for c in self.engine.calls],['POST','GET'])
        self.assertFalse((self.root/'retirement-outbox.json').exists())

    def test_no_maintenance_command_falls_back_to_existing_finite_audit(self):
        self.coordinator.command=None
        self.assertEqual(self.agent().run_once()['status'],'completed')
        self.assertEqual([c[0] for c in self.coordinator.calls],['retirement','claim','candidate','complete'])
        self.assertEqual(self.engine.cleanups,0)

    def test_lost_ack_restart_replays_exact_ready_outbox_without_native_access(self):
        saved=self.ready();self.coordinator.ack_error=None
        self.engine.handle=MagicMock(side_effect=AssertionError('native unavailable'))
        self.assertEqual(self.agent().run_once()['status'],'completed');self.engine.handle.assert_not_called()
        self.assertEqual(self.coordinator.calls[-1],('retirement-ack',json.loads(saved)))
        self.assertEqual(self.engine.cleanups,1)

    def test_existing_audit_completion_is_recovered_before_any_new_retirement(self):
        self.coordinator.error=OwnerSearchError('coordinator_unavailable',503)
        with self.assertRaises(OwnerSearchError):self.owner().run_once()
        self.coordinator.error=None;self.coordinator.calls.clear()
        self.assertEqual(self.agent().run_once()['status'],'completed')
        self.assertEqual([c[0] for c in self.coordinator.calls],['complete']);self.assertEqual(self.engine.cleanups,0)

    def test_audit_saved_while_waiting_for_owner_lock_still_precedes_maintenance(self):
        owner=self.owner();instance=cleanup.OwnerObjectRetirementAgent(owner)
        proof=self.engine.handle('POST','/object-audits/'+'c'*32+'/settlement-evidence',b'{}')[1]
        @contextmanager
        def raced_lock(root):
            with _exclusive(root):
                owner._save('complete',{'leaseId':'a'*32,'claimToken':'b'*32,'audit':fixtures.audit(),'evidence':proof})
                yield
        with patch.object(cleanup,'_exclusive',side_effect=raced_lock):
            self.assertEqual(instance.run_once()['status'],'completed')
        self.assertEqual([c[0] for c in self.coordinator.calls],['complete']);self.assertEqual(self.engine.cleanups,0)

    def test_crash_after_saving_command_promotes_it_before_any_native_call(self):
        instance=self.agent()
        with patch.object(cleanup.os,'replace',side_effect=OSError('PRIVATE')):
            with self.assertRaises(OSError):instance.run_once()
        self.assertFalse(self.engine.calls);self.assertTrue((self.root/'retirement-outbox.pending').exists())
        self.assertEqual(self.agent().run_once()['status'],'completed')
        self.assertEqual([c[0] for c in self.coordinator.calls],['retirement','retirement-ack'])

    def test_crash_after_completed_reply_flush_promotes_ack_without_repeating_cleanup(self):
        instance=self.agent();original=cleanup.os.replace;calls=0
        def replace(*args):
            nonlocal calls
            calls+=1
            if calls==2:raise OSError('PRIVATE')
            return original(*args)
        with patch.object(cleanup.os,'replace',side_effect=replace):
            with self.assertRaises(OSError):instance.run_once()
        self.assertEqual(self.engine.cleanups,1)
        saved=(self.root/'retirement-outbox.pending').read_bytes()
        self.engine.handle=MagicMock(side_effect=AssertionError('native files missing'))
        self.assertEqual(self.agent().run_once()['status'],'completed');self.engine.handle.assert_not_called()
        self.assertEqual(self.coordinator.calls[-1][1],json.loads(saved))

    def test_incomplete_pending_or_different_command_is_preserved_and_blocks_calls(self):
        partial=b'{"command":';path=self.root/'retirement-outbox.pending';path.write_bytes(partial)
        with self.assertRaises(ValueError):self.agent().run_once()
        self.assertEqual(path.read_bytes(),partial);self.assertFalse(self.coordinator.calls);self.assertFalse(self.engine.calls)
        path.unlink();saved=self.ready();doc=json.loads(saved);doc['command']['jobId']='d'*32;doc['audit']=None
        path.write_bytes(encoded(doc));self.coordinator.calls.clear()
        with self.assertRaises(OwnerSearchError):self.agent().run_once()
        self.assertEqual((self.root/'retirement-outbox.json').read_bytes(),saved);self.assertFalse(self.coordinator.calls)

    def test_capacity_cleanup_backlog_retains_command_without_ack_or_native_inference(self):
        self.engine.cleanup_state='retiring'
        self.assertEqual(self.agent().run_once(),{'status':'idle','retryAfterSeconds':30})
        self.assertEqual([c[0] for c in self.coordinator.calls],['retirement'])
        self.assertIsNone(json.loads((self.root/'retirement-outbox.json').read_bytes())['audit'])
        self.engine.cleanup_state='retired'
        self.assertEqual(self.agent().run_once()['status'],'completed');self.assertEqual(self.engine.cleanups,2)

    def test_ambiguous_ack_retains_exact_ready_bytes_and_does_not_repeat_cleanup(self):
        saved=self.ready();self.coordinator.ack_error=None;self.coordinator.ack_reply={'acknowledged':True,'private':'SECRET'}
        with self.assertRaisesRegex(OwnerSearchError,'invalid_owner_retirement_reply'):self.agent().run_once()
        self.assertEqual((self.root/'retirement-outbox.json').read_bytes(),saved);self.assertEqual(self.engine.cleanups,1)

    def test_pause_stop_and_second_writer_prevent_all_calls(self):
        for marker in ('PAUSE','STOP'):
            path=self.root/marker;path.touch();self.assertEqual(self.agent().run_once(),{'status':'paused'});path.unlink()
        with _exclusive(self.root):
            with self.assertRaisesRegex(OwnerSearchError,'owner_agent_busy'):self.agent().run_once()
        self.assertFalse(self.coordinator.calls);self.assertFalse(self.engine.calls);self.guard.assert_not_called()

    def test_pause_during_cleanup_keeps_command_and_does_not_ack_or_report_approval(self):
        self.engine.cleanup_hook=lambda:(self.root/'PAUSE').touch()
        self.assertEqual(self.agent().run_once(),{'status':'paused'})
        self.assertEqual([c[0] for c in self.coordinator.calls],['retirement'])
        self.assertIsNone(json.loads((self.root/'retirement-outbox.json').read_bytes())['audit'])

    def test_malformed_command_or_private_native_echo_never_reaches_ack(self):
        self.coordinator.command={**command(),'private':'PATH'}
        with self.assertRaisesRegex(OwnerSearchError,'invalid_owner_retirement'):self.agent().run_once()
        self.assertFalse(self.engine.calls)
        self.coordinator.command=command();original=self.engine.handle
        self.engine.handle=lambda *args:(200,{**original(*args)[1],'private':'PATH'})
        with self.assertRaisesRegex(OwnerSearchError,'invalid_owner_retirement'):self.agent().run_once()
        self.assertEqual([c[0] for c in self.coordinator.calls],['retirement','retirement'])

    def test_stronger_native_erasure_does_not_claim_account_deletion_complete(self):
        self.engine.cleanup_state='erased';self.coordinator.ack_reply={'acknowledged':True,'leaseId':'a'*32,
            'requestSha256':'9'*64,'privacyPending':True}
        self.assertEqual(self.agent().run_once(),{'status':'completed','retired':True,'privacyPending':True})
