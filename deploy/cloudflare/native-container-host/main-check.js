// Fixed private diagnostic of the immutable image's actual server main program.
// The two credentials stay inside the bound Worker/container process environment.
export const MAIN_CHECK = String.raw`import json, os, platform, re, signal, subprocess, sys, threading, time
from http.client import HTTPConnection
from pathlib import Path
phase = 'main_program'
child = None
buffers = {'stdout': bytearray(), 'stderr': bytearray()}
overflow = threading.Event()
allowed = {'invalid_native_runtime', 'incomplete_native_runtime', 'runtime_changed',
    'adapter_changed', 'engine_source_changed', 'invalid_runtime_file_pin',
    'runtime_size_limit', 'runtime_file_changed', 'unpinned_runtime_directory',
    'unpinned_runtime_file', 'invalid_native_countries', 'private_host_secret_required',
    'separate_operator_secret_required', 'linked_engine_path', 'invalid_engine_path'}
def stop():
    if child is None or child.poll() is not None:
        return
    try:
        if os.name == 'posix':
            os.killpg(child.pid, signal.SIGTERM)
        else:
            child.terminate()
    except ProcessLookupError:
        pass  # The child can exit between poll() and signalling its group.
    try:
        child.wait(timeout=2)
    except subprocess.TimeoutExpired:
        try:
            if os.name == 'posix':
                os.killpg(child.pid, signal.SIGKILL)
            else:
                child.kill()
        except ProcessLookupError:
            pass
        child.wait(timeout=2)
def drain(name, stream):
    try:
        while True:
            block = stream.read(1024)
            if not block:
                break
            if len(buffers[name]) + len(block) > 8192:
                overflow.set()
                break
            buffers[name].extend(block)
    finally:
        stream.close()
def request(method, path, credential=None):
    connection = HTTPConnection('127.0.0.1', 8080, timeout=1)
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
try:
    package = json.loads(Path('/opt/vision/runtime-package.json').read_bytes())
    service, operator = os.environ.get('VISION_HOST_SECRET'), os.environ.get('VISION_HOST_OPERATOR_SECRET')
    child = subprocess.Popen([sys.executable, '-B', '/opt/vision/server.py'],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=dict(os.environ), start_new_session=True)
    readers = [threading.Thread(target=drain, args=(name, getattr(child, name)), daemon=True)
        for name in buffers]
    for reader in readers:
        reader.start()
    end = time.monotonic() + 20
    health = None
    while time.monotonic() < end:
        if overflow.is_set() or child.poll() is not None:
            raise ValueError('native_main_program_failed')
        try:
            health = request('GET', '/health', service)
            break
        except (OSError, TimeoutError):
            time.sleep(0.05)
    if health is None:
        raise ValueError('native_main_program_failed')
    phase = 'http_self_check'
    if health != (200, {'status': 'native_host_available', 'runtimeSha256': package['runtimeSha256'],
            'identityOnly': True, 'auditReady': False, 'searchReady': False, 'activeNativeProcessesMaximum': 1}):
        raise ValueError('native_http_self_check_failed')
    if request('GET', '/health') != (401, {'error': 'unauthorized'}):
        raise ValueError('native_http_self_check_failed')
    if request('GET', '/health', operator) != (401, {'error': 'unauthorized'}):
        raise ValueError('native_http_self_check_failed')
    if request('POST', '/operator/bundle', service) != (401, {'error': 'unauthorized'}):
        raise ValueError('native_http_self_check_failed')
    if request('POST', '/operator/bundle', operator) != (400, {'error': 'invalid_request'}):
        raise ValueError('native_http_self_check_failed')
    result = {'status': 'native_main_check_passed', 'runtimeSha256': package['runtimeSha256'],
        'pythonVersion': platform.python_version(), 'uid': os.getuid(), 'modelFilesValidated': True,
        'httpServerChecked': True, 'serviceAuthChecked': True, 'operatorAuthChecked': True,
        'mainProgramChecked': True, 'productionQualified': False}
except Exception as error:
    stop()
    for reader in locals().get('readers', []):
        reader.join(timeout=1)
    code = str(error) if str(error) in allowed | {'native_http_self_check_failed', 'native_main_program_failed'} else 'native_boot_failed'
    if isinstance(error, UnicodeError):
        code = 'native_main_hostname_encoding_error'
    number = getattr(error, 'errno', None)
    number = number if type(number) is int and 0 <= number <= 4095 else None
    text = bytes(buffers['stderr']).decode('utf-8', errors='replace')
    classes = {'NameError': 'native_main_name_error', 'UnboundLocalError': 'native_main_name_error',
        'TypeError': 'native_main_type_error', 'AttributeError': 'native_main_attribute_error',
        'PermissionError': 'native_main_permission_error', 'FileNotFoundError': 'native_main_file_missing',
        'OSError': 'native_main_os_error', 'RuntimeError': 'native_main_runtime_error',
        'socket.gaierror': 'native_main_dns_error', 'socket.herror': 'native_main_dns_error',
        'UnicodeError': 'native_main_hostname_encoding_error', 'UnicodeEncodeError': 'native_main_hostname_encoding_error',
        'UnicodeDecodeError': 'native_main_hostname_encoding_error'}
    for line in text.splitlines():
        line = re.sub(r'\x1b\[[0-9;]*m', '', line).strip()
        if line.startswith('ModuleNotFoundError:') or line.startswith('ImportError:'):
            code = 'native_module_missing'
        elif line.partition(': ')[0] in {'ValueError', 'NativeSearchError', 'SnapshotError',
                'community.native_scene_search.NativeSearchError', 'community.search_snapshot.SnapshotError'} and line.partition(': ')[2] in allowed:
            code = line.partition(': ')[2]
        else:
            kind = line.partition(':')[0]
            if kind in classes:
                code = classes[kind]
                match = re.match(r'^[A-Za-z]+: \[Errno ([0-9]{1,4})\]', line)
                if match and 0 <= int(match[1]) <= 4095:
                    number = int(match[1])
    child_code = child.poll() if child is not None else None
    frames = re.findall(r'File "/opt/vision/server.py", line ([0-9]{1,4}),', text)
    result = {'status': 'native_boot_unavailable', 'phase': phase, 'code': code, 'errno': number,
        'childExitCode': child_code if type(child_code) is int and -255 <= child_code <= 255 else None,
        'stdoutBytes': len(buffers['stdout']), 'stderrBytes': len(buffers['stderr']),
        'serverLine': int(frames[-1]) if frames and 1 <= int(frames[-1]) <= 9999 else None}
finally:
    stop()
    for reader in locals().get('readers', []):
        reader.join(timeout=1)
print(json.dumps(result), flush=True)
sys.exit(0 if result['status'] == 'native_main_check_passed' else 1)
`;

export function checkedMainReceipt(value, runtimeSha256) {
  const keys = "httpServerChecked,mainProgramChecked,modelFilesValidated,operatorAuthChecked,productionQualified,pythonVersion,runtimeSha256,serviceAuthChecked,status,uid";
  if (!value || typeof value !== "object" || Array.isArray(value)
      || Object.keys(value).sort().join(",") !== keys
      || value.status !== "native_main_check_passed" || value.runtimeSha256 !== runtimeSha256
      || value.pythonVersion !== "3.12.15" || ![0, 10001].includes(value.uid)
      || ["httpServerChecked", "mainProgramChecked", "modelFilesValidated", "operatorAuthChecked", "serviceAuthChecked"].some(k => value[k] !== true)
      || value.productionQualified !== false) throw Error("native_main_check_failed");
  return value;
}

export function checkedMainFailureReceipt(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)
      || Object.keys(value).sort().join(",") !== "childExitCode,code,errno,phase,serverLine,status,stderrBytes,stdoutBytes"
      || !(value.childExitCode === null || Number.isInteger(value.childExitCode) && value.childExitCode >= -255 && value.childExitCode <= 255)
      || !(value.serverLine === null || Number.isInteger(value.serverLine) && value.serverLine >= 1 && value.serverLine <= 9999)
      || ["stdoutBytes", "stderrBytes"].some(k => !Number.isInteger(value[k]) || value[k] < 0 || value[k] > 8192)) {
    throw Error("native_boot_diagnostic_invalid");
  }
  return { childExitCode: value.childExitCode, stdoutBytes: value.stdoutBytes, stderrBytes: value.stderrBytes, serverLine: value.serverLine };
}
