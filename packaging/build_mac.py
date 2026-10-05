"""Build an unsigned maintainer app, or sign and notarize a public candidate."""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).parent))
from stage import REPO, regular, source_state, stage

def command(*args):
    subprocess.run(args, check=True)

def build(output, revision, identity=None, profile=None):
    if not re.fullmatch(r'[a-f0-9]{40}', revision): raise ValueError('invalid_revision')
    output = regular(output, directory=True, missing=True)
    if output.exists(): raise ValueError('package_output_exists')
    if bool(identity) != bool(profile) or identity and not identity.startswith('Developer ID Application: '):
        raise ValueError('developer_id_and_notary_profile_required_together')
    dirty = source_state(revision,signing=bool(identity))
    output.mkdir()
    app = output / 'VISION Community.app'
    resources = app / 'Contents/Resources'; resources.mkdir(parents=True)
    executable = app / 'Contents/MacOS/VISION'; executable.parent.mkdir()
    digest = stage(resources/'project', 'mac', revision)
    generated = output / 'Build.swift'
    generated.write_text('enum Build { static let inventorySHA = "'+digest+'"; static let revision = "'+revision+'" }\n')
    info = {'CFBundleExecutable':'VISION','CFBundleIdentifier':'org.visioncommunity.app',
        'CFBundleName':'VISION Community','CFBundleDisplayName':'VISION Community',
        'CFBundleVersion':'1','CFBundleShortVersionString':'0.1.0', 'CFBundlePackageType':'APPL',
        'LSMinimumSystemVersion':'13.0','NSHighResolutionCapable':True,'VISIONSourceRevision':revision}
    (app/'Contents/Info.plist').write_bytes(plistlib.dumps(info))
    main = output / 'main.swift'; main.write_bytes((REPO/'packaging/macos/Launcher.swift').read_bytes())
    command('xcrun','swiftc','-O','-target','arm64-apple-macosx13.0','-framework','AppKit',
            str(generated),str(main),'-o',str(executable))
    command(str(executable),'--self-check')
    # An ad-hoc compiler signature is only local build evidence.
    public = False
    if identity:
        command('codesign','--force','--options','runtime','--timestamp','--sign',identity,str(app))
        command('codesign','--verify','--deep','--strict',str(app))
        upload = output/'notary-upload.zip'
        command('ditto','-c','-k','--keepParent',str(app),str(upload))
        receipt = output/'notary-result.json'
        with receipt.open('xb') as handle:
            subprocess.run(['xcrun','notarytool','submit',str(upload),'--keychain-profile',profile,
                '--wait','--output-format','json'],stdout=handle,check=True)
        if json.loads(receipt.read_bytes()).get('status') != 'Accepted':raise ValueError('notarization_not_accepted')
        command('xcrun','stapler','staple',str(app)); command('xcrun','stapler','validate',str(app))
        command('spctl','--assess','--type','execute',str(app))
        public = True
    archive = output / ('VISION-Community-Mac.zip' if public else 'MAINTAINER-UNSIGNED-VISION-Mac.zip')
    command('ditto','-c','-k','--keepParent',str(app),str(archive))
    metadata = {'version':1,'sourceRevision':revision,'sourceWorktreeDirty':dirty,'platform':'darwin-arm64','publicDistributionReady':public,
        'productionQualified':False,'nativeRuntimesQualified':False,'artifact':archive.name,
        'bytes':archive.stat().st_size,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
        'inventorySha256':digest,'signedAndNotarized':public}
    (output/'package-receipt.json').write_text(json.dumps(metadata,indent=2)+'\n')
    return metadata

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True); parser.add_argument('--revision',required=True)
    parser.add_argument('--identity'); parser.add_argument('--notary-profile')
    args=parser.parse_args()
    print(json.dumps(build(args.output,args.revision,args.identity,args.notary_profile)))

if __name__=='__main__':main()
