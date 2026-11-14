"""Durable, single-worker, per-track metadata job queue.

Worker callbacks must not touch Tk. Results are delivered through the app event queue.
"""
import json
import sqlite3
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path


def utcnow():
    return datetime.now(timezone.utc).isoformat()


class DurableQueue:
    def __init__(self, database, execute, emit):
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.execute = execute
        self.emit = emit
        self.cv = threading.Condition()
        self.shutdown = False
        self.paused = False
        self.cancelled = set()
        with self.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, files TEXT NOT NULL,
                cursor INTEGER NOT NULL DEFAULT 0, state TEXT NOT NULL DEFAULT 'waiting',
                created TEXT NOT NULL, started TEXT, ended TEXT, errors TEXT NOT NULL DEFAULT '[]',
                successes INTEGER NOT NULL DEFAULT 0, skipped INTEGER NOT NULL DEFAULT 0,
                priority INTEGER NOT NULL DEFAULT 0);
                CREATE INDEX IF NOT EXISTS jobs_state_priority ON jobs(state,priority,id);''')
            db.execute("UPDATE jobs SET state='waiting' WHERE state='running'")
            db.execute('DELETE FROM jobs WHERE ended IS NOT NULL AND ended < ?',
                       ((datetime.now(timezone.utc)-timedelta(days=30)).isoformat(),))
        self.thread = threading.Thread(target=self._worker, daemon=True, name='djtag-queue')
        self.thread.start()

    def connect(self):
        return sqlite3.connect(self.database, timeout=20)

    def add(self, kind, files):
        files = list(dict.fromkeys(str(p) for p in files))
        if not files:
            raise ValueError('No tracks selected')
        with self.connect() as db:
            priority = db.execute('SELECT COALESCE(MAX(priority),0)+1 FROM jobs').fetchone()[0]
            cur = db.execute('INSERT INTO jobs(kind,files,created,priority) VALUES(?,?,?,?)',
                             (kind, json.dumps(files), utcnow(), priority))
            job_id = cur.lastrowid
        with self.cv: self.cv.notify_all()
        return job_id

    def snapshot(self, limit=100):
        with self.connect() as db:
            data = db.execute('SELECT id,kind,files,cursor,state,successes,skipped,errors,created,ended '
                              'FROM jobs ORDER BY CASE WHEN state="running" THEN 0 WHEN state="waiting" THEN 1 ELSE 2 END, priority,id LIMIT ?', (limit,)).fetchall()
        return [dict(id=r[0],kind=r[1],total=len(json.loads(r[2])),cursor=r[3],state=r[4],
                     successes=r[5],skipped=r[6],errors=json.loads(r[7]),created=r[8],ended=r[9]) for r in data]

    def pause(self, paused=True):
        with self.cv:
            self.paused = paused
            self.cv.notify_all()

    def cancel(self, job_id):
        with self.cv:
            self.cancelled.add(job_id)
            with self.connect() as db:
                db.execute("UPDATE jobs SET state='cancelled',ended=? WHERE id=? AND state='waiting'",(utcnow(),job_id))
            self.cv.notify_all()

    def move(self, job_id, delta):
        with self.cv:
            with self.connect() as db:
                rows=db.execute("SELECT id,priority FROM jobs WHERE state='waiting' ORDER BY priority,id").fetchall()
                ids=[r[0] for r in rows]
                if job_id not in ids: return False
                index=ids.index(job_id); other=index+delta
                if other < 0 or other >= len(ids): return False
                ids[index],ids[other]=ids[other],ids[index]
                for pos, ident in enumerate(ids):
                    db.execute('UPDATE jobs SET priority=? WHERE id=?',(pos,ident))
            self.cv.notify_all()
            return True

    def stop(self):
        with self.cv:
            self.shutdown=True
            self.cv.notify_all()

    def _worker(self):
        while True:
            with self.cv:
                if self.shutdown: return
                if self.paused:
                    self.cv.wait(timeout=.4)
                    continue
            with self.connect() as db:
                job=db.execute("SELECT id,kind,files,cursor,successes,skipped,errors FROM jobs WHERE state='waiting' ORDER BY priority,id LIMIT 1").fetchone()
                if job:
                    db.execute("UPDATE jobs SET state='running',started=COALESCE(started,?) WHERE id=?",(utcnow(),job[0]))
            if not job:
                with self.cv: self.cv.wait(timeout=.5)
                continue
            job_id,kind,raw,cursor,successes,skipped,raw_errors=job
            paths=json.loads(raw); errors=json.loads(raw_errors)
            cancelled=False
            for idx in range(cursor,len(paths)):
                with self.cv:
                    while self.paused and not self.shutdown and job_id not in self.cancelled:
                        self.cv.wait(timeout=.4)
                    if self.shutdown or job_id in self.cancelled:
                        cancelled=True
                        break
                path=paths[idx]
                try:
                    if not Path(path).is_file():
                        skipped+=1
                        self.emit(('queue_skip',job_id,path,'Missing file'))
                    else:
                        result=self.execute(kind,path)
                        # Commit cursor only after callback has completed; downstream UI
                        # result processing is idempotent and does not write music files.
                        successes+=1
                        self.emit(('queue_result',job_id,kind,path,result))
                except Exception as exc:
                    errors.append({'path':path,'error':str(exc)[:300]})
                    self.emit(('queue_skip',job_id,path,str(exc)[:120]))
                with self.connect() as db:
                    db.execute('UPDATE jobs SET cursor=?,successes=?,skipped=?,errors=? WHERE id=?',
                               (idx+1,successes,skipped,json.dumps(errors),job_id))
                self.emit(('queue_progress',job_id,idx+1,len(paths)))
            with self.connect() as db:
                db.execute('UPDATE jobs SET state=?,ended=? WHERE id=?',
                           ('waiting' if self.shutdown else ('cancelled' if cancelled else 'completed'),
                            None if self.shutdown else utcnow(),job_id))
            self.emit(('queue_done',job_id,kind,cancelled))
            with self.cv: self.cancelled.discard(job_id)
