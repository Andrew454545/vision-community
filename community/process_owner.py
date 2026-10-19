"""Keep native work owned by its caller, including an abrupt caller exit.

Windows uses a private, non-inheritable kill-on-close Job Object. POSIX uses
a new process session and a blocking parent-pipe monitor. A startup gate keeps
native code from running before ownership is established. No shell is used.
"""
from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys
import threading


class _WindowsJob:
    def __init__(self):
        import ctypes
        from ctypes import wintypes

        class BasicLimits(ctypes.Structure):
            _fields_ = [("processTime", ctypes.c_longlong), ("jobTime", ctypes.c_longlong),
                        ("flags", wintypes.DWORD), ("minimumWorkingSet", ctypes.c_size_t),
                        ("maximumWorkingSet", ctypes.c_size_t), ("activeProcesses", wintypes.DWORD),
                        ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
                        ("scheduling", wintypes.DWORD)]

        class IOCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in
                        ("readOperations", "writeOperations", "otherOperations", "readBytes", "writeBytes", "otherBytes")]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [("basic", BasicLimits), ("io", IOCounters),
                        ("processMemory", ctypes.c_size_t), ("jobMemory", ctypes.c_size_t),
                        ("peakProcessMemory", ctypes.c_size_t), ("peakJobMemory", ctypes.c_size_t)]

        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateJobObjectW": ([ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
            "SetInformationJobObject": ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL),
            "OpenProcess": ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            "AssignProcessToJobObject": ([wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
            "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self.api, name)
            function.argtypes, function.restype = arguments, result
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError("native_process_ownership_unavailable")
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE; no breakaway.
        if not self.api.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            self.close()
            raise OSError("native_process_ownership_unavailable")

    def assign(self, pid):
        process = self.api.OpenProcess(0x0101, False, pid)  # SET_QUOTA | TERMINATE.
        if not process:
            raise OSError("native_process_ownership_unavailable")
        try:
            if not self.api.AssignProcessToJobObject(self.handle, process):
                raise OSError("native_process_ownership_unavailable")
        finally:
            self.api.CloseHandle(process)

    def close(self):
        if self.handle:
            handle, self.handle = self.handle, None
            if not self.api.CloseHandle(handle):
                raise OSError("native_process_ownership_cleanup_failed")


def _make_job():
    return _WindowsJob() if os.name == "nt" else None


def _wrapper_python():
    executable = Path(sys.executable)
    if os.name == "nt" and executable.name.lower() == "pythonw.exe":
        # A GUI interpreter may expose no stdin even with redirected handles.
        # Use its verified private console sibling, hidden by CREATE_NO_WINDOW.
        executable = executable.with_name("python.exe")
        if not executable.is_file() or executable.is_symlink():
            raise OSError("native_process_console_runtime_missing")
    return str(executable)


def run_owned(argv, *, env, cwd, stdout, stderr, timeout, creationflags=0, on_owned=None):
    """Run with file-backed logs; stop all owned children on timeout or exit.

    Retain stdin until completion: its EOF is the POSIX parent-death signal.
    The wrapper receives the original argv, environment and working directory.
    Windows console work is windowless, including when a caller omits flags.
    """
    job, process = _make_job(), None
    group_stop_attempted = False
    def stop_children():
        nonlocal group_stop_attempted
        if job is not None:
            job.close()
        elif process is not None and not group_stop_attempted:
            # A repeated signal after successful timeout cleanup can target
            # only protected OS helpers, or a later reused process-group ID.
            # Preserve a first denial; never retry the same group implicitly.
            group_stop_attempted = True
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    try:
        if os.name == "nt":
            # A new-console request would override NO_WINDOW. Work has file logs.
            creationflags = (creationflags & ~subprocess.CREATE_NEW_CONSOLE) | subprocess.CREATE_NO_WINDOW
        options = {"creationflags": creationflags} if os.name == "nt" else {"start_new_session": True}
        process = subprocess.Popen(
            [_wrapper_python(), "-I", "-B", str(Path(__file__).resolve()), str(creationflags), "--", *argv],
            env=env, cwd=str(cwd), stdin=subprocess.PIPE, stdout=stdout, stderr=stderr,
            close_fds=True, **options,
        )
        if job is not None:
            job.assign(process.pid)
        if on_owned is not None:
            on_owned(process.pid)
        process.stdin.write(b"START\n")
        process.stdin.flush()
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as error:
            stop_children()
            process.wait(timeout=10)
            raise subprocess.TimeoutExpired(argv, timeout) from error
        if code in (77, 78):
            raise OSError("native_process_launch_failed")
        return subprocess.CompletedProcess(argv, code)
    finally:
        try:
            stop_children()
        finally:
            # A denied group/job close must still release the parent pipe and
            # stop/wait the wrapper. The cleanup error remains a failure.
            if process is not None:
                try:
                    process.stdin.close()
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=10)


def _wrapper():
    if len(sys.argv) < 4 or sys.argv[2] != "--":
        return 77
    # EOF before assignment means the caller died before granting ownership.
    if sys.stdin.buffer.readline(16) != b"START\n":
        return 77
    if os.name != "nt":
        def parent_pipe():
            # This read blocks, consumes no recurring CPU and holds no credentials.
            # Raw fd reads avoid holding Python's buffered-stdin lock while
            # interpreter shutdown joins no daemon thread.
            if not os.read(sys.stdin.fileno(), 1):
                os.killpg(os.getpgrp(), signal.SIGKILL)
        threading.Thread(target=parent_pipe, name="native-parent-pipe", daemon=True).start()
    try:
        flags = int(sys.argv[1])
        options = {"creationflags": flags} if os.name == "nt" else {}
        return subprocess.call(sys.argv[3:], stdin=subprocess.DEVNULL, close_fds=True, **options)
    except OSError:
        # Fixed diagnostic only: argv and exception text may contain private paths.
        print("native_process_launch_failed", file=sys.stderr, flush=True)
        return 78


if __name__ == "__main__":
    raise SystemExit(_wrapper())
