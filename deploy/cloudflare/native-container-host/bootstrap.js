// Fixed entrypoint; startup diagnostics never include exception text or paths.
export const BOOTSTRAP = String.raw`import os, sys
sys.path.insert(0, '/opt/vision/client')
sys.path.insert(0, '/opt/vision')
import hmac, json, threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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
    front = server.make_server(host, os.environ.get('VISION_HOST_SECRET'), os.environ.get('VISION_HOST_OPERATOR_SECRET'))
except Exception as error:
    allowed = {'invalid_native_runtime', 'incomplete_native_runtime', 'runtime_changed',
        'adapter_changed', 'engine_source_changed', 'invalid_runtime_file_pin',
        'runtime_size_limit', 'runtime_file_changed', 'unpinned_runtime_directory',
        'unpinned_runtime_file', 'invalid_native_countries', 'private_host_secret_required',
        'separate_operator_secret_required', 'linked_engine_path', 'invalid_engine_path'}
    message = str(error)
    number = getattr(error, 'errno', None)
    receipt = {'status': 'native_boot_unavailable', 'phase': phase,
        'code': message if message in allowed else 'native_boot_failed',
        'errno': number if type(number) is int and 0 <= number <= 4095 else None}
    data = json.dumps(receipt).encode('utf-8')
    credential = os.environ.get('VISION_HOST_SECRET', '')
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(5)
        def log_message(self, *_):
            pass
        def do_GET(self):
            headers = self.headers.get_all('Authorization', [])
            authorized = credential and len(headers) == 1 and hmac.compare_digest(
                headers[0].encode('utf-8'), ('Bearer ' + credential).encode('utf-8'))
            body = data if authorized and self.path == '/health' else b'{"error":"unavailable"}'
            self.send_response(200 if authorized and self.path == '/health' else 404)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    class DiagnosticServer(ThreadingHTTPServer):
        daemon_threads = True
        request_queue_size = 2
        def handle_error(self, *_):
            pass
    front = DiagnosticServer(('0.0.0.0', 8080), Handler)
    timer = threading.Timer(45, front.shutdown)
    timer.daemon = True
    timer.start()
    try:
        front.serve_forever()
    finally:
        timer.cancel()
        front.server_close()
    sys.exit(1)
else:
    try:
        front.serve_forever()
    finally:
        front.server_close()
`;

const PHASES = new Set(["module_import", "runtime_manifest", "state_directory", "runtime_identity", "server_credentials"]);
const CODES = new Set(["native_boot_failed", "invalid_native_runtime", "incomplete_native_runtime", "runtime_changed",
  "adapter_changed", "engine_source_changed", "invalid_runtime_file_pin", "runtime_size_limit", "runtime_file_changed",
  "unpinned_runtime_directory", "unpinned_runtime_file", "invalid_native_countries", "private_host_secret_required",
  "separate_operator_secret_required", "linked_engine_path", "invalid_engine_path"]);

export function checkedBootReceipt(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)
      || Object.keys(value).sort().join(",") !== "code,errno,phase,status"
      || value.status !== "native_boot_unavailable" || !PHASES.has(value.phase) || !CODES.has(value.code)
      || !(value.errno === null || Number.isInteger(value.errno) && value.errno >= 0 && value.errno <= 4095)) {
    throw Error("native_boot_diagnostic_invalid");
  }
  return { phase: value.phase, code: value.code, errno: value.errno };
}
