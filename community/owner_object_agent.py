"""Inert outbound Object verification transport and crash-safe finite agent.

No activation, task, listener, credential provisioning or download is installed.
The cost hold forbids real invocation. The coordinator owns publication/credit;
the existing independently pinned local auditor owns native work/protection.
"""
from __future__ import annotations

import base64
import copy
import http.client
import os
from pathlib import Path
import re
import time

from .native_scene_search import plain_path, strict_json
from .native_scene_verifier import field_bytes
from .object_audit_jobs import MAX_REQUEST
from .owner_object_verifier import job_response,EVIDENCE_KEYS
from .owner_search_agent import OwnerSearchError,_exclusive
from .owner_search_credentials import canonical_origin
from .search_snapshot import bounded_read,digest,encoded,resource_for_environment

ID=re.compile(r'[0-9a-f]{32}\Z');HEX=re.compile(r'[0-9a-f]{64}\Z')
MAX_OUTBOX=98304;ROUTES={'claim','candidate','complete','fail'}
BINDING_KEYS={'version','scope','policyId','policySha256','runtimeProfileSha256','qualityImplementationIdentity',
              'protectedAuthoritySha256','protectedOriginHandoffSha256','profiles','resource'}
JOB_KEYS={'version','leaseId','claimToken','claimUntil','binding','profileId','assignmentSha256','sourceSha256',
          'submissionSha256','payloadBytes','locations','jobId','candidateManifestSha256','nativeAttempts'}


def require(value,code='invalid_owner_object_reply'):
    if not value:raise OwnerSearchError(code)


def binding(value):
    require(isinstance(value,dict) and set(value)==BINDING_KEYS
        and type(value['version']) is int and value['version']==1 and value['scope']=='object-batch-parity-v1'
        and isinstance(value['policyId'],str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,128}',value['policyId'])
        and all(isinstance(value[k],str) and HEX.fullmatch(value[k]) for k in BINDING_KEYS
                if k.endswith('Sha256') or k=='qualityImplementationIdentity')
        and isinstance(value['profiles'],list) and 1<=len(value['profiles'])<=16
        and all(isinstance(v,str) and HEX.fullmatch(v) for v in value['profiles'])
        and len(set(value['profiles']))==len(value['profiles'])
        and value['resource'] in [resource_for_environment(e) for e in ('staging','production')]
        and (not value['policyId'].startswith('staging.') or value['resource']['bucket']=='vision-community-staging'),
        'owner_binding_configuration_required')
    return copy.deepcopy(value)


class HTTPSObjectCoordinator:
    """Fixed origin/routes and bounded JSON. No redirect, proxy or search-key use."""
    def __init__(self,origin,secret):
        self.origin=canonical_origin(origin);self.host=self.origin[8:]
        require(isinstance(secret,str) and HEX.fullmatch(secret),'owner_credentials_unavailable')
        self.secret=secret

    @classmethod
    def from_os_credentials(cls,origin):
        from .owner_object_credentials import read_owner_object_secret
        try:return cls(origin,read_owner_object_secret(origin))
        except Exception:raise OwnerSearchError('owner_credentials_unavailable') from None

    def post(self,action,value):
        require(action in ROUTES,'invalid_owner_route')
        raw=encoded(value);require(len(raw)<= (MAX_OUTBOX if action=='complete' else 8192),'owner_payload_limit')
        connection=http.client.HTTPSConnection(self.host,port=443,timeout=30)
        try:
            connection.request('POST','/api/object-audit-agent/'+action,body=raw,
                headers={'Authorization':'Bearer '+self.secret,'Content-Type':'application/json','Accept':'application/json'})
            response=connection.getresponse()
            limit=(MAX_REQUEST if action=='candidate' else 8192 if action=='claim' else 4096) if response.status==200 else 4096
            payload=response.read(limit+1);require(len(payload)<=limit,'owner_reply_limit')
            document=strict_json(payload);require(isinstance(document,dict))
            if response.status!=200:
                code='owner_protocol_configuration_required' if response.status in {400,404,405,409,413,422} else 'coordinator_unavailable'
                if response.status==409:
                    code={'owner_object_claim_lost':'object_claim_lost',
                          'owner_object_evidence_refresh_required':'object_evidence_refresh_required',
                          'owner_object_binding_required':'owner_binding_configuration_required',
                          'owner_object_binding_changed':'owner_binding_configuration_required',
                          'object_settlement_policy_mismatch':'owner_binding_configuration_required'}.get(document.get('error'),code)
                raise OwnerSearchError(code,response.status)
            return payload if action=='candidate' else document
        except OwnerSearchError:raise
        except Exception:raise OwnerSearchError('coordinator_unavailable') from None
        finally:connection.close()


class OwnerObjectAuditAgent:
    def __init__(self,coordinator,engine,state,independent_binding,*,guard,clock=time.time):
        require(callable(getattr(coordinator,'post',None)) and callable(getattr(engine,'handle',None))
            and callable(getattr(engine,'work_once',None)) and callable(guard),'owner_object_configuration_required')
        self.coordinator,self.engine,self.guard,self.clock=coordinator,engine,guard,clock
        self.binding=binding(independent_binding)
        self.state=plain_path(Path(state),directory=True)
        source=Path(__file__).absolute().parents[1]
        require(self.state!=source and source not in self.state.parents and self.state not in source.parents,
                'owner_object_private_state_required')
        work=getattr(getattr(engine,'jobs',None),'work',None)
        if isinstance(work,Path):
            require(self.state!=work and work not in self.state.parents and self.state not in work.parents,
                    'owner_object_private_state_required')
        self.outbox=self.state/'object-outbox.json';self.pending=self.state/'object-outbox.pending'

    def _now(self):
        value=self.clock();require(type(value) in (int,float) and 0<=value<=253402290000,'owner_clock_invalid')
        return int(value)

    def _paused(self):
        marker=getattr(self.engine,'_marker',None)
        return any((self.state/n).exists() for n in ('PAUSE','STOP')) or (callable(marker) and bool(marker()))

    def _report(self,code):
        require(code in {'owner_object_failed','object_outbox_incomplete'})
        try:
            fd=os.open(self.state/('failure-'+code+'.json'),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'wb') as stream:
                stream.write(encoded({'success':False,'error':code}));stream.flush();os.fsync(stream.fileno())
        except FileExistsError:pass

    @staticmethod
    def _document(value):
        require(isinstance(value,dict) and set(value)=={'action','body'} and value['action'] in {'complete','fail'},'invalid_owner_outbox')
        b=value['body'];require(isinstance(b,dict) and set(b)==({'leaseId','claimToken','audit','evidence'} if value['action']=='complete'
                                                        else {'leaseId','claimToken','reason'}),'invalid_owner_outbox')
        require(all(isinstance(b[k],str) and ID.fullmatch(b[k]) for k in ('leaseId','claimToken')),'invalid_owner_outbox')
        if value['action']=='complete':
            require(job_response(b['audit']) and b['audit']['leaseId']==b['leaseId'],'invalid_owner_outbox')
            e=b['evidence']
            require(e is None or isinstance(e,dict) and set(e)==EVIDENCE_KEYS and e['audit']==b['audit']
                and type(e['issuedAt']) is int and e['issuedAt']>=0 and type(e['expiresAt']) is int and e['expiresAt']==e['issuedAt']+30
                and e['qualificationScope']=='batch-only' and e['resource'] in [resource_for_environment(x) for x in ('staging','production')]
                and all(isinstance(e[k],str) and HEX.fullmatch(e[k]) for k in EVIDENCE_KEYS
                        if k.endswith('Sha256') or k=='qualityImplementationIdentity'),'invalid_owner_outbox')
        else:require(b['reason'] in {'busy','unavailable'},'invalid_owner_outbox')
        require(len(encoded(value))<=MAX_OUTBOX,'owner_payload_limit')
        return value

    @staticmethod
    def _same_completion(left,right):
        return left['action']==right['action']=='complete' and all(left['body'][k]==right['body'][k] for k in ('leaseId','claimToken','audit'))

    def _save(self,action,body,*,refresh=False):
        value=self._document({'action':action,'body':body})
        if refresh:
            old=self._document(strict_json(bounded_read(plain_path(self.outbox),MAX_OUTBOX)))
            require(self._same_completion(old,value),'invalid_owner_outbox')
            backup=self.state/'object-outbox-before-refresh.private.json'
            try:
                fd=os.open(backup,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with os.fdopen(fd,'wb') as stream:
                    stream.write(encoded(old));stream.flush();os.fsync(stream.fileno())
            except FileExistsError:plain_path(backup)
        else:require(not self.outbox.exists(),'invalid_owner_outbox')
        fd=os.open(self.pending,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as stream:
            stream.write(encoded(value));stream.flush();os.fsync(stream.fileno())
        os.replace(self.pending,self.outbox)

    def _recover(self):
        if not self.pending.exists():return
        path=plain_path(self.pending)
        try:value=self._document(strict_json(bounded_read(path,MAX_OUTBOX)))
        except (ValueError,OSError):
            self._report('object_outbox_incomplete')
            archive=self.state/'object-outbox-incomplete.private'
            require(not archive.exists(),'invalid_owner_outbox')
            os.replace(path,archive)  # Preserve the incomplete bytes; never delivered.
            return
        if self.outbox.exists():
            old=self._document(strict_json(bounded_read(plain_path(self.outbox),MAX_OUTBOX)))
            require(self._same_completion(old,value),'invalid_owner_outbox')
        os.replace(path,self.outbox)

    def _native(self,method,path,raw=None):
        self.guard();require(not self._paused(),'owner_object_paused')
        status,value=self.engine.handle(method,path,raw)
        if status!=200:
            if self._paused():raise OwnerSearchError('owner_object_paused')
            if status==503 and value=={'error':'object_job_queue_full'}:raise OwnerSearchError('object_queue_busy')
            raise OwnerSearchError('owner_object_verification_unavailable')
        return value

    def _audit(self,audit,job):
        require(job_response(audit) and all(audit[k]==wanted for k,wanted in {
            'leaseId':job['leaseId'],'profileId':job['profileId'],'policyId':self.binding['policyId'],
            'assignmentSha256':job['assignmentSha256'],'submissionSha256':job['submissionSha256']}.items()))
        require(audit['attempts']>=job['nativeAttempts'])
        if job['jobId'] is not None:require(audit['jobId']==job['jobId'] and audit['candidateManifestSha256']==job['candidateManifestSha256'])
        return audit

    def _proof(self,audit):
        proof=self._native('POST','/object-audits/'+audit['jobId']+'/settlement-evidence',b'{}')
        self._document({'action':'complete','body':{'leaseId':audit['leaseId'],'claimToken':'0'*32,'audit':audit,'evidence':proof}})
        require(proof['issuedAt']<=self._now()<proof['expiresAt'])
        require(all(proof[k]==self.binding[k] for k in BINDING_KEYS if k.endswith('Sha256') or k=='qualityImplementationIdentity')
                and proof['resource']==self.binding['resource'],'owner_binding_configuration_required')
        return proof

    def _deliver(self):
        if self._paused():return {'status':'paused'}
        value=self._document(strict_json(bounded_read(plain_path(self.outbox),MAX_OUTBOX)))
        self.guard()
        try:
            reply=self.coordinator.post(value['action'],value['body'])
        except OwnerSearchError as error:
            if error.code=='object_claim_lost' and error.status==409:
                self.outbox.unlink();return {'status':'claim_lost'}
            if error.code!='object_evidence_refresh_required' or error.status!=409 or value['action']!='complete':raise
            # FIRST replay the exact old completion: an already committed award
            # does not need current native files or renewed proof. Only this
            # explicit uncommitted response permits real protection revalidation.
            audit=value['body']['audit'];proof=self._proof(audit)
            self._save('complete',{**value['body'],'evidence':proof},refresh=True)
            if self._paused():return {'status':'paused'}
            self.guard()
            try:reply=self.coordinator.post('complete',{**value['body'],'evidence':proof})
            except OwnerSearchError as again:
                if again.code=='object_claim_lost' and again.status==409:
                    self.outbox.unlink();return {'status':'claim_lost'}
                raise
        if value['action']=='fail':
            require(isinstance(reply,dict) and set(reply)=={'failed','charged','retryAt','needsAttention'}
                and reply['failed'] is True and reply['charged'] is False and type(reply['retryAt']) is int
                and type(reply['needsAttention']) is bool,'invalid_owner_reply')
            result={'status':'idle' if value['body']['reason']=='busy' else 'failed',
                    'retryAfterSeconds':max(30,min(3600,reply['retryAt']-self._now()))}
        else:
            allowed={'completed','submissionId','accepted','unitsEarned','replayed','pendingAudit','auditState','qualificationScope',
                'pending','rejected','cancelled','freshAuditReply','retryAt','needsAttention','waitingForCapacity','auditProtocol',
                'productionQualified','serverAuthorization'}
            require(isinstance(reply,dict) and not set(reply)-allowed and reply.get('completed') is True
                and reply.get('submissionId')==value['body']['leaseId'] and type(reply.get('accepted')) is int
                and 0<=reply['accepted']<=4 and type(reply.get('unitsEarned')) is int
                and reply['unitsEarned'] in (0,reply['accepted']*10) and type(reply.get('pendingAudit')) is bool,
                'invalid_owner_reply')
            result={'status':'completed','accepted':reply['accepted'],'unitsEarned':reply['unitsEarned']}
        self.outbox.unlink();return result

    def _claim(self,reply):
        require(isinstance(reply,dict))
        job=reply.get('job')
        if job is None:
            require(reply=={'job':None,'retryAfterSeconds':30});return None
        require(set(reply)=={'job'} and isinstance(job,dict) and set(job)==JOB_KEYS)
        require(type(job['version']) is int and job['version']==1 and binding(job['binding'])==self.binding)
        require(all(isinstance(job[k],str) and ID.fullmatch(job[k]) for k in ('leaseId','claimToken'))
            and all(isinstance(job[k],str) and HEX.fullmatch(job[k]) for k in ('profileId','assignmentSha256','sourceSha256','submissionSha256'))
            and job['profileId'] in self.binding['profiles'] and type(job['locations']) is int and 1<=job['locations']<=4
            and type(job['payloadBytes']) is int and 1<=job['payloadBytes']<=MAX_REQUEST-1024
            and type(job['claimUntil']) is int and self._now()<job['claimUntil']<=self._now()+1200
            and type(job['nativeAttempts']) is int and 0<=job['nativeAttempts']<=3)
        require(job['jobId'] is None and job['candidateManifestSha256'] is None or isinstance(job['jobId'],str)
            and ID.fullmatch(job['jobId']) and isinstance(job['candidateManifestSha256'],str) and HEX.fullmatch(job['candidateManifestSha256']))
        return job

    def run_once(self):
        if self._paused():return {'status':'paused'}
        with _exclusive(self.state):
            if self._paused():return {'status':'paused'}
            self.guard();self._recover()
            if self.outbox.exists():return self._deliver()
            job=self._claim(self.coordinator.post('claim',{'binding':self.binding}))
            if job is None:return {'status':'idle','retryAfterSeconds':30}
            body={'leaseId':job['leaseId'],'claimToken':job['claimToken']}
            try:
                if job['jobId'] is None:
                    self.guard();raw=self.coordinator.post('candidate',body)
                    require(isinstance(raw,bytes) and 0<len(raw)<=MAX_REQUEST)
                    candidate=strict_json(raw)
                    require(isinstance(candidate,dict) and set(candidate)=={'version','leaseId','profileId','policyId',
                        'assignmentSha256','submissionSha256','objectIndex'} and type(candidate['version']) is int and candidate['version']==1)
                    require(all(candidate[k]==v for k,v in {**{k:job[k] for k in ('leaseId','profileId','assignmentSha256','submissionSha256')},
                        'policyId':self.binding['policyId']}.items()))
                    require(digest(field_bytes(raw,'objectIndex'))==job['submissionSha256'])
                    require(digest(base64.b64decode(candidate['objectIndex']['sourceTsv'],validate=True))==job['sourceSha256'])
                    audit=self._audit(self._native('POST','/object-audits',raw),job)
                else:audit=self._audit(self._native('GET','/object-audits/'+job['jobId']),job)
                if audit['state']=='queued':
                    self.guard();worked=self.engine.work_once()
                    if self._paused():raise OwnerSearchError('owner_object_paused')
                    require(worked.get('status') in {'worked','idle'},'owner_object_verification_unavailable')
                    audit=self._audit(self._native('GET','/object-audits/'+audit['jobId']),job)
                require(audit['state'] in {'staging','queued','running','approved','rejected','failed'},'owner_object_verification_unavailable')
                proof=self._proof(audit) if audit['state']=='approved' else None
                self._save('complete',{**body,'audit':audit,'evidence':proof})
            except Exception as error:
                if self.outbox.exists() or self.pending.exists():raise OwnerSearchError('owner_outbox_recovery_required') from None
                if isinstance(error,OwnerSearchError) and error.code=='owner_object_paused':return {'status':'paused'}
                busy=isinstance(error,OwnerSearchError) and error.code=='object_queue_busy'
                if not busy:self._report('owner_object_failed')
                self._save('fail',{**body,'reason':'busy' if busy else 'unavailable'})
            return self._deliver()
