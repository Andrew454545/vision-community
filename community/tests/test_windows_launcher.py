"""Offline checks of the real PowerShell bootstrap verification helpers."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile


REPO = Path(__file__).resolve().parents[2]
LAUNCHER = REPO / "windows" / "Start-Vision.ps1"
POWERSHELL = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"


def ps_string(value):
    return "'" + str(value).replace("'", "''") + "'"


@unittest.skipUnless(sys.platform == "win32", "Windows PowerShell bootstrap")
class WindowsLauncherTest(unittest.TestCase):
    def command(self, code, *, expected=0):
        result = subprocess.run(
            [str(POWERSHELL), "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
             ". " + ps_string(LAUNCHER) + "; " + code],
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result.stdout.strip()

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
            public = ["community/desktop.py", "community/bootstrap.py", "community/vision_index.py",
                      "community/runtime_manifest.json", "community/desktop_web/index.html",
                      "calibration/run_windows.py", "calibration/quality.py", "calibration/gen4-v1/checksums.json"]
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

    def test_running_instance_must_use_loopback_url(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "instance.json").write_text(json.dumps({"pid": os.getpid(), "url": "https://example.com/"}))
            self.assertEqual(self.command("Open-VisionExisting " + ps_string(root)), "False")


if __name__ == "__main__":
    unittest.main()
