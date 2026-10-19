"""Inert outbound published-job cleanup. No inference or financial authority.

Native jobs own file paths and deletion guards. The coordinator supplies the
immutable accepted identity. Account deletion remains a separate stronger path.
"""
import os
from pathlib import Path
import re

from .native_scene_search import plain_path, strict_json
from .owner_object_agent import ID,HEX,binding,require
from .owner_object_verifier import job_response
from .owner_search_agent import _exclusive,OwnerSearchError
from .search_snapshot import bounded_read,encoded

LIMIT=8192
COMMAND={'version','policyId','profileId','leaseId','jobId','requestSha256','body'}
BODY={'version','leaseId','assignmentSha256','submissionSha256','candidateManifestSha256','receiptSha256','attempts','acceptanceSha256'}


def command(value):
    require(isinstance(value,dict) and set(value)==COMMAND and type(value['version']) is int and value['version']==1
        and isinstance(value['policyId'],str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,128}',value['policyId'])
        and all(isinstance(value[k],str) and ID.fullmatch(value[k]) for k in ('leaseId','jobId'))
        and all(isinstance(value[k],str) and HEX.fullmatch(value[k]) for k in ('requestSha256','profileId')),'invalid_owner_retirement')
    b=value['body']
    require(isinstance(b,dict) and set(b)==BODY and type(b['version']) is int and b['version']==1
        and b['leaseId']==value['leaseId'] and type(b['attempts']) is int and 1<=b['attempts']<=3
        and all(isinstance(b[k],str) and HEX.fullmatch(b[k]) for k in BODY if k.endswith('Sha256')),'invalid_owner_retirement')
    return value


def checked_audit(value,c):
    require(job_response(value) and all(value[k]==v for k,v in {
        'jobId':c['jobId'],'leaseId':c['leaseId'],'policyId':c['policyId'],'profileId':c['profileId'],
        **{k:c['body'][k] for k in ('assignmentSha256','submissionSha256','candidateManifestSha256','attempts')}
        }.items()) and value['state'] in {'retiring','retired','erasing','erased'}
        and (value['state'] in {'erasing','erased'} or value['receiptSha256']==c['body']['receiptSha256']),
        'invalid_owner_retirement')
    return value


class OwnerObjectRetirementAgent:
    """Optional finite wrapper. Exact audit replies win before maintenance.

    A pending command is flushed before native cleanup; a completed native reply
    is flushed before acknowledgement. On restart a saved acknowledgement is
    replayed before native files or current policy are accessed.
    """
    def __init__(self,owner):
        require(all(callable(getattr(owner,n,None)) for n in ('run_once','guard','_paused'))
            and callable(getattr(owner.engine,'cleanup_once',None)),'owner_retirement_configuration_required')
        self.owner,self.engine,self.coordinator,self.state=owner,owner.engine,owner.coordinator,owner.state
        self.binding=binding(owner.binding)
        self.outbox=self.state/'retirement-outbox.json';self.pending=self.state/'retirement-outbox.pending'
    def _document(self,value):
        require(isinstance(value,dict) and set(value)=={'command','audit'},'invalid_owner_retirement_outbox')
        c=command(value['command'])
        if value['audit'] is not None:
            checked_audit(value['audit'],c)
            require(value['audit']['state'] in {'retired','erased'},'invalid_owner_retirement_outbox')
        require(len(encoded(value))<=LIMIT,'invalid_owner_retirement_outbox')
        return value
    def _read(self,path):return self._document(strict_json(bounded_read(plain_path(path),LIMIT)))
    def _save(self,value):
        self._document(value)
        if self.outbox.exists():require(self._read(self.outbox)['command']==value['command'],'invalid_owner_retirement_outbox')
        fd=os.open(self.pending,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as stream:
            stream.write(encoded(value));stream.flush();os.fsync(stream.fileno())
        os.replace(self.pending,self.outbox)
    def _recover(self):
        if self.pending.exists():
            value=self._read(self.pending)  # Preserve incomplete bytes and stop.
            if self.outbox.exists():
                old=self._read(self.outbox)
                require(old['command']==value['command'] and (old['audit'] is None or old==value),'invalid_owner_retirement_outbox')
            os.replace(self.pending,self.outbox)
    def _ack(self,value):
        if self.owner._paused():return {'status':'paused'}
        self.owner.guard();reply=self.coordinator.post('retirement-ack',value);c=value['command']
        require(isinstance(reply,dict) and set(reply)=={'acknowledged','leaseId','requestSha256','privacyPending'}
            and reply['acknowledged'] is True and reply['leaseId']==c['leaseId'] and reply['requestSha256']==c['requestSha256']
            and type(reply['privacyPending']) is bool,'invalid_owner_retirement_reply')
        self.outbox.unlink();return {'status':'completed','retired':True,'privacyPending':reply['privacyPending']}
    def _step(self):
        self.owner.guard();self._recover()
        if not self.outbox.exists():
            reply=self.coordinator.post('retirement',{'binding':self.binding})
            require(isinstance(reply,dict),'invalid_owner_retirement_reply')
            if reply=={'command':None,'retryAfterSeconds':30}:return None
            require(set(reply)=={'command'},'invalid_owner_retirement_reply');c=command(reply['command'])
            require(c['policyId']==self.binding['policyId'] and c['profileId'] in self.binding['profiles'],
                'owner_binding_configuration_required')
            self._save({'command':c,'audit':None})
        value=self._read(self.outbox)
        if value['audit'] is not None:return self._ack(value)
        c=value['command']
        audit=checked_audit(self.owner._native('POST','/object-audits/'+c['jobId']+'/retire',encoded(c['body'])),c)
        if audit['state'] not in {'retired','erased'}:
            self.owner.guard()
            if self.owner._paused():return {'status':'paused'}
            step=self.engine.cleanup_once()  # No run_next() inference fallback.
            if self.owner._paused():return {'status':'paused'}
            require(step.get('status') in {'worked','idle'},'owner_cleanup_operator_required')
            audit=checked_audit(self.owner._native('GET','/object-audits/'+c['jobId']),c)
            if audit['state'] not in {'retired','erased'}:return {'status':'idle','retryAfterSeconds':30}
        value={'command':c,'audit':audit};self._save(value)
        return self._ack(value)
    def run_once(self):
        if self.owner._paused():return {'status':'paused'}
        # The actual audit outbox is always replayed before new maintenance.
        if self.owner.outbox.exists() or self.owner.pending.exists():return self.owner.run_once()
        try:
            with _exclusive(self.state):
                if self.owner._paused():return {'status':'paused'}
                # Another owner can save a completion between the first check
                # and acquiring this lock. Release it before exact audit replay.
                result=None if self.owner.outbox.exists() or self.owner.pending.exists() else self._step()
        except OwnerSearchError as error:
            if error.code=='owner_object_paused':return {'status':'paused'}
            raise
        return self.owner.run_once() if result is None else result
