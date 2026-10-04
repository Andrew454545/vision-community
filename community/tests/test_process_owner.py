"""Real short-lived process trees, without imagery, service or inference work."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from community import process_owner
from community.vision_index import default_runner, VisionIndexError

REPO = Path(__file__).resolve().parents[2]
CHILD = """
import json, os, subprocess, sys, time
from pathlib import Path
root = Path(sys.argv[1])
if len(sys.argv) > 2:
    for i in range(600):
        (root / 'grandchild-beat').write_text(str(i))
        time.sleep(.03)
else:
    grandchild = subprocess.Popen([sys.executable, '-B', __file__, str(root), 'grandchild'], stdin=subprocess.DEVNULL)
    (root / 'pids.json').write_text(json.dumps([os.getpid(), grandchild.pid]))
    print('native child started', flush=True)
    for i in range(600):
        (root / 'checkpoint.json').write_text(json.dumps({'completed': False, 'nextLocationIndex': i}))
        time.sleep(.03)
"""


def terminated(pid):
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        api.OpenProcess.restype = wintypes.HANDLE
        api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        api.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = api.OpenProcess(0x100000, False, pid)
        if not handle:
            return ctypes.get_last_error() == 87  # No longer an existing PID.
        try:
            return api.WaitForSingleObject(handle, 0) == 0
        finally:
            api.CloseHandle(handle)
    # A reparented Linux zombie cannot execute or update saved work.
    status = Path(f"/proc/{pid}/stat")
    try:
        state = status.read_text()
    except FileNotFoundError:
        # The child can disappear between enumeration and the procfs read.
        # Verify with kill(0) below rather than treating that race as a failure.
        state = ""
    if state.rpartition(")")[2].strip().startswith("Z"):
        return True
    try:
        os.kill(pid, 0)
        return False
    except ProcessLookupError:
        return True


class ProcessOwnerTest(unittest.TestCase):
    def wait_for(self, predicate, timeout=10):
        deadline = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() > deadline:
                self.fail("Bounded process fixture did not reach the expected state")
            time.sleep(.03)

    def fixture(self, root):
        script = root / "finite child.py"
        script.write_text(CHILD)
        return [sys.executable, "-B", str(script), str(root)]

    def assert_tree_stopped(self, root):
        pids = json.loads((root / "pids.json").read_text())
        self.wait_for(lambda: all(terminated(pid) for pid in pids), timeout=5)
        checkpoint = (root / "checkpoint.json").read_bytes()
        heartbeat = (root / "grandchild-beat").read_bytes()
        time.sleep(.15)
        self.assertEqual((root / "checkpoint.json").read_bytes(), checkpoint)
        self.assertEqual((root / "grandchild-beat").read_bytes(), heartbeat)
        self.assertTrue(all(terminated(pid) for pid in pids))

    def test_exact_arguments_environment_workdir_logs_and_exit_status(self):
        with tempfile.TemporaryDirectory() as folder:
            # macOS /var aliases /private/var; getcwd reports the physical path.
            root = Path(folder).resolve()
            environment = os.environ.copy()
            environment["VISION_ORT_THREADS"] = "1"
            argument = "a folder; $(never execute) ' literal"
            code, stdout, stderr = default_runner(
                [sys.executable, "-c", "import json,os,sys; print(json.dumps([sys.argv[1],os.environ['VISION_ORT_THREADS'],os.getcwd()])); print('diagnostic',file=sys.stderr); sys.exit(7)", argument],
                environment, root)
            self.assertEqual(code, 7)
            self.assertEqual(json.loads(stdout), [argument, "1", str(root)])
            self.assertEqual(stderr.strip(), "diagnostic")
            self.assertEqual(json.loads(next(root.glob("*.exit.json")).read_text())["exitCode"], 7)

    def test_native_code_does_not_run_without_startup_gate(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            command = [sys.executable, "-I", "-B", process_owner.__file__, "0", "--", sys.executable,
                       "-c", "from pathlib import Path; Path('native-started').touch()"]
            completed = subprocess.run(command, input=b"", cwd=root, capture_output=True, timeout=10)
            self.assertEqual(completed.returncode, 77)
            self.assertFalse((root / "native-started").exists())

    def test_assignment_failure_stops_before_native_start_and_preserves_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            job = Mock()
            job.assign.side_effect = OSError("ownership could not be established")
            with patch("community.process_owner._make_job", return_value=job):
                with self.assertRaisesRegex(VisionIndexError, "vision_binary_launch_failed"):
                    default_runner([sys.executable, "-c", "from pathlib import Path; Path('native-started').touch()"], os.environ.copy(), root)
            self.assertFalse((root / "native-started").exists())
            self.assertEqual(json.loads(next(root.glob("*.exit.json")).read_text())["status"], "LAUNCH_FAILED")
            job.close.assert_called()

    def test_missing_binary_is_terminal_launch_failure_with_logs(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with self.assertRaisesRegex(VisionIndexError, "vision_binary_launch_failed"):
                default_runner([str(root / "missing-native")], os.environ.copy(), root)
            self.assertEqual(json.loads(next(root.glob("*.exit.json")).read_text())["status"], "LAUNCH_FAILED")
            self.assertIn("native_process_launch_failed", next(root.glob("*.stderr.log")).read_text())

    def test_unsaved_ownership_receipt_never_starts_native_work(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with (root / "stdout.log").open("wb") as stdout, (root / "stderr.log").open("wb") as stderr:
                with self.assertRaises(PermissionError):
                    process_owner.run_owned(
                        [sys.executable, "-c", "from pathlib import Path; Path('native-started').touch()"],
                        env=os.environ.copy(), cwd=root, stdout=stdout, stderr=stderr, timeout=5,
                        on_owned=Mock(side_effect=PermissionError("Cannot retain the ownership receipt")))
            self.assertFalse((root / "native-started").exists())

    @unittest.skipUnless(os.name == "nt", "Windows GUI interpreter")
    def test_gui_wrapper_requires_its_private_console_companion(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(process_owner, "sys", SimpleNamespace(executable=str(root / "pythonw.exe"))):
                with self.assertRaisesRegex(OSError, "native_process_console_runtime_missing"):
                    process_owner._wrapper_python()
                (root / "python.exe").write_bytes(b"selection-only fixture, never executed")
                self.assertEqual(process_owner._wrapper_python(), str(root / "python.exe"))

    @unittest.skipUnless(os.name == "nt", "Windows GUI interpreter")
    def test_real_windowless_parent_can_run_owned_native_work(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            pythonw = Path(sys.executable).with_name("pythonw.exe")
            self.assertTrue(pythonw.is_file())
            driver = root / "windowless-parent.py"
            driver.write_text(
                "import os,sys\nfrom pathlib import Path\nsys.path.insert(0," + repr(str(REPO)) + ")\n"
                "from community.vision_index import default_runner\nroot=Path(sys.argv[1])\n"
                "code,stdout,stderr=default_runner([str(Path(sys.executable).with_name('python.exe')),'-c',\"print('background-native-ready')\"],os.environ.copy(),root)\n"
                "assert code == 0 and stdout.strip() == 'background-native-ready'\n(root/'windowless-passed').touch()\n")
            with (root / "driver.stderr").open("wb") as errors:
                completed = subprocess.run([str(pythonw), "-B", str(driver), str(root)],
                    stdout=subprocess.DEVNULL, stderr=errors, timeout=15)
            self.assertEqual(completed.returncode, 0, (root / "driver.stderr").read_text())
            self.assertTrue((root / "windowless-passed").exists())

    def test_timeout_stops_native_and_grandchild_without_losing_checkpoint(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch("community.vision_index.INDEX_TIMEOUT_SECONDS", 2):
                with self.assertRaisesRegex(VisionIndexError, "vision_binary_timeout"):
                    default_runner(self.fixture(root), os.environ.copy(), root)
            self.assert_tree_stopped(root)
            self.assertEqual(json.loads(next(root.glob("*.exit.json")).read_text())["status"], "TIMEOUT")

    def test_abrupt_parent_exit_stops_tree_releases_lock_and_retains_work(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            child = self.fixture(root)
            driver = root / "parent.py"
            driver.write_text(
                "import os,sys\nfrom pathlib import Path\nsys.path.insert(0," + repr(str(REPO)) + ")\n"
                "from community.background import single_instance\nfrom community.vision_index import default_runner\n"
                "root=Path(sys.argv[1])\nwith single_instance(root):\n    default_runner(" + repr(child) + ",os.environ.copy(),root)\n")
            with (root / "parent.stderr").open("wb") as errors:
                parent = subprocess.Popen([sys.executable, "-B", str(driver), str(root)], stdout=subprocess.DEVNULL, stderr=errors)
                try:
                    self.wait_for(lambda: (root / "pids.json").exists() and (root / "grandchild-beat").exists())
                    parent.kill()  # Abrupt exit, not a cooperative stop/finally.
                    parent.wait(timeout=10)
                    self.assert_tree_stopped(root)
                    saved = (root / "checkpoint.json").read_bytes()
                    unfinished = next(root.glob("*.exit.json"))
                    self.assertEqual(json.loads(unfinished.read_text())["status"], "STARTED")
                    from community.background import single_instance
                    with single_instance(root):
                        code, stdout, _ = default_runner([sys.executable, "-c", "print('restarted safely')"], os.environ.copy(), root)
                    self.assertEqual((code, stdout.strip()), (0, "restarted safely"))
                    self.assertEqual((root / "checkpoint.json").read_bytes(), saved)
                    self.assertEqual(json.loads(unfinished.read_text())["status"], "STARTED")
                finally:
                    if parent.poll() is None:
                        parent.kill()
                    parent.wait(timeout=10)


if __name__ == "__main__":
    unittest.main()
