"""Finite diagnostic accounting of owned Windows native work.

Use in a single-threaded diagnostic process, never in the background worker.
The existing kill-on-close ownership remains in force. Windows' cumulative
job accounting includes exited children and peak committed memory; it is not
an inference-provider trace, a thermal reading or a throughput approval. An
explicit option also samples only this diagnostic's private job working sets;
it never monitors the installed background worker or unrelated applications.
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


class MemoryCounters(ctypes.Structure):
    _fields_ = [('size', ctypes.c_uint32), ('pageFaults', ctypes.c_uint32)] + [
        (name, ctypes.c_size_t) for name in ('peakWorkingSet', 'workingSet', 'peakPagedPool', 'pagedPool',
                                          'peakNonPagedPool', 'nonPagedPool', 'committed', 'peakCommitted')]


class WorkingSetObserver:
    """Bounded, opt-in samples; sums include shared pages and can miss short peaks."""
    def __init__(self, job, interval=0.25):
        self.job, self.interval = job, interval
        self.job_handle = job.handle
        if not self.job_handle:
            raise OSError('windows_working_set_private_job_unavailable')
        self.handles, self.peaks = {}, {}
        self.samples, self.maximum_observed, self.failed = 0, 0, False
        self.stop_event = threading.Event()
        self.thread = None
        self.api = job.api
        self.api.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(MemoryCounters), wintypes.DWORD]
        self.api.K32GetProcessMemoryInfo.restype = wintypes.BOOL
        self.api.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
        self.api.IsProcessInJob.restype = wintypes.BOOL
        self.api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.api.WaitForSingleObject.restype = wintypes.DWORD

    def process_running(self, handle):
        state = self.api.WaitForSingleObject(handle,0)
        if state not in (0,258):  # WAIT_OBJECT_0, WAIT_TIMEOUT; never treat WAIT_FAILED as live.
            raise OSError('windows_working_set_process_state_unavailable')
        return state==258

    def sample(self, *, final=False):
        if self.stop_event.is_set() and not final: return
        ids = ProcessList()
        # Never pass NULL after owner cleanup: Windows interprets it as the
        # calling process's current job, which is outside this observation.
        if (not self.api.QueryInformationJobObject(self.job_handle, 3, ctypes.byref(ids), ctypes.sizeof(ids), None)
                or ids.assigned>64 or ids.listed>64):
            raise OSError('windows_working_set_process_list_unavailable')
        for pid in ids.ids[:ids.listed]:
            if self.stop_event.is_set() and not final: return
            if pid in self.handles: continue
            handle = self.api.OpenProcess(0x101000, False, pid)  # QUERY_LIMITED_INFORMATION | SYNCHRONIZE.
            if not handle:
                if ctypes.get_last_error()==87: continue  # Exited before observation; coverage remains incomplete.
                raise OSError('windows_working_set_process_handle_unavailable')
            member = wintypes.BOOL()
            if not self.api.IsProcessInJob(handle,self.job_handle,ctypes.byref(member)) or not member.value:
                self.api.CloseHandle(handle)
                raise OSError('windows_working_set_process_not_owned')
            # Holding the handle pins this process identity against PID reuse.
            self.handles[pid] = handle
        current = 0
        for pid,handle in self.handles.items():
            if self.stop_event.is_set() and not final: return
            data = MemoryCounters()
            data.size = ctypes.sizeof(data)
            if not self.api.K32GetProcessMemoryInfo(handle,ctypes.byref(data),ctypes.sizeof(data)):
                if not self.process_running(handle): continue  # An exited address space may no longer be readable.
                raise OSError('windows_working_set_counters_unavailable')
            self.peaks[pid] = max(self.peaks.get(pid,0),data.peakWorkingSet)
            if self.process_running(handle):
                current += data.workingSet
        self.maximum_observed = max(self.maximum_observed,current)
        self.samples += 1

    def start(self):
        # Sample the gated wrapper before granting START to its native child.
        try:
            self.sample()
        except Exception:
            self.failed = True
            raise
        def observe():
            try:
                while not self.stop_event.wait(self.interval): self.sample()
            except Exception:
                self.failed = True
        self.thread = threading.Thread(target=observe,name='private-native-memory-diagnostic',daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)
            if self.thread.is_alive(): return False
        try:
            self.sample(final=True)
        except Exception:
            self.failed = True
        return True

    def receipt(self, accounted, stopped):
        observed = len(self.peaks)
        return {'status':'FAILED' if self.failed or not stopped else
                ('SAMPLED' if observed==accounted else 'SAMPLED_INCOMPLETE_PROCESS_COVERAGE'),
                'scope':'THIS_PRIVATE_JOB_ONLY', 'intervalSeconds':self.interval, 'samples':self.samples,
                'observedProcesses':observed, 'accountedProcesses':accounted,
                'allAccountedProcessesObserved':observed==accounted,
                'maximumObservedWorkingSetBytes':self.maximum_observed,
                'maximumReportedProcessPeakWorkingSetBytes':max(self.peaks.values(),default=0),
                'sumReportedProcessPeaksBytes':sum(self.peaks.values()), 'samplerStopped':stopped,
                'peakBetweenSamplesMayBeMissed':True, 'readsAcrossProcessesAreNotAtomic':True,
                'exactSimultaneousPeakEstablished':False, 'sharedPagesMayBeCountedMoreThanOnce':True,
                'processPeaksCoverObservedSamplesOnly':True, 'gpuMemoryMeasured':False}

    def close_handles(self):
        for handle in self.handles.values(): self.api.CloseHandle(handle)
        self.handles.clear()


class MeasuredJob(owner._WindowsJob):
    def __init__(self, receipt):
        self.receipt, self.assigned, self.measured = receipt, False, False
        self.working_set = None
        super().__init__()
        self.api.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                                       wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        self.api.QueryInformationJobObject.restype = wintypes.BOOL

    def assign(self, pid):
        super().assign(pid)
        self.assigned = True

    def close(self):
        if not self.handle:
            return  # Repeated cleanup must not overwrite an earlier wait failure.
        process_handles = []
        sampler_stopped = True
        try:
            if self.working_set:
                sampler_stopped = self.working_set.stop()
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
                if self.working_set:
                    self.receipt['workingSetObservation'] = self.working_set.receipt(basic.basic.totalProcesses,sampler_stopped)
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
                if self.working_set and self.receipt.get('workingSetObservation',{}).get('status')=='NOT_STARTED':
                    self.receipt['workingSetObservation'] = self.working_set.receipt(
                        self.receipt.get('totalProcesses'),sampler_stopped)
                if self.working_set and sampler_stopped:
                    self.working_set.close_handles()


def measure_owned(argv, *, receipt, sample_working_set=False, **kwargs):
    """Measure one operation. Receipt survives a native failure or timeout.

    This scoped adapter instruments the existing ownership implementation. It
    refuses concurrent callers rather than modifying a shared worker's factory.
    CPU/commit accounting is queried once. Optional working-set observation is
    finite and restricted to the newly created private job, with explicit sample
    and process-coverage limits; it never measures shared physical RAM exactly.
    """
    if os.name != 'nt' or threading.current_thread() is not threading.main_thread() or threading.active_count() != 1:
        raise RuntimeError('windows_resource_measurement_requires_isolated_main_thread')
    receipt.update(version=1, status='NOT_MEASURED', productionQualified=False,
                   scope='owned_wrapper_and_native_descendants', measurement='WINDOWS_JOB_CUMULATIVE_ACCOUNTING',
                   memoryMetric='PEAK_COMMITTED_BYTES_NOT_WORKING_SET', accountingCutoff='BEFORE_OWNED_CLEANUP', nativeExitCode=None)
    original_factory = owner._make_job
    start = time.perf_counter()
    jobs = []
    def factory():
        job = MeasuredJob(receipt)
        jobs.append(job)
        if sample_working_set:
            try:
                job.working_set = WorkingSetObserver(job)
            except Exception:
                job.close()
                raise
        return job
    owner._make_job = factory
    callback = kwargs.pop('on_owned',None)
    def on_owned(pid):
        if sample_working_set: jobs[0].working_set.start()
        if callback: callback(pid)
    if sample_working_set:
        receipt.update(version=2,workingSetObservation={'status':'NOT_STARTED'})
    try:
        result = owner.run_owned(argv, on_owned=on_owned, **kwargs)
        receipt['nativeExitCode'] = result.returncode
        if receipt['status'] != 'MEASURED':
            raise OSError('windows_job_accounting_unavailable')
        if not receipt['completeAfterOwnedCleanup']:
            raise OSError('windows_job_cleanup_unverified')
        if sample_working_set and receipt['workingSetObservation']['status']=='FAILED':
            raise OSError('windows_working_set_observation_unavailable')
        return result
    finally:
        owner._make_job = original_factory
        receipt['wallSeconds'] = time.perf_counter() - start
        if receipt.get('status') == 'MEASURED':
            receipt['cpuSeconds'] = receipt['cpuUserSeconds'] + receipt['cpuKernelSeconds']
            receipt['cpuSecondsPerWallSecond'] = receipt['cpuSeconds'] / receipt['wallSeconds']
