"""Inert configured Object audit runner; explicit future activation only.

No tasks, incoming ports, model downloads, credentials or activation files are
installed. The operational cost hold forbids invoking this for real work.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import signal
import sys
import threading

from .native_object_verifier import NativeObjectVerifier
from .native_scene_search import plain_path, strict_json
from .object_audit_jobs import ObjectAuditJobs
from .owner_object_agent import HTTPSObjectCoordinator, OwnerObjectAuditAgent, binding
from .owner_object_verifier import OwnerObjectVerifier
from .owner_search_agent import OwnerSearchError, _exclusive
from .owner_search_credentials import canonical_origin
from .owner_search_service import absolute_path, overlaps, failure_receipt
from .owner_search_supervisor import OwnerSearchSupervisor
from .search_snapshot import bounded_read, pinned_read, resource_for_environment

SCOPE='vision-owner-object-audit-service-v1'
ACTIVATION='OBJECT-ACTIVATE.private.json'
MAX_CONFIG=16384


class OwnerObjectServiceError(ValueError):pass


def require(value,code='owner_object_configuration_required'):
    if not value:raise OwnerObjectServiceError(code)


def load_configuration(path,checksum):
    """Check configuration only; committed replay may outlive native assets."""
    try:
        require(isinstance(checksum,str) and len(checksum)==64 and all(c in '0123456789abcdef' for c in checksum))
        path=plain_path(absolute_path(str(path)))
        doc=strict_json(pinned_read(path,checksum,MAX_CONFIG))
        keys={'version','scope','origin','environment','state','binding','native'}
        require(isinstance(doc,dict) and set(doc) in (keys,keys|{'retirement'})
            and type(doc['version']) is int and doc['version']==1 and doc['scope']==SCOPE
            and doc['environment'] in {'staging','production'} and canonical_origin(doc['origin'])==doc['origin'])
        require('retirement' not in doc or doc['retirement'] is True)
        require(binding(doc['binding'])['resource']==resource_for_environment(doc['environment']))
        state=plain_path(absolute_path(doc['state']),directory=True)
        source=Path(__file__).resolve().parents[1]
        require(not overlaps(state,source) and not overlaps(path,source) and not overlaps(state,path),
            'owner_object_private_state_required')
        native=doc['native']
        require(isinstance(native,dict) and set(native)=={'binary','models','policy','policySha256','registry','registrySha256','spool'}
            and native['policySha256']==doc['binding']['policySha256']
            and isinstance(native['registrySha256'],str) and len(native['registrySha256'])==64
            and all(c in '0123456789abcdef' for c in native['registrySha256']))
        paths={k:absolute_path(native[k]) for k in ('binary','models','policy','registry','spool')}
        spool=paths['spool']
        require(not overlaps(spool,source) and not overlaps(spool,state) and not overlaps(spool,path),
            'owner_object_private_state_required')
        for key in ('binary','models','policy','registry'):
            root=paths[key].parent if key in {'binary','policy','registry'} else paths[key]
            require(not overlaps(state,root) and not overlaps(spool,root),'owner_object_state_overlaps_input')
        return doc
    except OwnerObjectServiceError:raise
    except Exception:raise OwnerObjectServiceError('owner_object_configuration_required') from None


def check_activation(path,checksum,config):
    require(load_configuration(path,checksum)==config)
    try:
        approved=strict_json(bounded_read(plain_path(Path(config['state'])/ACTIVATION),4096))
        require(isinstance(approved,dict) and type(approved.get('version')) is int and type(approved.get('approved')) is bool
            and approved=={'version':1,'scope':'explicit-owner-object-audit-activation','approved':True,
                'configSha256':checksum,'origin':config['origin'],'environment':config['environment']},
            'owner_object_activation_required')
    except (ValueError,OSError):raise OwnerObjectServiceError('owner_object_activation_required') from None


class LazyCoordinator:
    def __init__(self,origin,guard):self.origin,self.guard,self.connection=origin,guard,None
    def post(self,action,body):
        self.guard()
        if self.connection is None:self.connection=HTTPSObjectCoordinator.from_os_credentials(self.origin)
        self.guard();return self.connection.post(action,body)


class LazyVerifier:
    def __init__(self,config,guard):self.config,self.guard,self.engine=config,guard,None
    def _marker(self):
        spool=Path(self.config['native']['spool'])
        return next((n.lower() for n in ('STOP','PAUSE') if (spool/n).exists()),None)
    def _get(self):
        self.guard()
        if self.engine is None:
            n=self.config['native'];v=NativeObjectVerifier(Path(n['binary']),Path(n['models']),Path(n['policy']),n['policySha256'])
            p=v.document
            actual={'version':1,'scope':'object-batch-parity-v1','policyId':p['policyId'],'policySha256':v.policy_sha256,
                'runtimeProfileSha256':v.profile['sha256'],'qualityImplementationIdentity':p['qualityImplementationIdentity'],
                'protectedAuthoritySha256':p['protectedAuthority']['sha256'],
                'protectedOriginHandoffSha256':p['protectedOriginHandoffSha256'],'profiles':p['profiles'],'resource':p['resource']}
            require(binding(actual)==self.config['binding'],'owner_object_native_binding_mismatch')
            jobs=ObjectAuditJobs(v,Path(n['registry']),n['registrySha256'],Path(n['spool']))
            try:
                self.guard();self.engine=OwnerObjectVerifier(jobs,guard=self.guard)
            except BaseException:jobs.close();raise
        self.guard();return self.engine
    def handle(self,*args):return self._get().handle(*args)
    def work_once(self):return self._get().work_once()
    def cleanup_once(self):return self._get().cleanup_once()
    def close(self):
        if self.engine is not None:self.engine.jobs.close();self.engine=None


def run_service(path,checksum,*,once=False,stop_event=None):
    state=None;engine=None
    try:
        require(type(once) is bool)
        config=load_configuration(path,checksum);state=Path(config['state'])
        if any((state/n).exists() for n in ('PAUSE','STOP')):
            return {'status':'stopped' if (state/'STOP').exists() else 'paused'}
        if any((Path(config['native']['spool'])/n).exists() for n in ('PAUSE','STOP')):return {'status':'paused'}
        with _exclusive(state,name='service.lock'):
            guard=lambda:check_activation(path,checksum,config)
            guard();engine=LazyVerifier(config,guard)
            try:
                owner=OwnerObjectAuditAgent(LazyCoordinator(config['origin'],guard),engine,state,config['binding'],guard=guard)
                if config.get('retirement'):
                    from .owner_object_retirement import OwnerObjectRetirementAgent
                    owner=OwnerObjectRetirementAgent(owner)
                supervisor=OwnerSearchSupervisor(owner,native_failure='native_verification_failed')
                return supervisor.step() if once else supervisor.run(stop_event or threading.Event())
            finally:
                engine.close();engine=None
    except OwnerSearchError as error:
        if error.code=='owner_agent_busy':return {'status':'busy'}
        if state is not None:failure_receipt(state)
        raise OwnerObjectServiceError('owner_object_operator_required') from None
    except Exception:
        if state is not None:failure_receipt(state)
        raise OwnerObjectServiceError('owner_object_operator_required') from None
    finally:
        if engine is not None:engine.close()


class Parser(argparse.ArgumentParser):
    def error(self,_):raise OwnerObjectServiceError('owner_object_arguments_required')


def main(argv=None):
    parser=Parser(description='Future private Object audit runner; approved activation required.')
    parser.add_argument('--config',required=True);parser.add_argument('--config-sha256',required=True)
    parser.add_argument('--once',action='store_true')
    stop=threading.Event();previous={}
    try:
        args=parser.parse_args(argv)
        for signum in (signal.SIGINT,signal.SIGTERM):previous[signum]=signal.signal(signum,lambda *_:stop.set())
        result=run_service(args.config,args.config_sha256,once=args.once,stop_event=stop)
        status=2 if result['status']=='operator_required' else 0
    except (Exception,KeyboardInterrupt):result,status={'status':'operator_required','error':'owner_object_operator_required'},1
    finally:
        for signum,handler in previous.items():signal.signal(signum,handler)
    if sys.stdout is not None:sys.stdout.write(json.dumps(result)+'\n')
    return status


if __name__=='__main__':raise SystemExit(main())
