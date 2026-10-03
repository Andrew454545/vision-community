// Fixed first eight public canary locations, through the actual audit path.
// No operator-supplied command, location, vector, URL or threshold is accepted.
export const AUDIT_BUDGET_SETUP = String.raw`import sys
sys.path.insert(0, '/opt/vision/client')
import hashlib, json, resource, tempfile, time
from pathlib import Path
from types import SimpleNamespace
from community.native_scene_search import NativeSceneRuntime
from community.native_scene_verifier import NativeSceneVerifier
from community.four_view import BYTES_PER_LOCATION, valid_four_view_record

started = time.monotonic()
try:
    runtime_sha = 'bbc60e94e6590c657f256d89f6d63db47f7f3d53d1ba37ffeafba07b6211d64e'
    runtime = NativeSceneRuntime(Path('/opt/vision/runtime/runtime.json'), runtime_sha)
    locations = [
        (145586295, 41.79270699022923, 20.39504004993244, 70.54816, 'Je141ivXzUUx4ro1j8_3vw', 'Albania'),
        (4626657, -34.857567632173556, -57.900785837317585, 139, 'km6gNrxKma-RMNvlJM_9-Q', 'Argentina'),
        (2410738, -37.795511834632805, 145.1150978737676, 105.47, '91dj0UCWJXcM7FbjjULcMQ', 'Australia'),
        (196829536, 48.14921727231794, 13.842905992732016, 359.61, 'h4vz8PMhJIhhRT6m0dGrpA', 'Austria'),
        (75713912, 22.50162321955617, 91.81576361489768, 170.77, 'WqSwMCWp14Hk9DdTwVNQNg', 'Bangladesh'),
        (209001370, 49.90982347475166, 5.57035186711602, 187.81, 'y1xacNDoVzpbL2OqJPrmlQ', 'Belgium'),
        (166285462, 44.43173955511929, 18.13176287002416, 10.688302, 'qmt7OJamHMq2y4WVccJhkg', 'Bosnia and Herzegovina'),
        (15119634, -25.409087378280752, -53.61125382587646, 264.71, 'QyRog2GXI3d2cnHL2T-JGw', 'Brazil'),
    ]
    records = [{'locationId': i, 'lat': lat, 'lng': lng, 'heading': heading,
        'pitch': 0, 'zoom': 0, 'assetId': asset, 'country': country, 'cameraGeneration': 'gen4'}
        for i, lat, lng, heading, asset, country in locations]
`;
export const AUDIT_BUDGET_CHECK = AUDIT_BUDGET_SETUP + String.raw`
    with tempfile.TemporaryDirectory(prefix='operator-audit-budget-', dir='/state') as temporary:
        runner = SimpleNamespace(runtime=runtime, timeout=50)
        runtime.verify_runtime()
        blob = NativeSceneVerifier.recompute(runner, records, Path(temporary))
        if len(blob) != len(records) * BYTES_PER_LOCATION or any(
                not valid_four_view_record(blob[i:i + BYTES_PER_LOCATION])
                for i in range(0, len(blob), BYTES_PER_LOCATION)):
            raise ValueError('invalid_model_output')
        runtime.verify_runtime()
        receipt = {'status': 'native_audit_budget_check_passed', 'runtimeSha256': runtime_sha,
            'locations': 8, 'views': 32, 'fetchErrors': 0, 'inferenceErrors': 0,
            'bytes': len(blob), 'outputSha256': hashlib.sha256(blob).hexdigest(),
            'sceneGraph': 'fp32', 'executionProvider': 'cpu', 'threads': 1,
            'nativeTimeoutSeconds': 50, 'elapsedSeconds': round(time.monotonic() - started, 3),
            'peakChildRssKiB': resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
            'productionQualified': False}
    print(json.dumps(receipt), flush=True)
except Exception:
    print('{"error":"native_audit_budget_check_failed"}', flush=True)
    sys.exit(1)
`;

export function checkedAuditBudgetReceipt(value, runtimeSha256) {
  const fields = ["status", "runtimeSha256", "locations", "views", "fetchErrors", "inferenceErrors",
    "bytes", "outputSha256", "sceneGraph", "executionProvider", "threads", "nativeTimeoutSeconds",
    "elapsedSeconds", "peakChildRssKiB", "productionQualified"];
  if (!value || typeof value !== "object" || Array.isArray(value)
      || Object.keys(value).sort().join(",") !== fields.sort().join(",")
      || value.status !== "native_audit_budget_check_passed" || value.runtimeSha256 !== runtimeSha256
      || value.locations !== 8 || value.views !== 32 || value.bytes !== 24640
      || value.fetchErrors !== 0 || value.inferenceErrors !== 0 || value.nativeTimeoutSeconds !== 50
      || value.sceneGraph !== "fp32" || value.executionProvider !== "cpu" || value.threads !== 1
      || !/^[0-9a-f]{64}$/.test(value.outputSha256) || value.productionQualified !== false
      || !Number.isFinite(value.elapsedSeconds) || value.elapsedSeconds <= 0 || value.elapsedSeconds > 60
      || !Number.isSafeInteger(value.peakChildRssKiB) || value.peakChildRssKiB <= 0) {
    throw Error("native_audit_budget_check_failed");
  }
  return value;
}
