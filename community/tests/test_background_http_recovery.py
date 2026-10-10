"""Real loopback HTTP/SQLite delivery across fresh Python processes.

Synthetic output only: no models, native inference, qualification, new accounts,
public service calls or actual credits. Storage pressure prevents new work.
"""
import json
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest

from community.contribute import save_session

REPO=Path(__file__).resolve().parents[2]
ACCOUNT='a'*32
LEASE='b'*32
CODE='fixture-private-recovery-code'
OUTPUTS=[{'locationId':1,'embedding':'synthetic saved output'}]
CHILD="""
import json,sys
from pathlib import Path
from community.background import BackgroundContributor,ProcessingSchedule,single_instance
from community.desktop import DesktopClient
from community.contribute import ContributeError
root,url,mode,now=Path(sys.argv[1]),sys.argv[2],sys.argv[3],float(sys.argv[4])
if mode=='seed':
    client=DesktopClient(url)
    client.enable_outbox(root/'indexes','a'*32)
    try: print(json.dumps(client.submit('b'*32,[{'locationId':1,'embedding':'synthetic saved output'}])))
    except ContributeError as error: print(json.dumps({'code':error.code}))
else:
    worker=BackgroundContributor(root,url=url,storage_limit_gb=1,prevent_sleep=False,
        schedule=ProcessingSchedule(day_pace='max',night_pace='max'),wall_clock=lambda:now)
    worker.storage_limit_bytes=1
    worker.storage['limitBytes']=1
    with single_instance(root):worker.run(once=True)
    print(json.dumps({'state':worker.last_state,'accepted':worker.completed}))
"""

class BackgroundHTTPRestartTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name).resolve()
        self.calls=[]
        self.phase='drop-submit'
        self.saved={}
        self.awards=set()
        self.cohort_only=False
        self.contributions_closed=False
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*_args):pass
            def send(self,status,value,*,partial=False,cookie=False):
                raw=json.dumps(value).encode()
                self.send_response(status)
                self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(raw)+100 if partial else len(raw)))
                if cookie:self.send_header('Set-Cookie','vision_session=fixture-token; Path=/')
                self.send_header('Connection','close')
                self.end_headers()
                self.wfile.write(raw[:5] if partial else raw)
                self.wfile.flush()
                self.close_connection=True
                if partial:
                    try:self.connection.shutdown(socket.SHUT_WR)
                    except OSError:pass
            def do_GET(self):
                owner.calls.append(('GET',self.path,None))
                if self.path=='/api/capabilities':
                    allowed=not owner.contributions_closed and (not owner.cohort_only
                        or self.headers.get('Authorization')=='Bearer fixture-token')
                    return self.send(200,{'version':1,'sceneContributions':{
                        'model':'vision-four-view-v4','ready':allowed,
                        'deviceQualificationRequired':True,'canaryLocations':112}})
                if self.path=='/api/me':
                    return self.send(200,{'accountId':ACCOUNT,'units':len(owner.awards)})
                self.send(404,{'error':'unexpected_fixture_request'})
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.calls.append(('POST',self.path,body))
                if self.path=='/api/recovery':
                    if body!={'recoveryCode':CODE}:return self.send(401,{'error':'unauthorized'})
                    return self.send(200,{'accountId':ACCOUNT},cookie=True)
                if self.path=='/api/submissions':
                    lease=body['leaseId']
                    existing=owner.saved.setdefault(lease,body['outputs'])
                    if existing!=body['outputs']:return self.send(409,{'error':'payload_changed'})
                    return self.send(200,{'pendingAudit':True,'submissionId':lease,
                        'accepted':0,'unitsEarned':0},partial=owner.phase=='drop-submit')
                if self.path=='/api/scene-audits':
                    if owner.phase=='redirect-audit':
                        self.send_response(307)
                        self.send_header('Location','/redirected-private-audit')
                        self.send_header('Content-Length','0')
                        self.end_headers()
                        return
                    if owner.phase=='malformed-audit':
                        return self.send(200,{'accepted':-1,'unitsEarned':0,'pendingAudit':False})
                    if owner.phase=='audit-outage':
                        return self.send(503,{'error':'scene_verifier_unavailable'})
                    if owner.phase=='private-audit-error':
                        return self.send(503,{'error':CODE})
                    if owner.phase=='reject':
                        return self.send(200,{'rejected':True,'accepted':0,'unitsEarned':0})
                    if owner.phase=='unauthorized-partial':
                        return self.send(401,{'error':'unauthorized'},partial=True)
                    if owner.phase=='error-partial':
                        return self.send(503,{'error':'scene_verifier_unavailable'},partial=True)
                    lease=body['submissionId']
                    if lease not in owner.saved:return self.send(404,{'error':'unknown_submission'})
                    owner.awards.add(lease)
                    return self.send(200,{'accepted':1,'unitsEarned':1,'pendingAudit':False},
                        partial=owner.phase=='drop-audit')
                self.send(404,{'error':'unexpected_fixture_request'})
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.server.daemon_threads=True
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.addCleanup(self.close)
        self.url='http://127.0.0.1:'+str(self.server.server_port)
        save_session(self.root/'account.json',url=self.url,account_id=ACCOUNT,recovery_code=CODE)
        self.account_bytes=(self.root/'account.json').read_bytes()

    def test_redirected_saved_audit_preserves_work_across_fresh_workers_and_cooldown(self):
        self.phase='pending'
        self.assertEqual(self.child('seed'),{'pendingAudit':True,'submissionId':LEASE,'accepted':0,'unitsEarned':0})
        saved=self.row()
        self.phase='redirect-audit'
        self.assertEqual(self.child(),{'state':'waiting_for_service','accepted':0})
        self.assertEqual(self.row(),saved)
        self.assertEqual(self.awards,set())
        self.assertFalse((self.root/'NEEDS-ATTENTION').exists())
        self.assertEqual(json.loads((self.root/'desktop-failure.json').read_text())['code'],'service_redirect_refused')
        calls=len(self.calls)
        self.phase='pending'
        self.assertEqual(self.child(now=10001),{'state':'waiting_for_service','accepted':0})
        self.assertEqual(len(self.calls),calls)
        self.assertEqual(self.child(now=11800),{'state':'waiting_for_space','accepted':1})
        self.assertEqual(self.awards,{LEASE})
        self.assertEqual(self.row()[0],'accepted')
        self.assertIsNone(self.row()[1])
        self.assertFalse(any(path=='/redirected-private-audit' for _,path,_ in self.calls))
        calls=len(self.calls)
        self.assertEqual(self.child(now=11860),{'state':'waiting_for_space','accepted':0})
        self.assertFalse(any(path=='/api/scene-audits' for _,path,_ in self.calls[calls:]))
        self.assert_private_and_no_new_work()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def test_saved_identity_can_recover_before_invitation_check_without_new_account_or_native_work(self):
        from community.background import BackgroundContributor
        self.cohort_only=True
        worker=BackgroundContributor(self.root,url=self.url,storage_limit_gb=1,prevent_sleep=False)
        worker.storage_limit_bytes=1
        worker.storage['limitBytes']=1
        worker.run(once=True)
        self.assertEqual(worker.last_state,'waiting_for_space')
        self.assertEqual(worker.completed,0)
        self.assertEqual(self.calls[0][:2],('POST','/api/recovery'))
        self.assertNotIn('/api/accounts',[call[1] for call in self.calls])
        self.assertNotIn('/api/leases',[call[1] for call in self.calls])

    def test_guided_account_recovery_remains_available_after_contributions_close(self):
        from community.desktop import DesktopApp
        self.contributions_closed=True
        app=DesktopApp(self.root,url=self.url)
        self.assertEqual(app.connect(CODE),{'connected':True})
        self.assertTrue(app.state['connected'])
        self.assertFalse(app.state['serviceReady'])
        self.assertFalse(app.state['qualified'])
        self.assertNotIn(CODE,app.state['message'])
        self.assertNotIn('/api/accounts',[call[1] for call in self.calls])

    def test_unexpected_private_error_is_redacted_and_recovers_across_fresh_workers(self):
        self.phase='pending'
        self.child('seed')
        saved=self.row()
        self.phase='private-audit-error'
        self.assertEqual(self.child(),{'state':'waiting_for_service','accepted':0})
        self.assertEqual(self.row(),saved)
        report=json.loads((self.root/'desktop-failure.json').read_text())
        self.assertEqual((report['code'],report['http_status']),('http_error',503))
        self.assertFalse((self.root/'NEEDS-ATTENTION').exists())
        self.assertEqual(self.awards,set())
        self.assert_private_and_no_new_work()
        calls=len(self.calls)
        self.phase='ack'
        self.assertEqual(self.child(now=11000),{'state':'waiting_for_service','accepted':0})
        self.assertEqual(len(self.calls),calls)
        self.assertEqual(self.child(now=11800),{'state':'waiting_for_space','accepted':1})
        self.assertEqual(self.row()[0],'accepted')
        self.assertIsNone(self.row()[1])
        self.assertEqual(self.awards,{LEASE})
        self.assert_private_and_no_new_work()

    def child(self,mode='recover',now=10000):
        completed=subprocess.run([sys.executable,'-B','-c',CHILD,str(self.root),self.url,mode,str(now)],
            cwd=REPO,capture_output=True,text=True,timeout=30,
            creationflags=0x08000000 if os.name=='nt' else 0)
        self.assertEqual(completed.returncode,0,completed.stderr)
        return json.loads(completed.stdout)

    def row(self):
        with closing(sqlite3.connect(self.root/'indexes/submissions.sqlite')) as connection:
            return connection.execute('SELECT state,payload_json,result_json FROM deliveries').fetchone()

    def assert_private_and_no_new_work(self):
        self.assertEqual((self.root/'account.json').read_bytes(),self.account_bytes)
        self.assertFalse((self.root/'runtime').exists())
        self.assertFalse(any(path in ('/api/accounts','/api/leases','/api/scene-qualifications')
                             for _method,path,_body in self.calls))
        for path in ('background-status.json','desktop-failure.json','background-retry.json'):
            if (self.root/path).exists():self.assertNotIn(CODE,(self.root/path).read_text())
        self.assertNotIn(CODE.encode(),(self.root/'indexes/submissions.sqlite').read_bytes())

    def test_malformed_success_preserves_work_across_processes_and_recovers_after_cooldown(self):
        self.phase='audit-outage'
        self.assertTrue(self.child('seed')['pendingAudit'])
        before=self.row()
        self.phase='malformed-audit'
        self.assertEqual(self.child(),{'state':'waiting_for_service','accepted':0})
        self.assertEqual(self.row(),before)
        self.assertEqual(self.awards,set())
        self.assertFalse((self.root/'NEEDS-ATTENTION').exists())
        self.assertEqual(json.loads((self.root/'desktop-failure.json').read_text())['code'],'invalid_submission_result')
        self.assertEqual(json.loads((self.root/'background-retry.json').read_text())['nextAttemptAt'],11800)
        calls=len(self.calls)
        self.assertEqual(self.child(now=11000),{'state':'waiting_for_service','accepted':0})
        self.assertEqual(len(self.calls),calls)
        self.phase='ack'
        self.assertEqual(self.child(now=11800),{'state':'waiting_for_space','accepted':1})
        self.assertEqual(self.row()[0],'accepted')
        self.assertIsNone(self.row()[1])
        self.assertEqual(self.awards,{LEASE})
        calls=len(self.calls)
        self.assertEqual(self.child(now=11860),{'state':'waiting_for_space','accepted':0})
        self.assertFalse(any(path=='/api/scene-audits' for _method,path,_body in self.calls[calls:]))
        self.assert_private_and_no_new_work()

    def test_partial_replies_and_outage_recover_across_processes_without_duplicate_award(self):
        self.assertEqual(self.child('seed'),{'code':'network_error'})
        self.assertEqual(self.row()[0],'ready')
        self.assertEqual(self.saved,{LEASE:OUTPUTS})
        self.phase='audit-outage'
        self.assertEqual(self.child(),{'state':'waiting_for_service','accepted':0})
        self.assertEqual(self.row()[0],'pending')
        retry=json.loads((self.root/'background-retry.json').read_text())
        self.assertEqual(retry['nextAttemptAt'],11800)
        calls=len(self.calls)
        self.assertEqual(self.child(now=11000),{'state':'waiting_for_service','accepted':0})
        self.assertEqual(len(self.calls),calls)
        self.phase='drop-audit'
        self.assertEqual(self.child(now=11800),{'state':'waiting_for_service','accepted':0})
        self.assertEqual(self.awards,{LEASE})
        self.assertEqual(self.row()[0],'pending')
        self.assertEqual(json.loads(self.row()[1]),OUTPUTS)
        self.assertFalse((self.root/'NEEDS-ATTENTION').exists())
        self.phase='ack'
        self.assertEqual(self.child(now=13600),{'state':'waiting_for_space','accepted':1})
        row=self.row()
        self.assertEqual(row[0],'accepted')
        self.assertIsNone(row[1])
        self.assertEqual(json.loads(row[2])['unitsEarned'],1)
        audit_calls=sum(path=='/api/scene-audits' for _method,path,_body in self.calls)
        self.assertEqual(self.child(now=13660),{'state':'waiting_for_space','accepted':0})
        self.assertEqual(sum(path=='/api/scene-audits' for _method,path,_body in self.calls),audit_calls)
        self.assertEqual(self.awards,{LEASE})
        self.assert_private_and_no_new_work()

    def test_terminal_rejection_preserves_payload_and_does_not_retry_after_restart(self):
        self.phase='audit-outage'
        self.child('seed')
        self.phase='reject'
        self.assertEqual(self.child(),{'state':'needs_attention','accepted':0})
        self.assertEqual(self.row()[0],'rejected')
        self.assertEqual(json.loads(self.row()[1]),OUTPUTS)
        original=(self.root/'desktop-failure.json').read_bytes()
        calls=len(self.calls)
        self.assertEqual(self.child(now=90000),{'state':'needs_attention','accepted':0})
        self.assertEqual(len(self.calls),calls)
        self.assertEqual((self.root/'desktop-failure.json').read_bytes(),original)
        self.assertEqual(self.awards,set())
        self.assert_private_and_no_new_work()

    def test_clock_rollback_keeps_saved_delivery_and_recovers_after_bounded_cooldown(self):
        self.phase='pending'
        self.child('seed')
        self.phase='audit-outage'
        self.assertEqual(self.child(),{'state':'waiting_for_service','accepted':0})
        saved=self.row()
        failure=(self.root/'desktop-failure.json').read_bytes()
        calls=len(self.calls)
        self.phase='ack'
        self.assertEqual(self.child(now=1000),{'state':'waiting_for_service','accepted':0})
        self.assertEqual(json.loads((self.root/'background-retry.json').read_text())['nextAttemptAt'],2800)
        self.assertEqual(self.child(now=2799),{'state':'waiting_for_service','accepted':0})
        self.assertEqual(len(self.calls),calls)
        self.assertEqual(self.row(),saved)
        self.assertEqual((self.root/'desktop-failure.json').read_bytes(),failure)
        self.assertEqual(self.child(now=2800),{'state':'waiting_for_space','accepted':1},
            (self.root/'desktop-failure.json').read_text())
        self.assertEqual(self.child(now=2860),{'state':'waiting_for_space','accepted':0})
        self.assertEqual(self.awards,{LEASE})
        self.assertEqual((self.root/'desktop-failure.json').read_bytes(),failure)
        self.assert_private_and_no_new_work()

    def test_partial_service_error_is_transient_and_preserves_pending_output(self):
        self.phase='audit-outage';self.child('seed')
        self.phase='error-partial'
        self.assertEqual(self.child(),{'state':'waiting_for_service','accepted':0})
        self.assertEqual(self.row()[0],'pending')
        self.assertEqual(json.loads(self.row()[1]),OUTPUTS)
        self.assertFalse((self.root/'NEEDS-ATTENTION').exists())
        self.assert_private_and_no_new_work()

    def test_partial_unauthorized_error_retains_status_and_stops(self):
        self.phase='audit-outage';self.child('seed')
        self.phase='unauthorized-partial'
        self.assertEqual(self.child(),{'state':'needs_attention','accepted':0})
        failure=json.loads((self.root/'desktop-failure.json').read_text())
        self.assertEqual(failure['code'],'http_error')
        self.assertEqual(self.row()[0],'pending')
        self.assert_private_and_no_new_work()

if __name__=='__main__':unittest.main()

