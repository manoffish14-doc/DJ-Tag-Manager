"""DJ Tag Manager: local macOS-friendly MP3 metadata editor."""
import json
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

import requests
from mutagen.id3 import ID3, ID3NoHeaderError, TDRC, TCON, TXXX
from mutagen.mp3 import MP3

APP_NAME = 'DJ Tag Manager'
USER_AGENT = 'DJTagManager/0.1 (local desktop application)'


def read_track(path):
    audio = MP3(path)
    tags = audio.tags
    def value(key):
        frames = tags.getall(key) if tags else []
        return str(frames[0].text[0]) if frames else ''
    return {'path': str(path), 'title': value('TIT2') or Path(path).stem,
            'artist': value('TPE1'), 'year': value('TDRC') or value('TYER'),
            'genre': value('TCON'), 'duration': audio.info.length}


def lookup_musicbrainz(artist, title):
    if not artist or not title:
        return {'error': 'Artist and title tags are required for lookup.'}
    try:
        r = requests.get('https://musicbrainz.org/ws/2/recording/',
            params={'query': f'artist:"{artist}" AND recording:"{title}"', 'fmt': 'json', 'limit': 8},
            headers={'User-Agent': USER_AGENT}, timeout=15)
        r.raise_for_status()
        candidates = r.json().get('recordings', [])
        if not candidates:
            return {'error': 'No MusicBrainz match found.'}
        best = candidates[0]
        dates = []
        for rec in candidates:
            if rec.get('first-release-date'):
                dates.append(rec['first-release-date'][:4])
        year = min(dates) if dates else (best.get('first-release-date') or '')[:4]
        genres = sorted(best.get('genres', []), key=lambda x: x.get('count', 0), reverse=True)
        genre = genres[0]['name'].title() if genres else ''
        return {'year': year, 'genre': genre, 'matched_title': best.get('title', ''),
                'score': best.get('score', 0), 'recording_id': best.get('id', '')}
    except (requests.RequestException, ValueError) as exc:
        return {'error': str(exc)}


def analyze_cues(path):
    """Suggest candidate cue timestamps; does not modify Serato metadata."""
    try:
        import librosa
        import numpy as np
        y, sr = librosa.load(path, sr=11025, mono=True)
        duration = len(y) / sr
        tempo, beats = librosa.beat.beat_track(y=y, sr=sr, trim=False)
        beat_times = librosa.frames_to_time(beats, sr=sr)
        rms = librosa.feature.rms(y=y)[0]
        hop = 512
        onset = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
        boundaries = librosa.onset.onset_detect(onset_envelope=onset, sr=sr, hop_length=hop, backtrack=True)
        times = librosa.frames_to_time(boundaries, sr=sr, hop_length=hop)
        candidates = [('Start', 0.0)]
        if len(beat_times):
            candidates.append(('First Beat', float(beat_times[0])))
        # Energy transitions are heuristic suggestions, not semantic drop/chorus detection.
        if len(rms) > 20:
            smooth = np.convolve(rms, np.ones(24)/24, mode='same')
            delta = smooth[24:] - smooth[:-24]
            order = np.argsort(delta)[::-1]
            picked = []
            for idx in order:
                t = float((idx + 24) * hop / sr)
                if 8 < t < duration - 8 and all(abs(t - x) > 12 for x in picked):
                    picked.append(t)
                if len(picked) == 3:
                    break
            for i, t in enumerate(sorted(picked), 1):
                candidates.append((f'Energy Rise {i}', t))
        if duration > 35:
            candidates.append(('Outro Region', max(0, duration - 24)))
        return {'bpm': round(float(np.asarray(tempo).reshape(-1)[0]), 1),
                'cues': [{'label': name, 'seconds': round(t, 2)} for name, t in candidates]}
    except Exception as exc:
        return {'error': str(exc)}


def write_tags(path, year, genre):
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()
    if year:
        tags.setall('TDRC', [TDRC(encoding=3, text=[year])])
    if genre:
        tags.setall('TCON', [TCON(encoding=3, text=[genre])])
    tags.save(path, v2_version=3)


class App:
    def __init__(self, root):
        self.root = root
        root.title(APP_NAME + ' 0.1')
        root.geometry('1040x650')
        self.rows = {}
        self.events = queue.Queue()
        self.busy = False
        toolbar = ttk.Frame(root, padding=10)
        toolbar.pack(fill='x')
        for label, cmd in [('Add MP3s', self.add_files), ('Add Folder', self.add_folder),
                           ('Lookup Selected', self.lookup), ('Analyze Cues', self.analyze),
                           ('Write Selected Tags', self.write), ('Export Cue Suggestions', self.export)]:
            ttk.Button(toolbar, text=label, command=cmd).pack(side='left', padx=3)
        columns = ('title', 'artist', 'year', 'genre', 'match', 'bpm', 'status')
        self.tree = ttk.Treeview(root, columns=columns, show='headings', selectmode='extended')
        widths = (210, 160, 70, 130, 70, 65, 200)
        for col, width in zip(columns, widths):
            self.tree.heading(col, text=col.title())
            self.tree.column(col, width=width, minwidth=50)
        self.tree.pack(fill='both', expand=True, padx=10, pady=5)
        self.tree.bind('<<TreeviewSelect>>', self.show_details)
        self.details = tk.Text(root, height=9, wrap='word')
        self.details.pack(fill='x', padx=10, pady=5)
        self.status = ttk.Label(root, text='Ready. Add MP3s or a folder.', padding=10)
        self.status.pack(fill='x')
        root.after(100, self.poll)

    def add_files(self):
        self.add_paths(filedialog.askopenfilenames(filetypes=[('MP3 files', '*.mp3')]))

    def add_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.add_paths(sorted(Path(folder).rglob('*.mp3')))

    def add_paths(self, paths):
        errors = 0
        for path in paths:
            path = str(path)
            if path in self.rows:
                continue
            try:
                track = read_track(path)
                track.update(match='', bpm='', status='Imported', cues=[])
                self.rows[path] = track
                self.refresh(path)
            except Exception:
                errors += 1
        self.status.config(text=f'{len(self.rows)} MP3s loaded. {errors} unreadable files skipped.')

    def refresh(self, path):
        r = self.rows[path]
        values = tuple(r.get(c, '') for c in ('title', 'artist', 'year', 'genre', 'match', 'bpm', 'status'))
        if self.tree.exists(path):
            self.tree.item(path, values=values)
        else:
            self.tree.insert('', 'end', iid=path, values=values)

    def selected(self):
        return list(self.tree.selection())

    def run_job(self, kind):
        paths = self.selected()
        if not paths:
            messagebox.showinfo(APP_NAME, 'Select one or more tracks first.')
            return
        if self.busy:
            return
        self.busy = True
        self.status.config(text=f'{kind}: processing {len(paths)} tracks...')
        def work():
            for index, path in enumerate(paths):
                r = self.rows[path]
                if kind == 'lookup':
                    result = lookup_musicbrainz(r['artist'], r['title'])
                    if index < len(paths)-1:
                        time.sleep(1.1)  # MusicBrainz public API rate limit
                else:
                    result = analyze_cues(path)
                self.events.put(('result', kind, path, result))
            self.events.put(('done', kind, len(paths)))
        threading.Thread(target=work, daemon=True).start()

    def lookup(self):
        self.run_job('lookup')

    def analyze(self):
        self.run_job('analyze')

    def poll(self):
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == 'done':
                    self.busy = False
                    self.status.config(text=f'{event[1].title()} finished: {event[2]} tracks.')
                    continue
                _, kind, path, result = event
                r = self.rows.get(path)
                if not r:
                    continue
                if 'error' in result:
                    r['status'] = result['error'][:65]
                elif kind == 'lookup':
                    r['suggested_year'] = result['year']
                    r['suggested_genre'] = result['genre']
                    r['match'] = str(result['score'])
                    r['status'] = 'Lookup ready — review before writing'
                else:
                    r['bpm'] = result['bpm']
                    r['cues'] = result['cues']
                    r['status'] = 'Cue suggestions ready'
                self.refresh(path)
                self.show_details()
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def show_details(self, _event=None):
        selected = self.selected()
        self.details.delete('1.0', 'end')
        if selected:
            r = self.rows[selected[0]]
            self.details.insert('end', json.dumps({k:v for k,v in r.items() if k != 'duration'}, indent=2))

    def write(self):
        paths = self.selected()
        ready = [p for p in paths if 'suggested_year' in self.rows[p] or 'suggested_genre' in self.rows[p]]
        if not ready:
            messagebox.showinfo(APP_NAME, 'Look up selected tracks first. No changes made.')
            return
        if not messagebox.askyesno(APP_NAME, f'Write suggested year/genre to {len(ready)} MP3(s)? Existing year/genre tags may be replaced. Make a backup first.'):
            return
        success = 0
        for path in ready:
            r = self.rows[path]
            try:
                write_tags(path, r.get('suggested_year', ''), r.get('suggested_genre', ''))
                r.update(read_track(path))
                r['status'] = 'Tags written'
                success += 1
            except Exception as exc:
                r['status'] = f'Write failed: {exc}'
            self.refresh(path)
        self.status.config(text=f'Tags written to {success}/{len(ready)} files.')

    def export(self):
        paths = [p for p in self.selected() if self.rows[p].get('cues')]
        if not paths:
            messagebox.showinfo(APP_NAME, 'Analyze selected tracks first.')
            return
        destination = filedialog.asksaveasfilename(defaultextension='.json', filetypes=[('JSON', '*.json')])
        if destination:
            with open(destination, 'w', encoding='utf-8') as f:
                json.dump([{k:self.rows[p][k] for k in ('path','title','artist','bpm','cues')} for p in paths], f, indent=2)
            self.status.config(text=f'Exported {len(paths)} cue suggestion records.')


if __name__ == '__main__':
    root = tk.Tk()
    App(root)
    root.mainloop()
