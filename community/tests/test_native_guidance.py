"""The guided page names the controls of the download the person actually opened."""
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

from community import desktop
from community import mac_starter as starter

ROOT = Path(__file__).resolve().parents[2]


class NativeGuidanceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()

    def run_mac_starter(self, sealed):
        source = self.root / ('sealed' if sealed else 'folder'); (source / 'community').mkdir(parents=True)
        (source / 'community' / 'mac_starter.py').write_text('')
        if sealed:
            (source / 'release-inventory.json').write_text('{}')
        app = self.root / 'private' / 'app'
        calls = []
        with patch.object(starter, '__file__', str(source / 'community' / 'mac_starter.py')), \
             patch.object(starter.sys, 'platform', 'darwin'), \
             patch.object(starter, 'copy_source', return_value=(app, 'a' * 64)), \
             patch.object(starter.subprocess, 'run', side_effect=lambda args, check: calls.append(args) or type('R', (), {'returncode': 0})()), \
             patch.object(sys, 'argv', ['mac_starter.py', '--root', str(self.root / 'private')]):
            self.assertEqual(starter.main(), 0)
        return calls[0]

    def test_mac_starter_marks_only_the_sealed_native_app(self):
        self.assertIn('--native-app', self.run_mac_starter(True))
        self.assertNotIn('--native-app', self.run_mac_starter(False))

    def test_windows_starter_marks_only_the_sealed_native_app(self):
        script = (ROOT / 'windows' / 'Start-Vision.ps1').read_text(encoding='utf-8')
        self.assertRegex(script, r"Test-Path -LiteralPath \(Join-Path \$source 'release-inventory\.json'\) -PathType Leaf\) \{ \$arguments \+= '--native-app' \}")

    def test_desktop_reports_native_app_without_other_side_effects(self):
        for flag, expected in ((['--native-app'], True), ([], False)):
            root = self.root / ('native' if expected else 'folder'); root.mkdir()
            seen = []
            class Fake:
                def __init__(self, folder):
                    self.root = folder; self.state = {}; seen.append(self)
                def reload_work_plan(self): pass
                def prepare(self): pass
            with patch.object(desktop, 'DesktopApp', Fake), \
                 patch.object(sys, 'argv', ['desktop.py', '--root', str(root), '--prepare-only', *flag]):
                desktop.main()
            self.assertIs(seen[0].state['nativeApp'], expected)

    def test_page_instructions_match_the_actual_launcher_labels(self):
        page = (ROOT / 'community' / 'desktop_web' / 'index.html').read_text(encoding='utf-8')
        script = (ROOT / 'community' / 'desktop_web' / 'app.js').read_text(encoding='utf-8')
        windows = (ROOT / 'packaging' / 'windows' / 'Launcher.cs').read_text(encoding='utf-8')
        mac = (ROOT / 'packaging' / 'macos' / 'Launcher.swift').read_text(encoding='utf-8')
        native = re.findall(r'<span class="native-app" id="(?:windows|mac)-background-native" hidden>(.*?)</span>', page)
        folder = re.findall(r'<span class="folder-download" id="(?:windows|mac)-background-folder">(.*?)</span>', page)
        self.assertEqual((len(native), len(folder)), (2, 2))
        # Each named control exists with exactly that label in the native app.
        for text in native:
            self.assertIn('<strong>Automatic processing</strong>', text)
            self.assertIn('<strong>VISION Community</strong>', text)
        self.assertIn('Text="Automatic processing"', windows)
        self.assertIn('"Automatic processing.lnk"', windows)
        self.assertIn('Text="VISION Community"', windows)
        self.assertIn('NSButton(title:"Automatic processing"', mac)
        self.assertIn('window.title = "VISION Community"', mac)
        self.assertIn('"Start VISION"', windows); self.assertIn('NSButton(title:"Start VISION"', mac)
        # The folder variants name files that ship in the extracted download.
        self.assertIn('Background VISION.cmd', folder[0]); self.assertTrue((ROOT / 'Background VISION.cmd').is_file())
        self.assertIn('Background VISION.command', folder[1]); self.assertTrue((ROOT / 'Background VISION.command').is_file())
        self.assertIn('byId(`${platform}-background-native`).hidden = state.nativeApp !== true', script)
        self.assertIn('byId(`${platform}-background-folder`).hidden = state.nativeApp === true', script)

    def test_public_download_links_use_one_pinned_preview(self):
        sources = [ROOT / name for name in ('README.md', 'START-HERE.md', 'START HERE.html')]
        sources += [ROOT / 'community' / 'web' / name for name in ('index.html', 'getting-started.html')]
        links = set()
        pattern = re.compile(r'https://github\.com/Andrew454545/vision-community/releases/download/[^)" ]+')
        for path in sources:
            links.update(pattern.findall(path.read_text(encoding='utf-8')))
        self.assertEqual(len(links), 1)
        self.assertIn('windows-starter-preview-20261004-recovery', next(iter(links)))

    def test_public_instructions_do_not_request_global_installs_or_security_bypasses(self):
        sources = [ROOT / name for name in ('README.md', 'START-HERE.md', 'START HERE.html')]
        sources += [ROOT / 'community' / 'web' / name for name in ('index.html', 'getting-started.html')]
        text = '\n'.join(path.read_text(encoding='utf-8').lower() for path in sources)
        for forbidden in ('sudo', 'pip install', 'set-executionpolicy', 'executionpolicy bypass',
                          'spctl --master-disable', '--no-verify'):
            self.assertNotIn(forbidden, text)


if __name__ == '__main__':
    unittest.main()
