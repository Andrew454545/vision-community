"""Actual durable native retry protocol; inference explicitly synthetic."""
import unittest
from concurrent.futures import ThreadPoolExecutor
from community import object_audit_jobs as jobs
from community.tests import test_object_audit_jobs as fixture_module

class ObjectRetryIntentTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixture_module.ObjectAuditJobTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f=self.fixture
        self.job=f.submit()['jobId']
        f.mark_running(self.job)
        f.attempt(self.job).mkdir()
        self.original=f.attempt(self.job)/'incomplete.private.log'
        self.original.write_bytes(b'preserved interrupted synthetic attempt\n')
        f.restart()
        f.now=f.service.get(self.job)['retryAt']
        self.intent={'requestId':'7'*64,'expectedAttempts':1}

    def test_lost_retry_reply_and_restart_do_not_repeat_a_later_failed_attempt(self):
        f=self.fixture
        self.assertEqual(f.service.control(self.job,'retry',self.intent)['state'],'queued')
        f.restart()
        self.assertEqual(f.service.control(self.job,'retry',self.intent)['state'],'queued')
        def failed(*_):
            raise RuntimeError('synthetic native failure, preserved by auditor')
        f.run_next(failed)
        result=f.service.get(self.job)
        self.assertEqual((result['state'],result['attempts']),('failed',2))
        f.now=result['retryAt']
        f.restart()
        self.assertEqual(f.service.control(self.job,'retry',self.intent)['state'],'failed')
        self.assertFalse(f.run_next())
        with f.service.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM retry_intents').fetchone()[0],1)
        self.assertEqual(self.original.read_bytes(),b'preserved interrupted synthetic attempt\n')
        next_intent={'requestId':'8'*64,'expectedAttempts':2}
        self.assertEqual(f.service.control(self.job,'retry',next_intent)['state'],'queued')
        f.run_next()
        self.assertEqual(f.service.get(self.job)['attempts'],3)
        self.assertEqual(f.service.get(self.job)['state'],'approved')
        self.assertEqual(f.service.control(self.job,'retry',self.intent)['state'],'approved')
        self.assertFalse(f.run_next())

    def test_changed_nonce_identity_and_stale_attempt_cannot_queue_work(self):
        f=self.fixture
        f.service.control(self.job,'retry',self.intent)
        with self.assertRaisesRegex(jobs.JobError,'object_job_control_conflict'):
            f.service.control(self.job,'retry',{**self.intent,'expectedAttempts':2})
        with self.assertRaisesRegex(jobs.JobError,'object_job_control_conflict'):
            f.service.control(self.job,'retry',{'requestId':'8'*64,'expectedAttempts':1})
        for change in [{'expectedAttempts':True},{'expectedAttempts':3},{'requestId':'short'},{'extra':'private'}]:
            with self.assertRaisesRegex(jobs.JobError,'invalid_object_job'):
                f.service.control(self.job,'retry',{**self.intent,**change})
        with f.service.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM retry_intents').fetchone()[0],1)

    def test_late_receipt_failure_rolls_back_queue_and_nonce(self):
        f=self.fixture
        with f.service.connect() as db:
            db.execute("CREATE TRIGGER injected BEFORE INSERT ON retry_intents BEGIN SELECT RAISE(ABORT,'synthetic_late_failure'); END")
        with self.assertRaisesRegex(Exception,'synthetic_late_failure'):
            f.service.control(self.job,'retry',self.intent)
        self.assertEqual(f.service.get(self.job)['state'],'failed')
        with f.service.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM retry_intents').fetchone()[0],0)
        self.assertEqual(self.original.read_bytes(),b'preserved interrupted synthetic attempt\n')

    def test_assignment_revocation_beats_a_saved_retry_nonce(self):
        f=self.fixture
        f.service.control(self.job,'retry',self.intent)
        f.service.erase_assignment(f.body['leaseId'])
        self.assertEqual(f.service.control(self.job,'retry',self.intent)['state'],'erasing')
        self.assertTrue(f.service.erase_next())
        f.restart()
        self.assertEqual(f.service.control(self.job,'retry',self.intent)['state'],'erased')
        self.assertFalse(f.run_next())

    def test_concurrent_retry_replays_commit_one_nonce_and_queue_once(self):
        f=self.fixture
        with ThreadPoolExecutor(max_workers=4) as pool:
            values=list(pool.map(lambda _:f.service.control(self.job,'retry',self.intent),range(4)))
        self.assertTrue(all(value['state']=='queued' and value['attempts']==1 for value in values))
        with f.service.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM retry_intents').fetchone()[0],1)
        f.run_next()
        self.assertEqual(f.service.get(self.job)['attempts'],2)
        self.assertFalse(f.run_next())

if __name__=='__main__':
    unittest.main()
