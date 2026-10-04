"""Offline checks of the real PowerShell bootstrap verification helpers."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zipfile


REPO = Path(__file__).resolve().parents[2]
LAUNCHER = REPO / "windows" / "Start-Vision.ps1"
POWERSHELL = Path(os.environ.get("VISION_TEST_POWERSHELL") or
                  str(Path(os.environ.get("SystemRoot", "C:/Windows")) /
                      "System32/WindowsPowerShell/v1.0/powershell.exe"))
INSTALLER = REPO / "windows/Install-Background.ps1"
SCHEDULER_MOCKS = """
function Get-ScheduledTask { $null }
function New-ScheduledTaskAction { [CmdletBinding()] param($Execute,$Argument)
    $global:CapturedAction = @{execute=$Execute;arguments=$Argument}; return $global:CapturedAction }
function New-ScheduledTaskTrigger { [CmdletBinding()] param([switch]$AtLogOn,$User,[switch]$Once,$At,$RepetitionInterval)
    if ($Once) { $global:RetryInterval = $RepetitionInterval.TotalMinutes }; @{} }
function New-ScheduledTaskSettingsSet { @{} }
function New-ScheduledTaskPrincipal { @{} }
function New-ScheduledTask { @{} }
function Register-ScheduledTask { $global:Registered = $true }
function Start-ScheduledTask { $global:Started = $true }
function Stop-ScheduledTask { throw 'An active task must never be force-stopped' }
function Unregister-ScheduledTask { $global:Removed = $true }
"""


def ps_string(value):
    return "'" + str(value).replace("'", "''") + "'"


@unittest.skipUnless(sys.platform == "win32", "Windows PowerShell bootstrap")
class WindowsLauncherTest(unittest.TestCase):
    def command(self, code, *, expected=0):
        result = subprocess.run(
            [str(POWERSHELL), "-NoProfile", "-Command",
             "$ErrorActionPreference='Stop'; . " + ps_string(LAUNCHER) + "; " + code],
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result.stdout.strip()

    def installer_fixture(self, folder):
        root = Path(folder) / "worker's folder"
        root.mkdir()
        source = Path(folder) / "source"
        (source / "community").mkdir(parents=True)
        (source / "windows").mkdir()
        (source / "windows/Start-Vision.ps1").write_bytes(LAUNCHER.read_bytes())
        for name in ("community/desktop.py", "community/bootstrap.py", "community/vision_index.py", "community/process_owner.py", "community/submission_outbox.py",
                     "community/runtime_manifest.json", "community/desktop_web/index.html",
                     "calibration/run_windows.py", "calibration/quality.py", "calibration/synthetic_canary.py",
                     "calibration/gen4-v1/checksums.json"):
            target = source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((REPO / name).read_bytes())
        (source / "community/__init__.py").write_text("")
        (source / "community/background.py").write_text(
            "def main():\n    raise RuntimeError('private diagnostic contents')\n")
        runtime = Path(folder) / "python"
        runtime.mkdir()
        for name in ("python.exe", "pythonw.exe"):
            (runtime / name).touch()
        command = ("& " + ps_string(INSTALLER) + " -Source " + ps_string(source) +
                   " -Root " + ps_string(root) + " -Python " + ps_string(runtime / "python.exe") +
                   " -AcceptContributions")
        return root, runtime, command

    def test_script_parses_and_python_pin_matches_the_calibration(self):
        self.command("$tokens=$null; $errors=$null; [Management.Automation.Language.Parser]::ParseFile(" +
                     ps_string(LAUNCHER) + ", [ref]$tokens, [ref]$errors) | Out-Null; if ($errors.Count) { throw ($errors | Out-String) }")
        source = LAUNCHER.read_text()
        calibration = (REPO / "calibration/Start-WindowsCalibration.ps1").read_text()
        for expected in ("3.14.7", "d297e5ff019966817ad8502465176139f2d3d840fa4ed84b13bed399a6ab1f15"):
            self.assertIn(expected, source)
            self.assertIn(expected, calibration)
        self.assertNotIn("Set-ExecutionPolicy", source)

    def test_python_reuse_checks_each_extracted_file_and_rejects_extras(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = root / "python.zip"
            extracted = root / "python"
            extracted.mkdir()
            with zipfile.ZipFile(archive, "w") as handle:
                for name, content in (("python.exe", b"trusted runtime"), ("python314._pth", b"python314.zip\n.")):
                    handle.writestr(name, content)
                    (extracted / name).write_bytes(content)
            code = "Test-VisionPythonFiles " + ps_string(archive) + " " + ps_string(extracted)
            self.assertEqual(self.command(code), "True")
            (extracted / "python.exe").write_bytes(b"changed runtime")
            self.assertEqual(self.command(code), "False")
            (extracted / "python.exe").write_bytes(b"trusted runtime")
            (extracted / "unexpected.dll").write_bytes(b"untrusted")
            self.assertEqual(self.command(code), "False")

    def test_corrupt_saved_archive_is_not_extracted_or_executed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "downloads").mkdir()
            (root / "downloads/python-3.14.7-embed-amd64.zip").write_bytes(b"untrusted")
            self.command("Get-VisionPython " + ps_string(root), expected=1)
            self.assertFalse((root / "python").exists())

    def test_snapshot_is_versioned_and_excludes_private_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source"
            private = root / "private"
            source.mkdir()
            private.mkdir()
            public = ["community/desktop.py", "community/bootstrap.py", "community/vision_index.py", "community/process_owner.py", "community/submission_outbox.py",
                      "community/runtime_manifest.json", "community/desktop_web/index.html",
                      "calibration/run_windows.py", "calibration/quality.py", "calibration/synthetic_canary.py", "calibration/gen4-v1/checksums.json"]
            secrets = [".git/config", ".env", "community/.data/account.json", "community/tests/test_private.py",
                       "community/credentials.json", "node_modules/private.txt"]
            for name in public + secrets:
                path = source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("public source" if name in public else "PRIVATE DO NOT COPY")
            code = "Copy-VisionSource " + ps_string(source) + " " + ps_string(private)
            first = Path(self.command(code))
            self.assertEqual(Path(self.command(code)), first)
            copied = {path.relative_to(first).as_posix() for path in first.rglob("*") if path.is_file()}
            self.assertEqual(copied, set(public) | {"source-inventory.json"})
            (source / "community/desktop.py").write_text("changed public source")
            self.assertNotEqual(Path(self.command(code)), first)

    def test_modified_private_snapshot_is_not_silently_reused(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            code = "Copy-VisionSource " + ps_string(REPO) + " " + ps_string(root)
            snapshot = Path(self.command(code))
            (snapshot / "community/desktop.py").write_text("changed source")
            self.command(code, expected=1)

    def test_actual_private_snapshot_can_import_both_guided_and_background_apps(self):
        with tempfile.TemporaryDirectory() as folder:
            snapshot = Path(self.command("Copy-VisionSource " + ps_string(REPO) + " " + ps_string(folder)))
            # -I removes the checkout/caller from Python's import search path;
            # every Community dependency must come from the packaged snapshot.
            code = ("import sys; from pathlib import Path; "
                    "root = Path(" + repr(str(snapshot)) + ").resolve(); sys.path.insert(0, str(root)); "
                    "import community.desktop, community.background, calibration.synthetic_canary; "
                    "generator = Path(calibration.synthetic_canary.__file__).resolve(); "
                    "assert generator.is_relative_to(root), (str(generator), str(root)); "
                    "assert len(calibration.synthetic_canary.image_bytes(0, 0)) == 224 * 224 * 3; "
                    "assert all(Path(module.__file__).resolve().is_relative_to(root) for name, module in sys.modules.items() "
                    "if name == 'community' or name.startswith('community.'))")
            result = subprocess.run([sys.executable, "-I", "-B", "-c", code], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_running_instance_must_use_loopback_url(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "instance.json").write_text(json.dumps({"pid": os.getpid(), "url": "https://example.com/"}))
            self.assertEqual(self.command("Open-VisionExisting " + ps_string(root)), "False")

    def test_background_installer_preserves_startup_failure_without_scheduler_side_effects(self):
        with tempfile.TemporaryDirectory() as folder:
            root, runtime, invocation = self.installer_fixture(folder)
            command = (SCHEDULER_MOCKS + "$messages = @(" + invocation + "); " +
                       "$global:CapturedAction | ConvertTo-Json -Compress")
            action = json.loads(self.command(command))
            self.assertEqual(Path(action["execute"]), runtime / "pythonw.exe")
            self.assertIn('--root "' + str(root) + '"', action["arguments"])
            self.assertIn('--day-pace medium --night-pace max --day-start 08:00 --night-start 22:00 --retry-minutes 30', action["arguments"])
            self.assertNotIn('--no-keep-awake', action["arguments"])
            entry = Path(re.match(r'^-B "([^"]+)"', action["arguments"])[1])
            self.assertTrue(entry.is_relative_to(root / "launchers"))
            result = subprocess.run([sys.executable, "-B", str(entry)],
                                    cwd=folder, capture_output=True, timeout=30)
            self.assertNotEqual(result.returncode, 0)
            report = (root / "startup-failure.json").read_text()
            self.assertEqual(json.loads(report)["error_type"], "RuntimeError")
            self.assertNotIn("private diagnostic contents", report)

    def test_background_schedule_flags_are_registered_and_private_work_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            root, _runtime, invocation = self.installer_fixture(folder)
            preserved = {"account.json": b"private account", "PAUSE": b"pause requested",
                         "indexes/checkpoint.json": b"saved checkpoint", "desktop-failure.json": b"saved failure",
                         "run-background.py": b"old installed launcher"}
            for name, body in preserved.items():
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(body)
            invocation += " -DayPace pause -NightPace slow -DayStart 07:30 -NightStart 19:45 -RetryMinutes 17 -StorageLimitGB 20 -AllowSleep"
            command = (SCHEDULER_MOCKS + "$messages = @(" + invocation + "); " +
                       "@{action=$global:CapturedAction;retry=$global:RetryInterval} | ConvertTo-Json -Compress")
            result = json.loads(self.command(command))
            args = result["action"]["arguments"]
            self.assertIn('--day-pace pause --night-pace slow --day-start 07:30 --night-start 19:45 --retry-minutes 17', args)
            self.assertTrue(args.endswith(' --no-keep-awake'))
            self.assertIn('--storage-limit-gb 20', args)
            self.assertEqual(result["retry"], 15)  # Windows recovery remains independent of service cooldown.
            self.assertEqual(json.loads((root / "background-settings.json").read_text()), {
                "dayPace": "pause", "nightPace": "slow", "dayStart": "07:30", "nightStart": "19:45",
                "retryMinutes": 17, "keepAwake": False, "clock": "Windows local time", "storageLimitGB": 20})
            for name, body in preserved.items():
                self.assertEqual((root / name).read_bytes(), body)

    def test_background_schedule_rejects_invalid_values_before_installation(self):
        with tempfile.TemporaryDirectory() as folder:
            root, _runtime, invocation = self.installer_fixture(folder)
            for flags in (" -DayStart 25:00", " -RetryMinutes 0", " -NightPace fast", " -DayStart 22:00 -NightStart 22:00",
                          " -StorageLimitGB -1", " -StorageLimitGB 4097"):
                with self.subTest(flags=flags):
                    self.command(SCHEDULER_MOCKS + invocation + flags, expected=1)
                    self.assertFalse((root / "apps").exists())
                    self.assertFalse((root / "background-settings.json").exists())

    def test_background_install_and_remove_refuse_to_interrupt_active_batches(self):
        import msvcrt
        with tempfile.TemporaryDirectory() as folder:
            root, _runtime, invocation = self.installer_fixture(folder)
            (root / "background-status.json").write_text(json.dumps({"state": "processing"}))
            (root / "account.json").write_text("private account")
            with (root / "desktop.lock").open("w+b") as guard:
                guard.write(b"0"); guard.flush(); guard.seek(0)
                msvcrt.locking(guard.fileno(), msvcrt.LK_NBLCK, 1)
                for suffix in ("", " -Remove"):
                    self.command(SCHEDULER_MOCKS + invocation + suffix, expected=1)
                    self.assertFalse((root / "STOP-AFTER-BATCH").exists())
                    self.assertFalse((root / "apps").exists())
            self.assertEqual((root / "account.json").read_text(), "private account")

    def test_idle_background_update_waits_for_worker_to_release_its_lock(self):
        import msvcrt
        with tempfile.TemporaryDirectory() as folder:
            root, _runtime, invocation = self.installer_fixture(folder)
            (root / "background-status.json").write_text(json.dumps({"state": "paused"}))
            (root / "PAUSE").touch()
            guard = (root / "desktop.lock").open("w+b")
            guard.write(b"0"); guard.flush(); guard.seek(0)
            msvcrt.locking(guard.fileno(), msvcrt.LK_NBLCK, 1)
            observed = []
            def stopped_worker():
                for _ in range(100):
                    if (root / "STOP-AFTER-BATCH").exists():
                        observed.append(True)
                        guard.close()
                        return
                    time.sleep(0.1)
            observer = threading.Thread(target=stopped_worker)
            observer.start()
            try:
                self.command(SCHEDULER_MOCKS + "$messages = @(" + invocation + ")")
            finally:
                observer.join(timeout=12)
                if not guard.closed:
                    guard.close()
            self.assertEqual(observed, [True])
            self.assertFalse((root / "STOP-AFTER-BATCH").exists())
            self.assertTrue((root / "PAUSE").exists())
            self.assertTrue((root / "background-settings.json").exists())

    def test_background_removal_leaves_private_files_and_old_launcher_intact(self):
        with tempfile.TemporaryDirectory() as folder:
            root, _runtime, invocation = self.installer_fixture(folder)
            preserved = {"account.json": "account", "PAUSE": "pause", "startup-failure.json": "failure",
                         "run-background.py": "old launcher", "indexes/checkpoint.json": "checkpoint"}
            for name, text in preserved.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
            mock_existing = ("function Get-ScheduledTask { [pscustomobject]@{Actions=@([pscustomobject]@{Arguments=" +
                             ps_string('--root "' + str(root) + '"') + "})} }; ")
            command = (SCHEDULER_MOCKS + mock_existing + "$messages = @(" + invocation +
                       " -Remove); $global:Removed | ConvertTo-Json -Compress")
            self.assertTrue(json.loads(self.command(command)))
            for name, text in preserved.items():
                self.assertEqual((root / name).read_text(), text)
            self.assertFalse((root / "apps").exists())

    def test_background_install_rejects_existing_task_with_a_different_root(self):
        with tempfile.TemporaryDirectory() as folder:
            root, _runtime, invocation = self.installer_fixture(folder)
            mock_existing = "function Get-ScheduledTask { [pscustomobject]@{Actions=@([pscustomobject]@{Arguments='--root \"C:\\different\"'})} }; "
            self.command(SCHEDULER_MOCKS + mock_existing + invocation, expected=1)
            self.assertFalse((root / "STOP-AFTER-BATCH").exists())
            self.assertFalse((root / "apps").exists())

    def test_failed_background_registration_or_start_preserves_a_stop_request(self):
        for failing_call in ("Register-ScheduledTask", "Start-ScheduledTask"):
            with self.subTest(failing_call=failing_call), tempfile.TemporaryDirectory() as folder:
                root, _runtime, invocation = self.installer_fixture(folder)
                (root / "account.json").write_text("private account")
                (root / "startup-failure.json").write_text("previous failure evidence")
                (root / "STOP-AFTER-BATCH").touch()
                failure = "function " + failing_call + " { throw 'simulated scheduler failure' }; "
                self.command(SCHEDULER_MOCKS + failure + invocation, expected=1)
                self.assertTrue((root / "STOP-AFTER-BATCH").exists())
                self.assertEqual((root / "account.json").read_text(), "private account")
                self.assertEqual((root / "startup-failure.json").read_text(), "previous failure evidence")
                reports = list(root.glob("background-install-failure-*.json"))
                self.assertEqual(len(reports), 1)
                report = json.loads(reports[0].read_text())
                self.assertEqual(report["status"], "INCOMPLETE")
                self.assertEqual(report["registrationSucceeded"], failing_call == "Start-ScheduledTask")
                self.assertTrue(report["stopRequestPreserved"])


if __name__ == "__main__":
    unittest.main()
