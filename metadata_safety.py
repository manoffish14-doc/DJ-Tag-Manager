"""Transactional audio-tag edits with durable recovery copies and a write journal.

No caller may mutate an original audio file through this module. Edits are made
on a same-directory temporary copy and installed only after validation.
"""
from __future__ import annotations
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

_LOCKS = {}
_LOCK_GUARD = threading.Lock()

class FileChangedError(RuntimeError):
    """File was changed externally after it was read."""

class UnsafeWriteError(RuntimeError):
    """A write failed before replacement or verification."""

def fingerprint(path):
    p = Path(path)
    s = p.stat()
    return {'size': s.st_size, 'mtime_ns': s.st_mtime_ns, 'dev': s.st_dev, 'ino': s.st_ino}

def _digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def _lock(path):
    key = str(Path(path).resolve())
    with _LOCK_GUARD:
        return _LOCKS.setdefault(key, threading.RLock())

def _init_db(db):
    with sqlite3.connect(db) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS metadata_writes (
          id TEXT PRIMARY KEY, path TEXT NOT NULL, backup TEXT NOT NULL,
          before_hash TEXT NOT NULL, after_hash TEXT NOT NULL,
          before_fingerprint TEXT NOT NULL, after_fingerprint TEXT NOT NULL,
          changes TEXT NOT NULL, created_utc TEXT NOT NULL, restored_utc TEXT)''')

def history(db_path, limit=100):
    db = Path(db_path)
    if not db.exists():
        return []
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute('SELECT * FROM metadata_writes ORDER BY created_utc DESC LIMIT ?', (limit,))]

def safe_write(path, changes, custom_changes, writer, reader, backup_root,
               expected=None, validator=None):
    """Return journal record after an atomic, verified write.

    expected is a fingerprint captured when the track was last read; mismatch
    blocks edits rather than overwriting another application's modifications.
    The backup is kept outside the music library. If validation or replacement
    fails, the original remains unchanged and the temporary file is removed.
    """
    source = Path(path).resolve(strict=True)
    if not source.is_file() or source.is_symlink():
        raise UnsafeWriteError('Not a regular, non-symlink audio file')
    if not changes and not custom_changes:
        raise ValueError('No metadata changes supplied')
    backup_root = Path(backup_root).expanduser().resolve()
    backup_root.mkdir(parents=True, exist_ok=True)
    db = backup_root / 'metadata_writes.sqlite3'
    _init_db(db)
    with _lock(source):
        original_fp = fingerprint(source)
        if expected is not None and original_fp != expected:
            raise FileChangedError('Audio file changed outside DJ Tag Manager; reload before saving')
        before = reader(str(source))
        before_hash = _digest(source)
        job_id = uuid.uuid4().hex
        backup = backup_root / (job_id + source.suffix.lower())
        tmp = None
        installed = False
        try:
            # A durable backup exists before any attempt to replace the source.
            shutil.copy2(source, backup)
            if _digest(backup) != before_hash:
                raise UnsafeWriteError('Backup verification failed')
            fd, tmp_name = tempfile.mkstemp(prefix='.djtag-', suffix=source.suffix, dir=source.parent)
            os.close(fd)
            tmp = Path(tmp_name)
            shutil.copy2(source, tmp)
            writer(str(tmp), changes, custom_changes or {})
            after = reader(str(tmp))
            if validator:
                validator(before, after, changes)
            else:
                for field, value in changes.items():
                    if field in after and str(after[field] or '') != str(value or ''):
                        raise UnsafeWriteError(f'Written {field} did not match requested value')
            if fingerprint(source) != original_fp or _digest(source) != before_hash:
                raise FileChangedError('Audio file changed during save; original not replaced')
            # Preserve original permissions and timestamp behavior for other metadata.
            shutil.copymode(source, tmp)
            os.replace(tmp, source)
            installed = True
            tmp = None
            final_fp = fingerprint(source)
            record = dict(id=job_id, path=str(source), backup=str(backup),
                          before_hash=before_hash, after_hash=_digest(source),
                          before_fingerprint=json.dumps(original_fp),
                          after_fingerprint=json.dumps(final_fp),
                          changes=json.dumps({'tags': changes, 'custom': custom_changes or {}}, default=str),
                          created_utc=datetime.now(timezone.utc).isoformat())
            with sqlite3.connect(db) as conn:
                conn.execute('''INSERT INTO metadata_writes
                  (id,path,backup,before_hash,after_hash,before_fingerprint,after_fingerprint,changes,created_utc)
                  VALUES (:id,:path,:backup,:before_hash,:after_hash,:before_fingerprint,:after_fingerprint,:changes,:created_utc)''',record)
            return record
        except Exception:
            # If journaling failed after replacement, restore the verified backup.
            if installed:
                shutil.copy2(backup, source)
            raise
        finally:
            if tmp is not None:
                tmp.unlink(missing_ok=True)

def restore_write(db_path, write_id):
    """Restore one write, only when the file still matches its saved after-state."""
    db = Path(db_path)
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute('SELECT * FROM metadata_writes WHERE id=?', (write_id,)).fetchone()
        if row is None:
            raise KeyError('Unknown metadata write')
        r = dict(row)
        if r['restored_utc']:
            raise UnsafeWriteError('Write was already restored')
        source = Path(r['path'])
        backup = Path(r['backup'])
        with _lock(source):
            if not source.is_file() or _digest(source) != r['after_hash']:
                raise FileChangedError('Audio changed since this write; cannot safely restore')
            if not backup.is_file() or _digest(backup) != r['before_hash']:
                raise UnsafeWriteError('Recovery copy missing or corrupt')
            fd, temp_name = tempfile.mkstemp(prefix='.djtag-restore-', suffix=source.suffix, dir=source.parent)
            os.close(fd)
            temp = Path(temp_name)
            try:
                shutil.copy2(backup, temp)
                if _digest(source) != r['after_hash']:
                    raise FileChangedError('Audio changed during restore')
                os.replace(temp, source)
                conn.execute('UPDATE metadata_writes SET restored_utc=? WHERE id=?',
                             (datetime.now(timezone.utc).isoformat(), write_id))
                conn.commit()
            finally:
                temp.unlink(missing_ok=True)
    return str(source)
