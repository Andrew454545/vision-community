"""CI-only native Windows layout smoke. No models, imagery or live services."""
import os
from pathlib import Path
import tempfile

import run_windows as runner


def main():
    # Keep this unique, ephemeral CI folder as evidence. Windows may retain an
    # executable handle after a successful process exit; deleting it here made
    # successful startup checks fail and also discarded useful failure logs.
    root = Path(tempfile.mkdtemp(prefix="vision-windows-layout-", dir=os.environ.get("RUNNER_TEMP")))
    report_path = root / "layout-smoke-report.json"
    report = {"version": 1, "status": "INCOMPLETE", "phase": "runtime_pin",
              "nativeInferencePerformed": False, "productionQualified": False}
    runner.write_json(report_path, report)
    try:
        manifest_path = runner.REPO / "community/runtime_manifest.json"
        if runner.sha(manifest_path) != runner.EXPECTED_RUNTIME_SHA256:
            raise ValueError("runtime_manifest_pin_mismatch")
        manifest = runner.json.loads(manifest_path.read_text())
        assets = [item for item in runner.scene_assets(manifest) if not item["asset"].startswith("siglip-")]
        report["phase"] = "download"
        runner.download_runtime(root / "runtime", assets)
        logger = runner.LoggedProcess(root, root)
        report["phase"] = "native_layout"
        _, stdout, stderr = logger([str(root / "runtime/bin/mma-vision.exe"), "index-layout"],
                                   runner.child_environment(root), root)
        layout = runner.parse_json_stdout(stdout)
        runner.require_layout(layout)
        assert layout["completeViewMask"] == 15
        print(stdout)
        print(stderr)
        report.update(status="WINDOWS_SCENE_BINARY_LAYOUT_OK_NO_INFERENCE", phase="complete")
        runner.write_json(report_path, report)
        print("WINDOWS_SCENE_BINARY_LAYOUT_OK_NO_INFERENCE")
        return root
    except BaseException as error:
        report.update(status="FAILED", error=type(error).__name__)
        runner.write_json(report_path, report)
        raise


if __name__ == "__main__":
    main()
