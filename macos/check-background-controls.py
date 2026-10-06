"""Finite actual Mac guarded startup/controls test; no real account or imagery.

Only a random temporary agent is registered. The real worker is paused before
it can make a service request. Keep only the aggregate report as an artifact.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from community.background import measure_storage, single_instance, WorkerAlreadyRunning
from community.mac_background import DEFAULT_SETTINGS, MacBackground
from community.mac_runtime import runtime_links
from community.mac_remove import prepare_removal
from community.mac_starter import copy_source, FILES, regular


def wait_until(check, seconds=45):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        result=check()
        if result:return result
        time.sleep(.1)
    raise RuntimeError('finite_mac_controls_timeout')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',required=True,type=Path)
    parser.add_argument('--report',required=True,type=Path)
    args=parser.parse_args()
    if sys.platform!='darwin':parser.error('Actual Mac required.')
    root=regular(args.root,directory=True)
    report=regular(args.report,missing=True)
    if report.exists():parser.error('Keep original evidence and choose a new report.')
    nonce=secrets.token_hex(16)
    fixture=root/('controls-check-'+nonce);fixture.mkdir(mode=0o700)
    home=fixture/'home';home.mkdir()
    # A distinct copied source receipt prevents failure-injection tests from
    # modifying the original verified starter snapshot or runtime.
    source=fixture/'source';source.mkdir()
    repository=Path(__file__).resolve().parents[1]
    for name in FILES:
        original=repository/name
        if original.is_file():
            target=source/name;target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(original.read_bytes())
    with (source/'community/background_web/style.css').open('ab') as output:
        output.write(b'\n/* isolated finite control fixture */\n')
    app,digest=copy_source(source,root)
    manager=MacBackground(root,app,home=home,label='org.visioncommunity.check.'+nonce)
    receipt={'status':'INCOMPLETE','productionQualified':False,'platform':'darwin-arm64',
        'realAccountsCreated':0,'serviceRequests':0,'nativeCommands':0,'imageryRetrieved':False,
        'contributionsUploaded':0,'temporaryAgentRemoved':False,'actualOsRestartTested':False,
        'loginRecoveryTested':False,'sourceSha256':digest}
    child=None
    phase='storage'
    try:
        usage=measure_storage(root,approved_links=runtime_links(root))
        if usage['links']!=9 or usage['usedBytes']<=0:raise RuntimeError('private_runtime_storage_failed')
        receipt['pinnedRuntimeLinksAccounted']=usage['links']
        # The real worker's first step is a durable pause, before service calls.
        regular(root/'PAUSE',missing=True).touch(mode=0o600)
        phase='registration'
        manager.enable(dict(DEFAULT_SETTINGS),accept=True,code='finite-offline-fixture-account')
        def paused():
            path=root/'background-status.json'
            return path.exists() and json.loads(path.read_text()).get('state')=='paused' and manager.status()['running']
        wait_until(paused)
        receipt['guardedWorkerStartedPaused']=True
        original=(root/'account.json').read_bytes()
        phase='handover'
        manager.enable(dict(DEFAULT_SETTINGS,storageLimitGb=20),accept=True,code='must-not-replace')
        wait_until(paused)
        if (root/'account.json').read_bytes()!=original or not (root/'PAUSE').exists():
            raise RuntimeError('saved_account_or_pause_changed')
        receipt['idleReplacementPreservedAccountAndPause']=True
        phase='window'
        private_url=root/'mac-controls-test-url'
        if private_url.exists():raise RuntimeError('private_control_url_already_exists')
        child=subprocess.Popen([sys.executable,'-I','-B',str(app/'community/mac_background_control.py'),
            '--root',str(root),'--no-browser','--check-label',manager.label,'--check-home',str(home)],
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        wait_until(private_url.exists)
        address=urlsplit(private_url.read_text())
        if address.hostname!='127.0.0.1' or not address.fragment:raise RuntimeError('private_window_scope_failed')
        base='http://127.0.0.1:'+str(address.port)
        for path in ('/','/app.js','/style.css'):
            with urlopen(base+path,timeout=5) as response:
                if response.status!=200 or response.headers.get('Cache-Control')!='no-store':
                    raise RuntimeError('private_window_asset_failed')
        try:urlopen(base+'/api/status',timeout=5).close()
        except HTTPError as error:
            if error.code!=403:raise RuntimeError('private_window_auth_failed') from None
        else:raise RuntimeError('private_window_auth_failed')
        headers={'X-Vision-Token':address.fragment,'Content-Type':'application/json'}
        with urlopen(Request(base+'/api/status',headers=headers),timeout=5) as response:
            status=json.load(response)
        if not status['enabled'] or not status['accountSaved'] or not status['running']:
            raise RuntimeError('private_window_status_failed')
        with urlopen(Request(base+'/api/quit',data=b'{}',headers=headers,method='POST'),timeout=5) as response:
            if response.status!=200:raise RuntimeError('private_window_quit_failed')
        child.wait(timeout=10)
        if child.returncode or private_url.exists() or not manager.status()['running']:
            raise RuntimeError('closing_controls_interrupted_worker')
        receipt['privateWindowAuthAssetsQuitAndIndependentWorker']=True
        phase='remove'
        removal=subprocess.run(['/bin/bash',str(repository/'macos/Remove-Vision.command'),
            '--root',str(root),'--check-label',manager.label,'--check-home',str(home)],
            capture_output=True,text=True,timeout=90)
        if removal.returncode or json.loads(removal.stdout).get('status')!='MAC_REMOVAL_READY':
            raise RuntimeError('application_removal_not_ready')
        if manager.status()['enabled'] or manager.plist.exists() or (root/'account.json').read_bytes()!=original:
            raise RuntimeError('private_agent_removal_failed')
        receipt['temporaryAgentRemoved']=True
        receipt['applicationRemovalCooperativelyStoppedOwnedWorker']=True
        original_registration=manager.receipt.read_bytes()
        if prepare_removal(root,home=home,label=manager.label)['status']!='MAC_REMOVAL_READY' or manager.receipt.read_bytes()!=original_registration:
            raise RuntimeError('application_removal_repeat_changed_receipt')
        receipt['applicationRemovalRepeatPreservedReceiptAndAccount']=True
        phase='changed_source'
        # Execute the recorded system-only guard directly after an isolated
        # snapshot change. No changed Python must run, and a report must survive.
        (app/'community/mac_worker.py').write_bytes(b'raise RuntimeError("changed source must not run")\n')
        regular(root/'STOP-AFTER-BATCH').unlink()
        before=len(list((root/'setup-failures').glob('*.json'))) if (root/'setup-failures').exists() else 0
        result=subprocess.run(manager.config['ProgramArguments'],cwd=root,env={},
            capture_output=True,text=True,timeout=30)
        if result.returncode==0 or not (root/'NEEDS-ATTENTION').exists():
            raise RuntimeError('changed_source_not_blocked')
        after=len(list((root/'setup-failures').glob('*.json')))
        if after!=before+1:raise RuntimeError('trust_failure_not_preserved')
        repeated=subprocess.run(manager.config['ProgramArguments'],cwd=root,env={},
            capture_output=True,text=True,timeout=30)
        if repeated.returncode or len(list((root/'setup-failures').glob('*.json')))!=after:
            raise RuntimeError('trust_failure_repeated_expensively')
        receipt['changedSourceBlockedBeforePythonAndReportPreserved']=True
        receipt['attentionPreventsRepeatedLaunches']=True
        receipt['status']='MAC_GUARDED_BACKGROUND_CONTROLS_VERIFIED'
    except Exception as error:
        receipt.update(phase=phase,errorType=type(error).__name__)
        raise
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            try:child.wait(timeout=10)
            except subprocess.TimeoutExpired:child.kill();child.wait(timeout=5)
        if not receipt['temporaryAgentRemoved']:
            try:
                manager.remove()
                receipt['temporaryAgentRemoved']=not manager.plist.exists()
            except Exception:
                receipt['cleanupFailed']=True
        with report.open('x',encoding='utf-8') as output:json.dump(receipt,output,indent=2)
        print(json.dumps(receipt,sort_keys=True))


if __name__=='__main__':main()
