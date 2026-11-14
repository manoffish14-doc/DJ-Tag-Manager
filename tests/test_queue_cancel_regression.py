import tempfile, time, threading, unittest
from pathlib import Path
from task_queue import DurableQueue

class QueueCancelRegression(unittest.TestCase):
    def test_cancel_running_drops_late_result_and_allows_next_job(self):
        with tempfile.TemporaryDirectory() as td:
            file=Path(td)/'song.mp3';file.write_bytes(b'x')
            started=threading.Event(); release=threading.Event(); events=[]
            def execute(kind,path):
                started.set();release.wait(3);return {'genre':'test'}
            q=DurableQueue(Path(td)/'tasks.sqlite',execute,events.append)
            try:
                ident=q.add('lookup',[str(file)])
                self.assertTrue(started.wait(2))
                q.cancel(ident)
                self.assertEqual(next(j for j in q.snapshot() if j['id']==ident)['state'],'cancelled')
                release.set();q.thread.join(.15)
                deadline=time.monotonic()+2
                while time.monotonic()<deadline and not any(e[0]=='queue_done' for e in events):time.sleep(.01)
                self.assertFalse(any(e[0]=='queue_result' for e in events))
                self.assertEqual(next(j for j in q.snapshot() if j['id']==ident)['state'],'cancelled')
            finally:q.stop();release.set()
