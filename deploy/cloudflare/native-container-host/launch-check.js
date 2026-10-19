// Fixed, offline diagnostic: separate VM launch from runtime/HTTP startup.
// Only generated, disposable credentials are used; no operator input or inference.
export const LAUNCH_CHECK = String.raw`import os, sys, json, platform, secrets, threading
from http.client import HTTPConnection
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
    phase = 'server_credentials'
    service, operator = secrets.token_hex(32), secrets.token_hex(32)
    front = server.make_server(host, service, operator, bind='127.0.0.1', port=0)
    runner = threading.Thread(target=front.serve_forever, daemon=True)
    runner.start()
    try:
        phase = 'http_self_check'
        def request(method, path, credential=None):
            connection = HTTPConnection('127.0.0.1', front.server_address[1], timeout=2)
            try:
                headers = {'Content-Type': 'application/json'}
                if credential is not None:
                    headers['Authorization'] = 'Bearer ' + credential
                connection.request(method, path, body=b'{}' if method == 'POST' else None, headers=headers)
                response = connection.getresponse()
                raw = response.read(4097)
                if len(raw) > 4096 or response.getheader('Cache-Control') != 'no-store':
                    raise ValueError('native_http_self_check_failed')
                return response.status, json.loads(raw)
            finally:
                connection.close()
        if request('GET', '/health') != (401, {'error': 'unauthorized'}):
            raise ValueError('native_http_self_check_failed')
        if request('GET', '/health', operator) != (401, {'error': 'unauthorized'}):
            raise ValueError('native_http_self_check_failed')
        status, health = request('GET', '/health', service)
        if status != 200 or health != {'status': 'native_host_available',
                'runtimeSha256': package['runtimeSha256'], 'identityOnly': True,
                'auditReady': False, 'searchReady': False, 'activeNativeProcessesMaximum': 1}:
            raise ValueError('native_http_self_check_failed')
        if request('POST', '/operator/bundle', service) != (401, {'error': 'unauthorized'}):
            raise ValueError('native_http_self_check_failed')
        # Authenticated invalid content must stop before activation or native work.
        if request('POST', '/operator/bundle', operator) != (400, {'error': 'invalid_request'}):
            raise ValueError('native_http_self_check_failed')
    finally:
        front.shutdown()
        front.server_close()
        runner.join(timeout=2)
    print(json.dumps({'status': 'native_launch_check_passed',
        'runtimeSha256': package['runtimeSha256'], 'pythonVersion': platform.python_version(),
        'uid': os.getuid(), 'modelFilesValidated': True, 'httpServerChecked': True,
        'serviceAuthChecked': True, 'operatorAuthChecked': True, 'productionQualified': False}), flush=True)
except Exception as error:
    allowed = {'invalid_native_runtime', 'incomplete_native_runtime', 'runtime_changed',
        'adapter_changed', 'engine_source_changed', 'invalid_runtime_file_pin',
        'runtime_size_limit', 'runtime_file_changed', 'unpinned_runtime_directory',
        'unpinned_runtime_file', 'invalid_native_countries', 'linked_engine_path', 'invalid_engine_path',
        'private_host_secret_required', 'separate_operator_secret_required', 'native_http_self_check_failed'}
    message, number = str(error), getattr(error, 'errno', None)
    print(json.dumps({'status': 'native_boot_unavailable', 'phase': phase,
        'code': message if message in allowed else 'native_boot_failed',
        'errno': number if type(number) is int and 0 <= number <= 4095 else None}), flush=True)
    sys.exit(1)
`;

export function checkedLaunchReceipt(value, runtimeSha256) {
  if (!value || typeof value !== "object" || Array.isArray(value)
      || Object.keys(value).sort().join(",") !== "httpServerChecked,modelFilesValidated,operatorAuthChecked,productionQualified,pythonVersion,runtimeSha256,serviceAuthChecked,status,uid"
      || value.status !== "native_launch_check_passed" || value.runtimeSha256 !== runtimeSha256
      || value.pythonVersion !== "3.12.15" || ![0, 10001].includes(value.uid)
      || value.modelFilesValidated !== true || value.httpServerChecked !== true
      || value.serviceAuthChecked !== true || value.operatorAuthChecked !== true || value.productionQualified !== false) {
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
