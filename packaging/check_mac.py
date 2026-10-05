"""Actual Mac bundle guards, with disposable resources and no app launch."""
import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile


def check(app):
    app=app.resolve()
    def run(candidate):
        return subprocess.run([str(candidate/'Contents/MacOS/VISION'),'--self-check'],capture_output=True,text=True,timeout=20)
    result=run(app)
    if result.returncode or 'PACKAGE_VERIFIED' not in result.stdout:raise ValueError('original_package_failed')
    with tempfile.TemporaryDirectory() as folder:
        candidate=Path(folder).resolve()/'Check.app';shutil.copytree(app,candidate)
        project=candidate/'Contents/Resources/project'
        source=project/'community/desktop.py';original=source.read_bytes()
        source.write_bytes(original+b'\nchanged fixture\n')
        if not run(candidate).returncode:raise ValueError('changed_file_accepted')
        source.write_bytes(original)
        extra=project/'unknown-file.txt';extra.write_text('disposable fixture')
        if not run(candidate).returncode:raise ValueError('unknown_file_accepted')
        extra.unlink()
        target=project/'community/work_plan.py';body=target.read_bytes();target.unlink()
        outside=Path(folder).resolve()/'outside.py';outside.write_bytes(body);target.symlink_to(outside)
        if not run(candidate).returncode:raise ValueError('redirected_file_accepted')
    print('{"status":"PACKAGE_GUARDS_PASS","changedFileRefused":true,"extraFileRefused":true,"symlinkRefused":true,"productionQualified":false}')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--app',type=Path,required=True)
    check(parser.parse_args().app)
