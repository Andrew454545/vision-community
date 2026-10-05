"""Build the per-user Windows setup; unsigned builds are maintainer previews."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).parent))
from stage import REPO, archive, inventory, regular, source_state, stage


def powershell(script, *arguments):
    shell = Path(os.environ['WINDIR'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
    subprocess.run([str(shell),'-NoProfile','-File',str(script),*arguments],check=True)


def build(output, revision, signer=None, publisher=None):
    if bool(signer) != bool(publisher):raise ValueError('signer_and_expected_publisher_required_together')
    dirty=source_state(revision,signing=bool(signer))
    output=regular(output,directory=True,missing=True)
    if output.exists():raise ValueError('package_output_exists')
    output.mkdir(); project=output/'project'
    stage(project,'windows',revision)
    if signer:
        signer=regular(signer)
        for path in sorted(project.rglob('*.ps1')):powershell(signer,'-File',str(path))
    digest=inventory(project,revision)
    payload=output/'payload.zip'; payload_digest=archive(project,payload)
    generated=output/'Build.cs'
    generated.write_text('static class Build { public const string PayloadSHA="'+payload_digest+'"; '+
        'public const string InventorySHA="'+digest+'"; public const string Revision="'+revision+'"; }\n')
    executable=output/('VISION-Community-Setup.exe' if signer else 'MAINTAINER-UNSIGNED-VISION-Setup.exe')
    compiler=Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    subprocess.run([str(compiler),'/nologo','/target:winexe','/platform:x64','/optimize+',
        '/out:'+str(executable),'/resource:'+str(payload)+',VisionPayload',
        '/reference:System.Windows.Forms.dll','/reference:System.Drawing.dll','/reference:System.Web.Extensions.dll',
        '/reference:System.IO.Compression.dll','/reference:System.IO.Compression.FileSystem.dll',
        '/reference:Microsoft.CSharp.dll',str(generated),str(REPO/'packaging/windows/Launcher.cs')],check=True)
    if signer:powershell(signer,'-File',str(executable))
    # Wait explicitly for a GUI-subsystem executable. The fixture never installs
    # shortcuts, registers startup, retrieves inputs or starts a native indexer.
    check=output/'check-package.ps1'
    check.write_text("param($Program,$Report)\n$p=Start-Process -FilePath $Program -ArgumentList '--self-check' -Wait -PassThru -RedirectStandardOutput $Report\nif ($p.ExitCode) {exit 1}\n")
    if signer:powershell(signer,'-File',str(check))
    report=output/'package-self-check.json';powershell(check,str(executable),str(report))
    if json.loads(report.read_text(encoding='utf-8-sig')).get('status')!='PACKAGE_VERIFIED':raise ValueError('package_check_failed')
    # The finite fixture creates a local unsigned helper. Run it in unsigned CI,
    # not on signing nodes which may require every development script signed.
    if not signer:
        with tempfile.TemporaryDirectory(prefix='vision-detached-check-') as folder:
            fixture=Path(folder)/'child'
            started=subprocess.Popen([str(executable),'--detached-check',str(fixture)])
            if started.wait(timeout=20):raise ValueError('detached_fixture_start_failed')
            result=fixture/'result.json';deadline=time.monotonic()+30
            while not result.exists() and time.monotonic()<deadline:time.sleep(.1)
            if not result.exists() or json.loads(result.read_text()).get('status')!='DETACHED_HELPER_PASS':
                raise ValueError('detached_helper_did_not_finish')
            (output/'detached-helper-check.json').write_bytes(result.read_bytes())
    public=False
    if signer:
        verify=output/'check-signatures.ps1'
        verify.write_text("param($Project,$Program,$Publisher)\n$ErrorActionPreference='Stop'\n"+
            "$files=@(Get-ChildItem -LiteralPath $Project -Filter '*.ps1' -Recurse -File)+@(Get-Item -LiteralPath $Program)\n"+
            "foreach($file in $files) { $signature=Get-AuthenticodeSignature -LiteralPath $file.FullName; "+
            "if($signature.Status -ne 'Valid' -or -not $signature.TimeStamperCertificate -or $signature.SignerCertificate.Subject -ne $Publisher) {throw 'invalid_release_signature'} }\n")
        powershell(signer,'-File',str(verify))
        powershell(verify,str(project),str(executable),publisher)
        public=True
    metadata={'version':1,'sourceRevision':revision,'sourceWorktreeDirty':dirty,'platform':'windows-x86_64','publicDistributionReady':public,
        'productionQualified':False,'nativeRuntimesQualified':False,'artifact':executable.name,
        'bytes':executable.stat().st_size,'sha256':hashlib.sha256(executable.read_bytes()).hexdigest(),
        'inventorySha256':digest,'signedAndTimestamped':public}
    (output/'package-receipt.json').write_text(json.dumps(metadata,indent=2)+'\n')
    return metadata


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--revision',required=True)
    parser.add_argument('--signer',type=Path);parser.add_argument('--publisher')
    args=parser.parse_args()
    print(json.dumps(build(args.output,args.revision,args.signer,args.publisher)))

if __name__=='__main__':main()
