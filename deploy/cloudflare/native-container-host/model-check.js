// Fixed operator diagnostic using the first public gen4-v1 canary location.
// Accepts no commands, URLs, credentials, poses or volunteer records.
export const MODEL_CHECK = String.raw`import sys
sys.path.insert(0, '/opt/vision/client')
import hashlib, json, resource, tempfile, time
from pathlib import Path
from types import SimpleNamespace
from community.native_scene_search import NativeSceneRuntime
from community.native_scene_verifier import NativeSceneVerifier
from community.four_view import valid_four_view_record

started = time.monotonic()
try:
    runtime_sha = 'bbc60e94e6590c657f256d89f6d63db47f7f3d53d1ba37ffeafba07b6211d64e'
    runtime = NativeSceneRuntime(Path('/opt/vision/runtime/runtime.json'), runtime_sha)
    record = {'locationId': 145586295, 'lat': 41.79270699022923,
        'lng': 20.39504004993244, 'heading': 70.54816, 'pitch': 0, 'zoom': 0,
        'assetId': 'Je141ivXzUUx4ro1j8_3vw', 'country': 'Albania', 'cameraGeneration': 'gen4'}
    with tempfile.TemporaryDirectory(prefix='operator-model-check-', dir='/state') as temporary:
        runner = SimpleNamespace(runtime=runtime, timeout=90)
        blob = NativeSceneVerifier.recompute(runner, [record], Path(temporary))
        if not valid_four_view_record(blob):
            raise ValueError('invalid_model_output')
        runtime.verify_runtime()
        receipt = {'status': 'native_model_check_passed', 'runtimeSha256': runtime_sha,
            'locations': 1, 'views': 4, 'fetchErrors': 0, 'inferenceErrors': 0,
            'bytes': len(blob), 'outputSha256': hashlib.sha256(blob).hexdigest(),
            'sceneGraph': 'fp32', 'executionProvider': 'cpu', 'threads': 1,
            'elapsedSeconds': round(time.monotonic() - started, 3),
            'peakChildRssKiB': resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
            'productionQualified': False}
    print(json.dumps(receipt), flush=True)
except Exception:
    print('{"error":"native_model_check_failed"}', flush=True)
    sys.exit(1)
`;

export function checkedModelReceipt(value, runtimeSha256) {
  const expected = ["status", "runtimeSha256", "locations", "views", "fetchErrors", "inferenceErrors",
    "bytes", "outputSha256", "sceneGraph", "executionProvider", "threads", "elapsedSeconds",
    "peakChildRssKiB", "productionQualified"];
  if (!value || typeof value !== "object" || Array.isArray(value)
      || Object.keys(value).sort().join(",") !== expected.sort().join(",")
      || value.status !== "native_model_check_passed" || value.runtimeSha256 !== runtimeSha256
      || value.locations !== 1 || value.views !== 4 || value.bytes !== 3080
      || value.fetchErrors !== 0 || value.inferenceErrors !== 0
      || value.sceneGraph !== "fp32" || value.executionProvider !== "cpu" || value.threads !== 1
      || !/^[0-9a-f]{64}$/.test(value.outputSha256) || value.productionQualified !== false
      || !Number.isFinite(value.elapsedSeconds) || value.elapsedSeconds <= 0 || value.elapsedSeconds > 105
      || !Number.isSafeInteger(value.peakChildRssKiB) || value.peakChildRssKiB <= 0) {
    throw Error("native_model_check_failed");
  }
  return value;
}
