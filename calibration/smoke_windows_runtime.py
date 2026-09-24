"""CI-only native Windows layout smoke. No models, imagery or live services."""
import os
from pathlib import Path
import tempfile

import run_windows as runner


def main():
    with tempfile.TemporaryDirectory(dir=os.environ.get("RUNNER_TEMP")) as temp:
        root = Path(temp)
        manifest_path = runner.REPO / "community/runtime_manifest.json"
        assert runner.sha(manifest_path) == runner.EXPECTED_RUNTIME_SHA256
        manifest = runner.json.loads(manifest_path.read_text())
        assets = [item for item in runner.scene_assets(manifest) if not item["asset"].startswith("siglip-")]
        runner.download_runtime(root / "runtime", assets)
        logger = runner.LoggedProcess(root, root)
        _, stdout, stderr = logger([str(root / "runtime/bin/mma-vision.exe"), "index-layout"],
                                   runner.child_environment(root), root)
        layout = runner.parse_json_stdout(stdout)
        runner.require_layout(layout)
        assert layout["completeViewMask"] == 15
        print(stdout)
        print(stderr)
        print("WINDOWS_SCENE_BINARY_LAYOUT_OK_NO_INFERENCE")


if __name__ == "__main__":
    main()
