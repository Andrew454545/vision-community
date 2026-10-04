"""Finite diagnostic accounting of owned Windows native work, without polling.

Use in a single-threaded diagnostic process, never in the background worker.
The existing kill-on-close ownership remains in force. Windows' cumulative
job accounting includes exited children and peak committed memory; it is not
an inference-provider trace, a thermal reading or a throughput approval.
https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-queryinformationjobobject
"""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import threading
import time

from community import process_owner as owner


class Accounting(ctypes.Structure):
    _fields_ = [(name, ctypes.c_longlong) for name in
                ('userTime', 'kernelTime', 'periodUserTime', 'periodKernelTime')] + [
                (name, wintypes.DWORD) for name in ('pageFaults', 'totalProcesses', 'activeProcesses', 'terminatedProcesses')]


class IO(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in
                ('readOperations', 'writeOperations', 'otherOperations', 'readBytes', 'writeBytes', 'otherBytes')]


class BasicAndIO(ctypes.Structure):
    _fields_ = [('basic', Accounting), ('io', IO)]


class Limits(ctypes.Structure):
    _fields_ = [('processTime', ctypes.c_longlong), ('jobTime', ctypes.c_longlong),
                ('flags', wintypes.DWORD), ('minimumWorkingSet', ctypes.c_size_t),
                ('maximumWorkingSet', ctypes.c_size_t), ('activeProcesses', wintypes.DWORD),
                ('affinity', ctypes.c_size_t), ('priority', wintypes.DWORD), ('scheduling', wintypes.DWORD)]


class Extended(ctypes.Structure):
    _fields_ = [('basic', Limits), ('io', IO)] + [
                (name, ctypes.c_size_t) for name in
                ('processMemory', 'jobMemory', 'peakProcessMemory', 'peakJobMemory')]


class ProcessList(ctypes.Structure):
    _fields_ = [('assigned', wintypes.DWORD), ('listed', wintypes.DWORD), ('ids', ctypes.c_size_t * 64)]


class MeasuredJob(owner._WindowsJob):
    def __init__(self, receipt):
        self.receipt, self.assigned, self.measured = receipt, False, False
        super().__init__()
        self.api.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                                       wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        self.api.QueryInformationJobObject.restype = wintypes.BOOL

    def assign(self, pid):
        super().assign(pid)
        self.assigned = True

    def close(self):
        process_handles = []
        try:
            if self.handle and self.assigned and not self.measured:
                self.measured = True
                basic, limits = BasicAndIO(), Extended()
                for info_class, data in ((8, basic), (9, limits)):
                    returned = wintypes.DWORD()
                    if (not self.api.QueryInformationJobObject(self.handle, info_class, ctypes.byref(data),
                            ctypes.sizeof(data), ctypes.byref(returned)) or returned.value != ctypes.sizeof(data)):
                        self.receipt.update(status='MEASUREMENT_FAILED')
                        raise OSError('windows_job_accounting_unavailable')
                self.receipt.update(status='MEASURED',
                    cpuUserSeconds=basic.basic.userTime / 10_000_000,
                    cpuKernelSeconds=basic.basic.kernelTime / 10_000_000,
                    totalProcesses=basic.basic.totalProcesses, activeProcessesAtMeasurement=basic.basic.activeProcesses,
                    peakProcessCommittedBytes=limits.peakProcessMemory, peakJobCommittedBytes=limits.peakJobMemory,
                    readOperationBytes=basic.io.readBytes, writeOperationBytes=basic.io.writeBytes,
                    otherOperationBytes=basic.io.otherBytes, pageFaults=basic.basic.pageFaults,
                    completeAfterExit=basic.basic.activeProcesses == 0)
                if basic.basic.activeProcesses:
                    ids = ProcessList()
                    if not self.api.QueryInformationJobObject(self.handle, 3, ctypes.byref(ids), ctypes.sizeof(ids), None):
                        raise OSError('windows_job_process_accounting_unavailable')
                    self.api.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                                  ctypes.POINTER(wintypes.DWORD)]
                    self.api.QueryFullProcessImageNameW.restype = wintypes.BOOL
                    names = []
                    for pid in ids.ids[:ids.listed]:
                        process = self.api.OpenProcess(0x101000, False, pid)  # QUERY_LIMITED_INFORMATION | SYNCHRONIZE.
                        if not process:
                            if ctypes.get_last_error() != 87:  # An exited PID is invalid.
                                raise OSError('windows_job_process_handle_unavailable')
                            names.append('EXITED_BEFORE_NAME_READ')
                            continue
                        process_handles.append(process)
                        buffer, length = ctypes.create_unicode_buffer(32768), wintypes.DWORD(32768)
                        if not self.api.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(length)):
                            raise OSError('windows_job_process_name_unavailable')
                        names.append(Path(buffer.value).name)
                    self.receipt['activeProcessNamesAtMeasurement'] = names
        except Exception:
            # Report this only after run_owned has closed stdin and waited.
            # Raising inside its cleanup would interrupt that cleanup sequence.
            self.receipt.update(status='MEASUREMENT_FAILED')
        finally:
            # A measurement failure must never disable descendant cleanup.
            try:
                super().close()
            finally:
                self.api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
                self.api.WaitForSingleObject.restype = wintypes.DWORD
                deadline, stopped = time.monotonic() + 3, True
                for process in process_handles:
                    try:
                        stopped &= self.api.WaitForSingleObject(process, max(0, int((deadline-time.monotonic()) * 1000))) == 0
                    finally:
                        self.api.CloseHandle(process)
                self.receipt['remainingDescendantsStopped'] = stopped
                self.receipt['completeAfterOwnedCleanup'] = stopped and self.receipt.get('status') == 'MEASURED'


def measure_owned(argv, *, receipt, **kwargs):
    """Measure one operation. Receipt survives a native failure or timeout.

    This scoped adapter instruments the existing ownership implementation. It
    refuses concurrent callers rather than modifying a shared worker's factory.
    Query Windows exactly once before the private handle closes; no sampler.
    """
    if os.name != 'nt' or threading.current_thread() is not threading.main_thread() or threading.active_count() != 1:
        raise RuntimeError('windows_resource_measurement_requires_isolated_main_thread')
    receipt.update(version=1, status='NOT_MEASURED', productionQualified=False,
                   scope='owned_wrapper_and_native_descendants', measurement='WINDOWS_JOB_CUMULATIVE_ACCOUNTING',
                   memoryMetric='PEAK_COMMITTED_BYTES_NOT_WORKING_SET', accountingCutoff='BEFORE_OWNED_CLEANUP', nativeExitCode=None)
    original_factory = owner._make_job
    start = time.perf_counter()
    owner._make_job = lambda: MeasuredJob(receipt)
    try:
        result = owner.run_owned(argv, **kwargs)
        receipt['nativeExitCode'] = result.returncode
        if receipt['status'] != 'MEASURED':
            raise OSError('windows_job_accounting_unavailable')
        return result
    finally:
        owner._make_job = original_factory
        receipt['wallSeconds'] = time.perf_counter() - start
        if receipt.get('status') == 'MEASURED':
            receipt['cpuSeconds'] = receipt['cpuUserSeconds'] + receipt['cpuKernelSeconds']
            receipt['cpuSecondsPerWallSecond'] = receipt['cpuSeconds'] / receipt['wallSeconds']
