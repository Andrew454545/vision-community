"""Run the installed fixed-input computer check without opening a browser."""
from pathlib import Path
import argparse
import json
import os
import sys

REPO = Path(os.path.abspath(__file__)).parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from community.local_scene_readiness import LocalSceneReadiness
from community.local_scene_pilot import atomic_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', type=Path, required=True)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--runtime-root', type=Path, required=True)
    parser.add_argument('--result', type=Path, required=True)
    args = parser.parse_args()
    app = LocalSceneReadiness(args.check, args.data_dir, args.runtime_root)
    try:
        app.start()
        app.thread.join(2000)  # Up to three finite 600-second native profiles.
        if app.thread.is_alive():
            raise TimeoutError('finite_computer_check_timeout')
        archive = app.export_results() if app.reports else None
        result = {'contract': 'vision-local-scene-check-result-v1', 'status': app.phase,
            'completedChecks': app.completed // 112, 'installationId': app.installation_id,
            'resultsZip': archive, 'scope': 'OWNER_REVIEW_REQUIRED',
            'liveImageryRequests': 0, 'uploads': 0}
        atomic_json(args.result, result)
        print(json.dumps(result), flush=True)
        return 0 if app.phase == 'complete' else 2
    finally:
        app.close()


if __name__ == '__main__':
    raise SystemExit(main())
