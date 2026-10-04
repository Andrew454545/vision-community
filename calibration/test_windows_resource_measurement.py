import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from calibration.windows_resource_measurement import MeasuredJob, measure_owned
from community import process_owner as owner


class MeasurementTest(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
