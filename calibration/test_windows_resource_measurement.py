import os
import ctypes
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from calibration.windows_resource_measurement import MemoryCounters, MeasuredJob, ProcessList, WorkingSetObserver, measure_owned
from community import process_owner as owner


class MeasurementTest(unittest.TestCase):
    def measured_descendant(self,configure,receipt,seconds=60):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            # Independently hold the fixture child's identity before the
            # measurement hooks can deliberately break enumeration/membership.
            # Closing a kill-on-close job initiates asynchronous termination;
            # wait before TemporaryDirectory removes the child's working folder.
            from ctypes import wintypes
            cleanup_api=ctypes.WinDLL('kernel32',use_last_error=True)
            cleanup_api.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
            cleanup_api.OpenProcess.restype=wintypes.HANDLE
            cleanup_api.IsProcessInJob.argtypes=[wintypes.HANDLE,wintypes.HANDLE,ctypes.POINTER(wintypes.BOOL)]
            cleanup_api.IsProcessInJob.restype=wintypes.BOOL
            cleanup_api.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
            cleanup_api.WaitForSingleObject.restype=wintypes.DWORD
            cleanup_api.CloseHandle.argtypes=[wintypes.HANDLE]
            cleanup_api.CloseHandle.restype=wintypes.BOOL
            held=[]
            class ConfiguredJob(MeasuredJob):
                def __init__(self,value):
                    super().__init__(value)
                    configure(self,root)
                def close(job):
                    try:
                        if job.handle and (root/'started').is_file():
                            process=cleanup_api.OpenProcess(0x101000,False,int((root/'started').read_text()))
                            if process:
                                member=wintypes.BOOL()
                                if cleanup_api.IsProcessInJob(process,job.handle,ctypes.byref(member)) and member.value:
                                    held.append(process)
                                else:
                                    cleanup_api.CloseHandle(process)
                                    raise OSError('fixture_child_not_owned')
                            elif ctypes.get_last_error()!=87:
                                raise OSError('fixture_child_handle_unavailable')
                    finally:
                        super(ConfiguredJob,job).close()
            child=('import os,time; from pathlib import Path; '
                'Path("started.part").write_text(str(os.getpid())); Path("started.part").replace("started"); ')
            child+=('time.sleep('+str(seconds)+')' if seconds is not None else
                '\nwhile not Path("exit-requested").exists(): time.sleep(0.01)')
            source=('import subprocess,sys,time; from pathlib import Path; '
                'subprocess.Popen([sys.executable,"-I","-c",'+repr(child)+'],creationflags=0x08000000,'
                'stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); '
                '\nwhile not Path("started").exists(): time.sleep(0.01)')
            with patch('calibration.windows_resource_measurement.MeasuredJob',ConfiguredJob), (root/'out.log').open('wb') as output:
                try:
                    return measure_owned([sys.executable,'-I','-c',source],receipt=receipt,
                        env=dict(os.environ),cwd=root,stdout=output,stderr=output,timeout=10,creationflags=0x08000000)
                finally:
                    for process in held:
                        try:self.assertEqual(cleanup_api.WaitForSingleObject(process,3000),0,'Fixture child did not finish owned shutdown')
                        finally:cleanup_api.CloseHandle(process)

    @unittest.skipUnless(os.name=='nt','Windows job accounting')
    def test_name_read_failure_after_pinned_owned_process_exit_keeps_accounting(self):
        def configure(job,root):
            from ctypes import wintypes
            wait=job.api.WaitForSingleObject
            wait.argtypes=[wintypes.HANDLE,wintypes.DWORD];wait.restype=wintypes.DWORD
            get_pid=job.api.GetProcessId
            get_pid.argtypes=[wintypes.HANDLE];get_pid.restype=wintypes.DWORD
            def read_name(process,_flags,buffer,length):
                if get_pid(process)==int((root/'started').read_text()):
                    (root/'exit-requested').write_text('exit after membership was checked')
                    self.assertEqual(wait(process,3000),0)  # Actual exit on this held identity.
                    ctypes.set_last_error(31)
                    return False
                # This guard injects one controlled leaf's name-read failure.
                # Mock success for the other owned fixture wrappers so their
                # real transient exit/name failures cannot obscure that case.
                # Separate real-name and live-failure guards retain coverage.
                buffer.value='CONTROLLED_FIXTURE_PROCESS'
                ctypes.cast(length,ctypes.POINTER(wintypes.DWORD))[0]=len(buffer.value)
                return True
            job.api.QueryFullProcessImageNameW=read_name
        receipt={}
        try:
            result=self.measured_descendant(configure,receipt,seconds=None)
        except OSError:
            self.fail('Controlled owned-process exit measurement failed: '+repr(receipt))
        self.assertEqual(result.returncode,0)
        self.assertEqual(receipt['status'],'MEASURED')
        self.assertIn('EXITED_BEFORE_NAME_READ',receipt['activeProcessNamesAtMeasurement'])
        self.assertIn({'win32Error':31,'processState':'EXITED'},receipt['exitedProcessNameObservations'])
        self.assertTrue(receipt['completeAfterOwnedCleanup'])

    @unittest.skipUnless(os.name=='nt','Windows job accounting')
    def test_live_name_read_failure_retains_stage_and_error_without_approving_measurement(self):
        jobs=[]
        def configure(job,_root):
            jobs.append(job)
            def unavailable(*_args):
                ctypes.set_last_error(5)
                return False
            job.api.QueryFullProcessImageNameW=unavailable
        receipt={}
        with self.assertRaisesRegex(OSError,'accounting_unavailable'):
            self.measured_descendant(configure,receipt)
        self.assertEqual(receipt['measurementFailure'],{'stage':'process_name','errorType':'OSError','win32Error':5})
        self.assertFalse(receipt['completeAfterOwnedCleanup'])
        self.assertTrue(receipt['remainingDescendantsStopped'])
        self.assertIsNone(jobs[0].handle)

    @unittest.skipUnless(os.name=='nt','Windows job accounting')
    def test_failed_process_wait_is_never_an_exit_attestation(self):
        def configure(job,_root):
            wait=job.api.WaitForSingleObject
            def state(process,timeout):
                if timeout==0:
                    ctypes.set_last_error(6)
                    return 0xffffffff
                return wait(process,timeout)
            job.api.WaitForSingleObject=state
            job.api.QueryFullProcessImageNameW=lambda *_args:False
        receipt={}
        with self.assertRaisesRegex(OSError,'accounting_unavailable'):
            self.measured_descendant(configure,receipt)
        self.assertEqual(receipt['measurementFailure']['stage'],'process_state')
        self.assertEqual(receipt['measurementFailure']['win32Error'],6)
        self.assertFalse(receipt['completeAfterOwnedCleanup'])
        self.assertNotIn('exitedProcessNameObservations',receipt)

    @unittest.skipUnless(os.name=='nt','Windows job accounting')
    def test_named_process_membership_is_checked_before_reading_it(self):
        calls=[]
        def configure(job,_root):
            from ctypes import wintypes
            def member(_process,_job,result):
                ctypes.cast(result,ctypes.POINTER(wintypes.BOOL))[0]=False
                return True
            job.api.IsProcessInJob=member
            def name(*_args):calls.append(True);return True
            job.api.QueryFullProcessImageNameW=name
        receipt={}
        with self.assertRaisesRegex(OSError,'accounting_unavailable'):
            self.measured_descendant(configure,receipt)
        self.assertEqual(calls,[])
        self.assertEqual(receipt['measurementFailure']['stage'],'process_membership')
        self.assertFalse(receipt['completeAfterOwnedCleanup'])

    @unittest.skipUnless(os.name=='nt','Windows job accounting')
    def test_process_list_overflow_is_not_silently_truncated(self):
        def configure(job,_root):
            query=job.api.QueryInformationJobObject
            def list_query(handle,kind,data,*args):
                if kind==3:
                    ids=ctypes.cast(data,ctypes.POINTER(ProcessList)).contents
                    ids.assigned=65;ids.listed=64
                    return True
                return query(handle,kind,data,*args)
            job.api.QueryInformationJobObject=list_query
        receipt={}
        with self.assertRaisesRegex(OSError,'accounting_unavailable'):
            self.measured_descendant(configure,receipt)
        self.assertEqual(receipt['measurementFailure']['stage'],'job_process_list')
        self.assertFalse(receipt['completeAfterOwnedCleanup'])

    def test_working_set_counter_layout_uses_fixed_dwords_and_native_size_t(self):
        self.assertEqual(ctypes.sizeof(MemoryCounters),8+8*ctypes.sizeof(ctypes.c_size_t))

    @unittest.skipUnless(os.name == 'nt', 'Windows working sets')
    def test_observer_never_falls_back_to_callers_job_after_cleanup(self):
        job = MeasuredJob({})
        original_handle = job.handle
        try:
            observer = WorkingSetObserver(job)
            calls = []
            def unavailable(handle,*_args):
                calls.append(handle)
                return False
            job.api.QueryInformationJobObject = unavailable
            job.handle = None  # Simulate owner close without changing the captured identity.
            with self.assertRaisesRegex(OSError,'process_list_unavailable'):
                observer.sample()
            self.assertEqual(calls,[original_handle])
            self.assertNotIn(None,calls)
        finally:
            job.handle = original_handle
            job.close()

    @unittest.skipUnless(os.name == 'nt', 'Windows working sets')
    def test_stopped_periodic_observer_cannot_query_a_job_again(self):
        job = MeasuredJob({})
        try:
            observer = WorkingSetObserver(job)
            observer.stop_event.set()
            with patch.object(job.api,'QueryInformationJobObject') as query:
                observer.sample()
                query.assert_not_called()
        finally:
            job.close()

    def test_concurrent_context_is_refused_without_changing_ownership(self):
        original = owner._make_job
        with patch('calibration.windows_resource_measurement.threading.active_count', return_value=2):
            with self.assertRaisesRegex(RuntimeError, 'isolated_main_thread'):
                measure_owned(['unused'], receipt={})
        self.assertIs(owner._make_job, original)

    @unittest.skipUnless(os.name == 'nt', 'Windows job accounting')
    def test_actual_cpu_memory_and_exited_descendants_are_counted(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            child = 'import time; data=bytearray(24*1024**2); end=time.process_time()+0.15\nwhile time.process_time()<end: pass'
            source = 'import subprocess,sys; subprocess.run([sys.executable,"-I","-c",' + repr(child) + '],check=True)'
            receipt = {}
            original = owner._make_job
            with (root / 'out.log').open('wb') as output:
                result = measure_owned([sys.executable, '-I', '-c', source], receipt=receipt,
                    env=dict(os.environ), cwd=root, stdout=output, stderr=output, timeout=10)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(receipt['status'], 'MEASURED')
            self.assertGreaterEqual(receipt['totalProcesses'], 3)
            self.assertGreater(receipt['cpuSeconds'], 0.10)
            self.assertGreaterEqual(receipt['peakJobCommittedBytes'], 24 * 1024**2)
            self.assertEqual(receipt['activeProcessesAtMeasurement'], 0)
            self.assertTrue(receipt['completeAfterExit'])
            self.assertFalse(receipt['productionQualified'])
            self.assertIs(owner._make_job, original)

    @unittest.skipUnless(os.name == 'nt', 'Windows working sets')
    def test_actual_working_set_samples_cover_touched_memory_and_owned_exited_children(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            child = 'import time; data=bytearray(24*1024**2); time.sleep(1.0)'
            source = 'import subprocess,sys; subprocess.run([sys.executable,"-I","-c",'+repr(child)+'],check=True)'
            receipt = {}
            with (root/'out.log').open('wb') as output:
                result = measure_owned([sys.executable,'-I','-c',source],receipt=receipt,sample_working_set=True,
                    env=dict(os.environ),cwd=root,stdout=output,stderr=output,timeout=10)
            sample = receipt['workingSetObservation']
            self.assertEqual(result.returncode,0)
            self.assertEqual(receipt['version'],2)
            self.assertEqual(sample['status'],'SAMPLED')
            self.assertEqual(sample['observedProcesses'],receipt['totalProcesses'])
            self.assertGreaterEqual(sample['observedProcesses'],3)
            self.assertGreaterEqual(sample['maximumObservedWorkingSetBytes'],24*1024**2)
            self.assertGreaterEqual(sample['maximumReportedProcessPeakWorkingSetBytes'],24*1024**2)
            self.assertTrue(sample['samplerStopped'])
            self.assertTrue(sample['allAccountedProcessesObserved'])
            self.assertTrue(sample['peakBetweenSamplesMayBeMissed'])
            self.assertTrue(sample['readsAcrossProcessesAreNotAtomic'])
            self.assertFalse(sample['exactSimultaneousPeakEstablished'])
            self.assertTrue(sample['sharedPagesMayBeCountedMoreThanOnce'])
            self.assertFalse(sample['gpuMemoryMeasured'])
            self.assertTrue(receipt['completeAfterOwnedCleanup'])

    @unittest.skipUnless(os.name == 'nt', 'Windows working sets')
    def test_sampler_api_failure_still_closes_job_and_restores_factory(self):
        jobs = []
        class FailedMemory(MeasuredJob):
            def __init__(self,receipt):
                super().__init__(receipt)
                jobs.append(self)
                self.api.K32GetProcessMemoryInfo = lambda *_args:False
        with tempfile.TemporaryDirectory() as temp:
            receipt,original = {},owner._make_job
            with patch('calibration.windows_resource_measurement.MeasuredJob',FailedMemory), \
                 (Path(temp)/'out.log').open('wb') as output:
                with self.assertRaisesRegex(OSError,'working_set_counters_unavailable'):
                    measure_owned([sys.executable,'-I','-c','pass'],receipt=receipt,sample_working_set=True,
                        env=dict(os.environ),cwd=temp,stdout=output,stderr=output,timeout=10)
            self.assertIsNone(jobs[0].handle)
            self.assertIs(owner._make_job,original)
            self.assertEqual(receipt['workingSetObservation']['status'],'FAILED')
            self.assertTrue(receipt['workingSetObservation']['samplerStopped'])
            self.assertEqual(jobs[0].working_set.handles,{})

    @unittest.skipUnless(os.name == 'nt', 'Windows working sets')
    def test_invalid_process_wait_state_is_not_accepted_as_live_memory(self):
        jobs = []
        class FailedWait(MeasuredJob):
            def __init__(self,receipt):
                super().__init__(receipt)
                jobs.append(self)
                self.api.WaitForSingleObject = lambda *_args:0xFFFFFFFF  # WAIT_FAILED.
        with tempfile.TemporaryDirectory() as temp:
            receipt = {}
            with patch('calibration.windows_resource_measurement.MeasuredJob',FailedWait), \
                 (Path(temp)/'out.log').open('wb') as output:
                with self.assertRaisesRegex(OSError,'process_state_unavailable'):
                    measure_owned([sys.executable,'-I','-c','pass'],receipt=receipt,sample_working_set=True,
                        env=dict(os.environ),cwd=temp,stdout=output,stderr=output,timeout=10)
            self.assertIsNone(jobs[0].handle)
            self.assertEqual(receipt['workingSetObservation']['status'],'FAILED')
            self.assertTrue(receipt['workingSetObservation']['samplerStopped'])

    @unittest.skipUnless(os.name == 'nt', 'Windows working sets')
    def test_pid_membership_is_verified_before_reading_any_memory(self):
        jobs = []
        memory_reads = []
        class NonMember(MeasuredJob):
            def __init__(self,receipt):
                super().__init__(receipt)
                jobs.append(self)
                # Pretend an enumerated PID has changed ownership. Do not read it.
                def member(_process,_job,value):
                    ctypes.cast(value,ctypes.POINTER(owner_test_bool))[0]=False
                    return True
                from ctypes import wintypes
                owner_test_bool = wintypes.BOOL
                self.api.IsProcessInJob = member
                def read(*_args):
                    memory_reads.append(True)
                    raise AssertionError('nonmember_memory_must_never_be_read')
                self.api.K32GetProcessMemoryInfo = read
        with tempfile.TemporaryDirectory() as temp:
            receipt = {}
            with patch('calibration.windows_resource_measurement.MeasuredJob',NonMember), \
                 (Path(temp)/'out.log').open('wb') as output:
                with self.assertRaisesRegex(OSError,'process_not_owned'):
                    measure_owned([sys.executable,'-I','-c','pass'],receipt=receipt,sample_working_set=True,
                        env=dict(os.environ),cwd=temp,stdout=output,stderr=output,timeout=10)
            self.assertEqual(memory_reads,[])
            self.assertIsNone(jobs[0].handle)
            self.assertEqual(jobs[0].working_set.peaks,{})
            self.assertEqual(receipt['workingSetObservation']['status'],'FAILED')

    @unittest.skipUnless(os.name == 'nt', 'Windows working sets')
    def test_working_set_sampler_timeout_keeps_partial_receipt_and_stops_thread(self):
        with tempfile.TemporaryDirectory() as temp:
            receipt = {}
            with (Path(temp)/'out.log').open('wb') as output:
                with self.assertRaises(subprocess.TimeoutExpired):
                    measure_owned([sys.executable,'-I','-c','import time; data=bytearray(8*1024**2); time.sleep(20)'],
                        receipt=receipt,sample_working_set=True,env=dict(os.environ),cwd=temp,
                        stdout=output,stderr=output,timeout=.7)
            self.assertTrue(receipt['workingSetObservation']['samplerStopped'])
            self.assertGreaterEqual(receipt['workingSetObservation']['samples'],2)
            self.assertTrue(receipt['completeAfterOwnedCleanup'])
            self.assertFalse(receipt['completeAfterExit'])

    @unittest.skipUnless(os.name == 'nt', 'Windows job accounting')
    def test_actual_nonzero_exit_keeps_measured_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            receipt = {}
            with (Path(temp) / 'out.log').open('wb') as output:
                result = measure_owned([sys.executable, '-I', '-c', 'raise SystemExit(5)'], receipt=receipt,
                    env=dict(os.environ), cwd=temp, stdout=output, stderr=output, timeout=10)
            self.assertEqual((result.returncode, receipt['nativeExitCode']), (5, 5))
            self.assertEqual(receipt['status'], 'MEASURED')
            self.assertTrue(receipt['completeAfterExit'])

    @unittest.skipUnless(os.name == 'nt', 'Windows job accounting')
    def test_actual_timeout_keeps_partial_accounting_and_restores_ownership(self):
        with tempfile.TemporaryDirectory() as temp:
            receipt = {}
            original = owner._make_job
            with (Path(temp) / 'out.log').open('wb') as output:
                with self.assertRaises(subprocess.TimeoutExpired):
                    measure_owned([sys.executable, '-I', '-c', 'import time; time.sleep(20)'], receipt=receipt,
                        env=dict(os.environ), cwd=temp, stdout=output, stderr=output, timeout=0.5)
            self.assertEqual(receipt['status'], 'MEASURED')
            self.assertFalse(receipt['completeAfterExit'])
            self.assertIsNone(receipt['nativeExitCode'])
            self.assertIs(owner._make_job, original)

    @unittest.skipUnless(os.name == 'nt', 'Windows job accounting')
    def test_accounting_api_failure_still_closes_owned_job(self):
        jobs = []
        class FailedMeasurement(MeasuredJob):
            def __init__(self, receipt):
                super().__init__(receipt)
                jobs.append(self)
                self.api.QueryInformationJobObject = lambda *_args: False
        with tempfile.TemporaryDirectory() as temp:
            receipt = {}
            original = owner._make_job
            with patch('calibration.windows_resource_measurement.MeasuredJob', FailedMeasurement), \
                 (Path(temp) / 'out.log').open('wb') as output:
                with self.assertRaisesRegex(OSError, 'accounting_unavailable'):
                    measure_owned([sys.executable, '-I', '-c', 'pass'], receipt=receipt,
                        env=dict(os.environ), cwd=temp, stdout=output, stderr=output, timeout=10)
            self.assertEqual(receipt['status'], 'MEASUREMENT_FAILED')
            self.assertIsNone(jobs[0].handle)
            self.assertIs(owner._make_job, original)

    @unittest.skipUnless(os.name == 'nt', 'Windows job accounting')
    def test_living_owned_descendant_is_identified_and_waited_after_cleanup(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            child = 'from pathlib import Path; import time; Path("started").write_text("yes"); time.sleep(60)'
            source = ('import subprocess,sys,time; from pathlib import Path; '
                      'subprocess.Popen([sys.executable,"-I","-c",' + repr(child) + '],'
                      'stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); '
                      '\nwhile not Path("started").exists(): time.sleep(0.01)')
            receipt = {}
            with (root / 'out.log').open('wb') as output:
                result = measure_owned([sys.executable, '-I', '-c', source], receipt=receipt,
                    env=dict(os.environ), cwd=root, stdout=output, stderr=output, timeout=10)
            self.assertEqual(result.returncode, 0)
            self.assertGreater(receipt['activeProcessesAtMeasurement'], 0)
            self.assertFalse(receipt['completeAfterExit'])
            self.assertTrue(receipt['remainingDescendantsStopped'])
            self.assertTrue(receipt['completeAfterOwnedCleanup'])
            self.assertTrue(any(name.lower().startswith('python') for name in receipt['activeProcessNamesAtMeasurement']))

    @unittest.skipUnless(os.name == 'nt', 'Windows job accounting')
    def test_repeated_close_cannot_erase_unverified_descendant_wait(self):
        jobs = []
        class UnverifiedWait(MeasuredJob):
            def __init__(self, receipt):
                super().__init__(receipt)
                jobs.append(self)
                self.api.WaitForSingleObject = lambda *_args: 258  # Inject WAIT_TIMEOUT.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            child = 'from pathlib import Path; import time; Path("started").write_text("yes"); time.sleep(60)'
            source = ('import subprocess,sys,time; from pathlib import Path; '
                'subprocess.Popen([sys.executable,"-I","-c",' + repr(child) + '],'
                'stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); '
                '\nwhile not Path("started").exists(): time.sleep(0.01)')
            receipt = {}
            with patch('calibration.windows_resource_measurement.MeasuredJob', UnverifiedWait), \
                 (root / 'out.log').open('wb') as output:
                with self.assertRaisesRegex(OSError, 'cleanup_unverified'):
                    measure_owned([sys.executable, '-I', '-c', source], receipt=receipt,
                        env=dict(os.environ), cwd=root, stdout=output, stderr=output, timeout=10)
            self.assertFalse(receipt['remainingDescendantsStopped'])
            self.assertFalse(receipt['completeAfterOwnedCleanup'])
            jobs[0].close()
            self.assertFalse(receipt['completeAfterOwnedCleanup'])


if __name__ == '__main__':
    unittest.main()
