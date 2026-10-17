"""One bounded recovery check: timeout/cancel and actual metadata child recovery."""
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest

from community.local_scene_library_ui import LibrarySession
from community.local_scene_recover import watchdog
from community.tests import test_local_scene_archive as helper


class RecoverTests(unittest.TestCase):
    def test_stall_and_cancel_are_bounded_and_owned_child_recovers_saved_work(self):
        for cancel,expected in ((False,79),(True,0)):
            done=threading.Event();codes=[]
            def terminate(code):codes.append(code);done.set()
            thread=threading.Thread(target=watchdog,args=([time.monotonic()-1],done,lambda:cancel,.1,terminate),
                                    kwargs={'dump':lambda:None})
            thread.start();self.assertTrue(done.wait(2));thread.join(2)
            self.assertEqual(codes,[expected])
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);app=helper.ArchiveTest().make(root,count=2)
            data=app.root.parent
            session=LibrarySession(SimpleNamespace(thread=None,runtime_root=root/'runtime'),data)
            try:
                session._recover()
                self.assertEqual(session.library.status()['locations'],2)
                self.assertFalse(list(session.library.root.glob('recover-*')))
                # An existing library searches without rescanning old folders.
                session._recover=lambda:(_ for _ in ()).throw(AssertionError('unexpected rescan'))
                session.searcher=lambda *_a,**_k:{'locations':2,'map':None}
                session._run({'prompt':'a road'})
                self.assertEqual(session.phase,'complete')
            finally:
                session.close()
