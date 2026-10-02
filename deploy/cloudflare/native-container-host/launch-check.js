// Fixed, offline diagnostic: separate VM launch from Python/runtime startup.
// No secrets, commands, locations, model inference or readiness are accepted.
export const LAUNCH_CHECK = String.raw`import os, sys, json, platform
sys.path.insert(0, '/opt/vision/client')
sys.path.insert(0, '/opt/vision')
from pathlib import Path
phase = 'module_import'
try:
    import server
    phase = 'runtime_manifest'
    root = Path('/opt/vision')
    package = server.native.strict_json((root / 'runtime-package.json').read_bytes())
    phase = 'state_directory'
    state = Path('/state')
    state.mkdir(mode=0o700, exist_ok=True)
    phase = 'runtime_identity'
    host = server.Host(root / 'runtime/runtime.json', package['runtimeSha256'], state)
    print(json.dumps({'status': 'native_launch_check_passed',
        'runtimeSha256': package['runtimeSha256'], 'pythonVersion': platform.python_version(),
        'uid': os.getuid(), 'modelFilesValidated': True, 'productionQualified': False}), flush=True)
except Exception as error:
    allowed = {'invalid_native_runtime', 'incomplete_native_runtime', 'runtime_changed',
        'adapter_changed', 'engine_source_changed', 'invalid_runtime_file_pin',
        'runtime_size_limit', 'runtime_file_changed', 'unpinned_runtime_directory',
        'unpinned_runtime_file', 'invalid_native_countries', 'linked_engine_path', 'invalid_engine_path'}
    message, number = str(error), getattr(error, 'errno', None)
    print(json.dumps({'status': 'native_boot_unavailable', 'phase': phase,
        'code': message if message in allowed else 'native_boot_failed',
        'errno': number if type(number) is int and 0 <= number <= 4095 else None}), flush=True)
    sys.exit(1)
`;

export function checkedLaunchReceipt(value, runtimeSha256) {
  if (!value || typeof value !== "object" || Array.isArray(value)
      || Object.keys(value).sort().join(",") !== "modelFilesValidated,productionQualified,pythonVersion,runtimeSha256,status,uid"
      || value.status !== "native_launch_check_passed" || value.runtimeSha256 !== runtimeSha256
      || value.pythonVersion !== "3.12.15" || ![0, 10001].includes(value.uid)
      || value.modelFilesValidated !== true || value.productionQualified !== false) {
    throw Error("native_launch_check_failed");
  }
  return value;
}

export function stderrClass(bytes) {
  const text = new TextDecoder().decode(bytes);
  // Inspect only to select a constant class; never return/retain raw output.
  for (const type of ["SyntaxError", "IndentationError", "ModuleNotFoundError", "ImportError", "PermissionError", "FileNotFoundError"]) {
    if (new RegExp(`^${type}:`, "m").test(text)) return type;
  }
  return null;
}
