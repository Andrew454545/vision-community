"""Finite real native bootstrap/private Python/page check under Restricted.

No app installation, scheduled task, account, model, imagery or contribution.
The fresh tree and failure receipt are preserved on failure. Only the exact
created native helper and empty-page Python process can be stopped by this check.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request

PYTHON_SHA = 'd297e5ff019966817ad8502465176139f2d3d840fa4ed84b13bed399a6ab1f15'


def check(executable, report, archive=None):
    from community.mac_starter import regular
    report=regular(report,missing=True)
    if report.exists():raise ValueError('report_already_exists')
    try:return _check(executable,report,archive)
    except Exception:
        if not report.exists():
            report.write_text(json.dumps({'status':'INCOMPLETE','code':'native_guided_fixture_failed','accountsCreated':0,'nativeInference':False,'productionQualified':False})+'\n',encoding='utf-8')
        raise


def _check(executable, report, archive=None):
    # All writable paths are exact fresh children of the chosen temp directory.
    from community.mac_starter import regular
    executable=regular(executable)
    report=regular(report,missing=True)
    if report.exists():raise ValueError('report_already_exists')
    folder=Path(tempfile.mkdtemp(prefix='vision-native-guided-')).absolute()
    data=folder/'private';downloads=data/'downloads';downloads.mkdir(parents=True)
    if archive is not None:
        archive=regular(archive)
        if hashlib.sha256(archive.read_bytes()).hexdigest()!=PYTHON_SHA:
            raise ValueError('private_python_archive_changed')
        shutil.copyfile(archive,downloads/'python-3.14.7-embed-amd64.zip')
    env={name.upper():value for name,value in os.environ.items()}
    env.update(PSEXECUTIONPOLICYPREFERENCE='Restricted',VISION_DISPOSABLE_GUIDED='1')
    # A caller using PowerShell 7 can otherwise hide Windows PowerShell's built-in
    # read-only security cmdlet with its unrelated module search path.
    env['PSMODULEPATH']=str(Path(os.environ['WINDIR'])/'System32/WindowsPowerShell/v1.0/Modules')
    # Read-only -Command query, not script execution or an execution-policy change.
    shell=Path(os.environ['WINDIR'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
    policy=subprocess.run([str(shell),'-NoProfile','-Command','Get-ExecutionPolicy'],env=env,capture_output=True,text=True,timeout=20)
    if policy.returncode or policy.stdout.strip()!='Restricted':raise ValueError('restricted_child_policy_not_verified')
    mode='--guided-check' if archive else '--guided-download-check'
    process=subprocess.Popen([str(executable),mode,str(folder)],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    result={'status':'INCOMPLETE','effectiveChildPolicy':'Restricted','accountsCreated':0,'nativeInference':False,'productionQualified':False}
    try:
        deadline=time.monotonic()+210
        url_path=data/'local-test-url.txt'
        ready_path=data/'native-check-ready.json'
        while (not url_path.exists() or not ready_path.exists()) and time.monotonic()<deadline:
            if process.poll() is not None:raise ValueError('native_guided_exited_early')
            time.sleep(.1)
        if not url_path.exists() or not ready_path.exists():raise ValueError('native_guided_did_not_open')
        if json.loads(ready_path.read_text(encoding='utf-8'))!={'authenticatedPageVerified':True}:raise ValueError('native_guided_reuse_not_verified')
        url=url_path.read_text(encoding='utf-8')
        matched=re.fullmatch(r'http://127\.0\.0\.1:([1-9][0-9]{0,4})/#([A-Za-z0-9_-]{32,128})',url)
        if not matched or int(matched[1])>65535:raise ValueError('invalid_fixture_local_url')
        base=url.split('#')[0]
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,*args,**kwargs):raise ValueError('fixture_redirect_refused')
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
        headers={'X-Vision-Token':matched[2],'Origin':base.rstrip('/')}
        request=urllib.request.Request(base+'api/status',headers=headers)
        with opener.open(request,timeout=10) as response:
            state=json.loads(response.read(65536))
        if state.get('nativeApp') is not True:raise ValueError('native_guided_labels_missing')
        # This real page has no connected account, runtime or accepted work.
        if state.get('busy') is not False:raise ValueError('unexpected_fixture_work')
        request=urllib.request.Request(base+'api/quit',data=b'{}',headers={**headers,'Content-Type':'application/json'})
        with opener.open(request,timeout=10) as response:
            if json.loads(response.read(4096))!={'ok':True}:raise ValueError('incomplete_close_reply')
        stdout,stderr=process.communicate(timeout=20)
        receipt=json.loads(stdout.decode('utf-8-sig'))
        if process.returncode or receipt.get('status')!='NATIVE_GUIDED_START_PASS':raise ValueError('native_guided_failed')
        if (data/'account.json').exists() or (data/'instance.json').exists() or url_path.exists():raise ValueError('unexpected_fixture_private_state')
        snapshots=[p for p in (data/'apps').iterdir() if re.fullmatch('[a-f0-9]{64}',p.name)]
        if len(snapshots)!=1:raise ValueError('unexpected_snapshot_count')
        # Imports must work from the actual copied snapshot, independently of the checkout.
        private_python=next((data/'python').glob('*/python.exe'))
        code=("import sys;from pathlib import Path;root=Path(sys.argv[1]);sys.path.insert(0,str(root));"
              "import community.desktop,community.background,community.object_canary,calibration.synthetic_canary;"
              "assert len(calibration.synthetic_canary.image_bytes(0,0))==224*224*3;"
              "assert all(Path(m.__file__).is_relative_to(root) for n,m in sys.modules.items() if n=='community' or n.startswith('community.'))")
        imported=subprocess.run([str(private_python),'-I','-B','-c',code,str(snapshots[0])],env=env,capture_output=True,timeout=20)
        if imported.returncode:raise ValueError('private_snapshot_import_failed')
        # Reuse this exact pinned archive in a separate fresh native background
        # fixture. PAUSE is created before Python starts; no account recovery,
        # service request, imagery or inference is possible in its paused loop.
        background=Path(tempfile.mkdtemp(prefix='vision-native-paused-')).absolute()
        background_downloads=background/'private'/'downloads';background_downloads.mkdir(parents=True)
        shutil.copyfile(downloads/'python-3.14.7-embed-amd64.zip',background_downloads/'python-3.14.7-embed-amd64.zip')
        background_env={**env,'VISION_DISPOSABLE_BACKGROUND':'1'}
        paused=subprocess.run([str(executable),'--background-run-check',str(background)],env=background_env,capture_output=True,timeout=100)
        if paused.returncode:raise ValueError('native_paused_worker_failed')
        background_receipt=json.loads(paused.stdout.decode('utf-8-sig'))
        if background_receipt.get('status')!='NATIVE_PAUSED_BACKGROUND_PASS':raise ValueError('native_paused_worker_receipt_failed')
        result={**result,**receipt,'completeCloseReply':True,'privateSnapshotImports':True,'installedApplicationChanged':False,'startupTaskChanged':False,'pausedBackground':background_receipt}
        report.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
        # Verify exact owned path before cleanup; do not delete user-selected paths.
        regular(folder,directory=True)
        if folder.parent!=Path(tempfile.gettempdir()).absolute() or not folder.name.startswith('vision-native-guided-'):
            raise ValueError('fixture_cleanup_scope')
        shutil.rmtree('\\\\?\\'+str(folder))
        regular(background,directory=True)
        if background.parent!=Path(tempfile.gettempdir()).absolute() or not background.name.startswith('vision-native-paused-'):
            raise ValueError('background_fixture_cleanup_scope')
        shutil.rmtree('\\\\?\\'+str(background))
        return result
    except Exception:
        # Keep only fixed status, not native output, paths, tokens or URL fragments.
        report.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
        raise
    finally:
        if process.poll() is None:
            # The native finite-check helper owns its one empty-page child and
            # stops it after its 60-second deadline. Never kill an installed worker.
            try:process.communicate(timeout=65)
            except subprocess.TimeoutExpired:process.terminate();process.communicate(timeout=10)


if __name__=='__main__':
    import sys
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--archive',type=Path)
    args=parser.parse_args()
    print(json.dumps(check(args.executable,args.report,args.archive)))
