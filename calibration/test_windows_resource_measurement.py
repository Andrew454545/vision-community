import os
import ctypes
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from calibration.windows_resource_measurement import MemoryCounters, MeasuredJob, WorkingSetObserver, measure_owned
from community import process_owner as owner


class MeasurementTest(unittest.TestCase):
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
