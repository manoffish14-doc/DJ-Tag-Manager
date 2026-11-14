"""Safe local library tools for DJ Tag Manager.

No Serato proprietary data is written here. File operations require explicit consent.
"""
import json
import os
import re
import shutil
import sqlite3
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


def canonical(text):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(text or '').casefold()) if c.isalnum())


def duplicate_groups(rows):
    from cleanup_engine import duplicate_clusters
    return duplicate_clusters(rows)


def bitrate_value(row):
    m = re.search(r'\d+', str(row.get('bitrate', '')))
    return int(m.group()) if m else 0


def preferred_copy(group, rows):
    from cleanup_engine import best_copy
    return best_copy(group, rows)


def archive_files(paths, destination, library_rows):
    """Archive selected files; reject collisions and never overwrite existing files.

    Returns a manifest with original and destination paths. All paths validated
    before moving anything. A partial move is rolled back on failure.
    """
    destination = Path(destination).expanduser().resolve()
    if not destination.is_dir():
        raise ValueError('Choose an existing archive folder')
    unique = list(dict.fromkeys(str(Path(p).resolve()) for p in paths))
    moves = []
    for path in unique:
        source = Path(path)
        if path not in library_rows or not source.is_file():
            raise ValueError(f'Unavailable library track: {path}')
        target = destination / source.name
        if target.exists() or any(t == target for _, t in moves):
            raise FileExistsError(f'Archive filename collision: {target.name}')
        if source == target:
            raise ValueError('Source is already in the archive folder')
        moves.append((source, target))
    completed = []
    try:
        for source, target in moves:
            shutil.move(str(source), str(target))
            completed.append((source, target))
        manifest = {'schema': 1, 'created': datetime.now(timezone.utc).isoformat(),
                    'moves': [{'from': str(s), 'to': str(t)} for s, t in completed]}
        manifest_file = destination / ('djtag-archive-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.json')
        manifest_file.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        return manifest, manifest_file
    except Exception:
        for source, target in reversed(completed):
            if target.exists() and not source.exists():
                shutil.move(str(target), str(source))
        raise


def restore_archive(manifest_path):
    manifest = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
    if manifest.get('schema') != 1 or not isinstance(manifest.get('moves'), list):
        raise ValueError('Invalid archive manifest')
    moves = [(Path(m['to']), Path(m['from'])) for m in manifest['moves']]
    for source, target in moves:
        if not source.is_file() or target.exists() or not target.parent.is_dir():
            raise ValueError(f'Cannot safely restore {source} to {target}')
    done = []
    try:
        for source, target in moves:
            shutil.move(str(source), str(target))
            done.append((source, target))
    except Exception:
        for source, target in reversed(done):
            if target.exists() and not source.exists():
                shutil.move(str(target), str(source))
        raise
    return len(done)


def name_suggestions(row):
    title = str(row.get('title') or '')
    artist = str(row.get('artist') or '')
    proposals = {}
    match = re.match(r'^(.{2,90}?)\s+[-–—]\s+(.+)$', title)
    if match and (not artist or canonical(match.group(1)) == canonical(artist)):
        proposals['title'] = (match.group(2).strip(), 88 if artist else 62)
        if not artist:
            proposals['artist'] = (match.group(1).strip(), 62)
    featured = re.search(r'\s*\(?\b(?:feat\.?|featuring|ft\.?)\s+([^()]+)\)?', proposals.get('title', (title,))[0], re.I)
    if featured and artist:
        who = featured.group(1).strip(' )')
        if who and canonical(who) not in canonical(artist):
            proposals['artist'] = (artist + ' ft. ' + who, 78)
            proposals['title'] = (re.sub(r'\s*\(?\b(?:feat\.?|featuring|ft\.?)\s+[^()]+\)?', '', title, flags=re.I).strip(), 78)
    return {field: (value, confidence) for field, (value, confidence) in proposals.items() if value and value != row.get(field, '')}


class LibraryStore:
    """Small SQLite store for app-only cues, decisions, and durable cleanup history."""
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS cues (path TEXT NOT NULL, slot INTEGER NOT NULL,
                    seconds REAL NOT NULL, label TEXT NOT NULL DEFAULT '', color TEXT NOT NULL DEFAULT '#FACC15',
                    PRIMARY KEY(path,slot));
                CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY, created TEXT NOT NULL,
                    action TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS preferences (name TEXT PRIMARY KEY, value TEXT NOT NULL);
            ''')
    def connect(self):
        return sqlite3.connect(self.path, timeout=10)
    def cues(self, path):
        with self.connect() as db:
            return [dict(slot=s, seconds=t, label=l, color=c) for s,t,l,c in db.execute(
                'SELECT slot,seconds,label,color FROM cues WHERE path=? ORDER BY slot', (path,))]
    def save_cue(self, path, slot, seconds, label='', color='#FACC15'):
        if not 1 <= slot <= 8 or seconds < 0:
            raise ValueError('Cue slot must be 1–8 and time must be nonnegative')
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO cues VALUES (?,?,?,?,?)', (path, slot, seconds, label, color))
    def clear_cue(self, path, slot):
        with self.connect() as db:
            db.execute('DELETE FROM cues WHERE path=? AND slot=?', (path, slot))
    def history(self, action, payload):
        with self.connect() as db:
            db.execute('INSERT INTO history(created,action,payload) VALUES (?,?,?)',
                       (datetime.now(timezone.utc).isoformat(), action, json.dumps(payload)))
    def history_rows(self, limit=100):
        with self.connect() as db:
            return list(db.execute('SELECT id,created,action,payload FROM history ORDER BY id DESC LIMIT ?', (limit,)))
