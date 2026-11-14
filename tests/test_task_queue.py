import tempfile
import time
import unittest
from pathlib import Path
from task_queue import DurableQueue


class QueueTests(unittest.TestCase):
    def test_completed_files_are_not_repeated(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            files=[]
            for i in range(3):
                p=root/f'{i}.mp3';p.write_bytes(b'test');files.append(str(p))
            called=[]
            queue=DurableQueue(root/'jobs.db',lambda kind,path: called.append(path) or {'ok':True},lambda event:None)
            queue.add('lookup',files)
            deadline=time.time()+5
            while time.time()<deadline and queue.snapshot()[0]['state']!='completed':time.sleep(.03)
            self.assertEqual(queue.snapshot()[0]['state'],'completed')
            self.assertEqual(called,files)
            queue.stop();queue.thread.join(timeout=2)
            restarted=DurableQueue(root/'jobs.db',lambda kind,path: called.append(path),lambda event:None)
            time.sleep(.1)
            self.assertEqual(called,files)
            restarted.stop();restarted.thread.join(timeout=2)

    def test_reorder_waiting_jobs(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);p=root/'a.mp3';p.write_bytes(b'x')
            q=DurableQueue(root/'jobs.db',lambda kind,path:None,lambda event:None)
            q.pause(True)
            a=q.add('lookup',[p]);b=q.add('analyze',[p])
            self.assertTrue(q.move(b,-1))
            self.assertFalse(q.move(b,-1))
            q.stop();q.thread.join(timeout=2)

if __name__=='__main__':unittest.main()
