"""An actual idle guided process must deliver its complete reply before exit."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


class DesktopCloseReplyTests(unittest.TestCase):
    def test_idle_process_delivers_complete_close_reply_and_keeps_saved_work(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            saved = root / 'retained-checkpoint.json'
            saved.write_bytes(b'private unfinished fixture')
            entry = Path(__file__).resolve().parents[1] / 'desktop.py'
            child = subprocess.Popen([sys.executable, '-I', '-B', str(entry),
                '--root', str(root), '--no-browser'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                address = root / 'local-test-url.txt'
                deadline = time.monotonic() + 15
                while not address.exists() and child.poll() is None and time.monotonic() < deadline:
                    time.sleep(.05)
                self.assertTrue(address.exists(), 'owned guided fixture did not start')
                url = urlsplit(address.read_text())
                self.assertEqual(url.hostname, '127.0.0.1')
                base = 'http://127.0.0.1:' + str(url.port)
                headers = {'X-Vision-Token':url.fragment,'Content-Type':'application/json'}
                with urlopen(Request(base+'/api/quit', data=b'{}', headers=headers,
                                     method='POST'), timeout=5) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(json.load(response), {'ok':True})
                self.assertEqual(child.wait(timeout=10), 0)
                self.assertFalse(address.exists())
                self.assertFalse((root / 'instance.json').exists())
                self.assertEqual(saved.read_bytes(), b'private unfinished fixture')
                self.assertFalse((root / 'account.json').exists())
            finally:
                if child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        child.kill(); child.wait(timeout=5)
