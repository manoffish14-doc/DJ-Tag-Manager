"""DJ Tag Manager: local macOS-friendly MP3 metadata editor."""
import json
import subprocess
import re
import shutil
from datetime import datetime
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

import requests
from mutagen.id3 import ID3, ID3NoHeaderError, TDRC, TCON, TIT2, TPE1, TCOM, TXXX, COMM, Frames
from metadata_sources import lookup as multi_lookup
from mutagen.mp3 import MP3

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except ImportError:
    DND_FILES = None
    TkinterDnD = None

# DJ Tag Manager visual system: charcoal surfaces, warm yellow highlights.
COLORS = {
    'bg': '#0B0E13', 'panel': '#141922', 'raised': '#1C2330',
    'hover': '#293241', 'line': '#303947', 'text': '#F3F5F8',
    'muted': '#A6B0BF', 'accent': '#FFD23F', 'accent_hover': '#FFE17B',
    'select': '#4C411C', 'input': '#10151D',
}


def apply_dark_theme(root):
    """Use the built-in ttk clam engine; no extra packages or Mac setup."""
    style = ttk.Style(root)
    style.theme_use('clam')
    root.configure(background=COLORS['bg'])
    style.configure('.', background=COLORS['bg'], foreground=COLORS['text'],
                    font=('Helvetica', 13))
    style.configure('TFrame', background=COLORS['bg'])
    style.configure('Panel.TFrame', background=COLORS['panel'])
    style.configure('TLabel', background=COLORS['bg'], foreground=COLORS['text'])
    style.configure('Muted.TLabel', background=COLORS['bg'], foreground=COLORS['muted'])
    style.configure('Brand.TLabel', background=COLORS['bg'], foreground=COLORS['accent'],
                    font=('Helvetica', 21, 'bold'))
    style.configure('TButton', background=COLORS['raised'], foreground=COLORS['text'],
                    borderwidth=0, padding=(13, 9), relief='flat',
                    font=('Helvetica', 12, 'bold'))
    style.map('TButton', background=[('pressed', COLORS['hover']),
                                     ('active', COLORS['hover'])],
              foreground=[('disabled', COLORS['muted'])])
    style.configure('Accent.TButton', background=COLORS['accent'],
                    foreground=COLORS['bg'], padding=(15, 9))
    style.map('Accent.TButton', background=[('active', COLORS['accent_hover']),
                                            ('pressed', COLORS['accent_hover'])],
              foreground=[('active', COLORS['bg'])])
    style.configure('TEntry', fieldbackground=COLORS['input'],
                    foreground=COLORS['text'], insertcolor=COLORS['accent'],
                    bordercolor=COLORS['line'], lightcolor=COLORS['line'],
                    darkcolor=COLORS['line'], padding=7)
    style.map('TEntry', bordercolor=[('focus', COLORS['accent'])],
              lightcolor=[('focus', COLORS['accent'])])
    style.configure('Treeview', background=COLORS['panel'],
                    fieldbackground=COLORS['panel'], foreground=COLORS['text'],
                    rowheight=39, borderwidth=0, relief='flat',
                    font=('Helvetica', 13))
    style.map('Treeview', background=[('selected', COLORS['select'])],
              foreground=[('selected', COLORS['accent'])])
    style.configure('Treeview.Heading', background=COLORS['raised'],
                    foreground=COLORS['muted'], padding=(12, 11),
                    borderwidth=0, relief='flat', font=('Helvetica', 12, 'bold'))
    style.map('Treeview.Heading', background=[('active', COLORS['hover'])],
              foreground=[('active', COLORS['accent'])])
    style.configure('TScrollbar', background=COLORS['raised'],
                    troughcolor=COLORS['bg'], borderwidth=0, arrowcolor=COLORS['muted'])
    style.configure('TCheckbutton', background=COLORS['bg'], foreground=COLORS['text'])
    style.map('TCheckbutton', background=[('active', COLORS['bg'])],
              foreground=[('active', COLORS['accent'])])
    style.configure('TSeparator', background=COLORS['line'])
    return style


def style_popup(window):
    window.configure(bg=COLORS['bg'])


def style_plain_widget(widget):
    if isinstance(widget, tk.Text):
        widget.configure(bg=COLORS['panel'], fg=COLORS['text'],
                         insertbackground=COLORS['accent'],
                         selectbackground=COLORS['select'],
                         relief='flat', highlightthickness=1,
                         highlightbackground=COLORS['line'], padx=12, pady=10,
                         font=('Menlo', 12))
    elif isinstance(widget, tk.Listbox):
        widget.configure(bg=COLORS['panel'], fg=COLORS['text'],
                         selectbackground=COLORS['select'],
                         selectforeground=COLORS['accent'],
                         highlightthickness=0, relief='flat',
                         font=('Helvetica', 13))
    elif isinstance(widget, tk.Canvas):
        widget.configure(bg=COLORS['bg'])

APP_NAME = 'DJ Tag Manager'
MIN_ANALYZED_BPM = 50.0
MAX_ANALYZED_BPM = 160.0

def normalize_analyzed_bpm(tempo, minimum=MIN_ANALYZED_BPM, maximum=MAX_ANALYZED_BPM):
    """Keep tempo within bounds by octave shifts (half/double time)."""
    import math
    value = float(tempo)
    if not math.isfinite(value) or value <= 0:
        raise ValueError('No valid BPM detected')
    while value < minimum:
        value *= 2
    while value > maximum:
        value /= 2
    if not minimum <= value <= maximum:
        raise ValueError('Detected BPM cannot be represented in the configured range')
    # Round halves up (rather than Python's ties-to-even round).
    # Values are positive after validation.
    return math.floor(value + 0.5)

USER_AGENT = 'DJTagManager/0.1 (local desktop application)'



# The column chooser controls presentation only. No ID3 data is discarded.
COLUMN_LABELS = {
    'title': 'Title', 'artist': 'Artist', 'album': 'Album', 'album_artist': 'Album Artist',
    'year': 'Year', 'genre': 'Genre', 'composer': 'Composer / Subgenre',
    'track_number': 'Track #', 'disc_number': 'Disc #', 'bpm_tag': 'Tagged BPM',
    'key': 'Musical Key', 'comment': 'Comment', 'publisher': 'Publisher',
    'isrc': 'ISRC', 'copyright': 'Copyright', 'encoded_by': 'Encoded By',
    'duration_display': 'Duration', 'bitrate': 'Bitrate', 'sample_rate': 'Sample Rate',
    'filename': 'Filename', 'folder': 'Folder', 'path': 'File Path', 'match': 'Match',
    'bpm': 'Analyzed BPM', 'status': 'Status',
    'sources_display': 'Lookup Sources',
}
DEFAULT_COLUMNS = ('title', 'artist', 'year', 'genre', 'composer', 'match', 'bpm', 'status')
ID3_TEXT_FIELDS = {
    'album': 'TALB', 'album_artist': 'TPE2', 'track_number': 'TRCK',
    'disc_number': 'TPOS', 'bpm_tag': 'TBPM', 'key': 'TKEY',
    'publisher': 'TPUB', 'isrc': 'TSRC', 'copyright': 'TCOP', 'encoded_by': 'TENC',
    'title': 'TIT2', 'artist': 'TPE1', 'year': 'TDRC', 'genre': 'TCON', 'composer': 'TCOM',
}


def inspect_metadata(path):
    """Return every ID3 frame in a human-readable, non-destructive view."""
    tags = ID3(path)
    entries = []
    for frame in tags.values():
        frame_id = getattr(frame, 'FrameID', type(frame).__name__)
        frame_key = getattr(frame, 'HashKey', frame_id)
        if hasattr(frame, 'text'):
            value = ' / '.join(str(v) for v in frame.text)
        elif frame_id in ('APIC', 'GEOB', 'PRIV'):
            payload = getattr(frame, 'data', b'')
            value = f'[Binary data: {len(payload):,} bytes]'
            desc = getattr(frame, 'desc', '')
            if desc:
                value += f' Description: {desc}'
            owner = getattr(frame, 'owner', '')
            if owner:
                value += f' Owner: {owner}'
        elif frame_id == 'COMM':
            value = ' / '.join(str(v) for v in frame.text)
        elif frame_id == 'USLT':
            value = str(getattr(frame, 'text', ''))
        else:
            value = str(frame)
            if len(value) > 800:
                value = value[:800] + '… [truncated in viewer]'
        entries.append((str(frame_key), str(value)))
    return sorted(entries, key=lambda item: item[0])


def display_value(row, column):
    if column in row.get('pending_tags', {}):
        return row['pending_tags'][column]
    # Display lookup proposals in the original columns without writing to disk.
    if column in ('year', 'genre', 'composer'):
        suggested = row.get({'composer': 'suggested_subgenre'}.get(column, 'suggested_' + column), '')
        if suggested:
            return suggested
    if column in ('title', 'artist'):
        return row.get('suggested_' + column, row.get(column, ''))
    if column == 'sources_display':
        return ', '.join(row.get('sources', []))
    if column == 'filename':
        return Path(row['path']).name
    if column == 'folder':
        return str(Path(row['path']).parent)
    return row.get(column, '')

def read_track(path):
    audio = MP3(path)
    tags = audio.tags
    def value(key):
        frames = tags.getall(key) if tags else []
        return str(frames[0].text[0]) if frames else ''
    comment_frames = tags.getall('COMM') if tags else []
    comment = ' / '.join(str(v) for v in comment_frames[0].text) if comment_frames else ''
    duration = audio.info.length
    extras = {name: value(frame_id) for name, frame_id in ID3_TEXT_FIELDS.items()}
    extras.update(comment=comment, filename=Path(path).name,
                  duration_display=f'{int(duration // 60)}:{int(duration % 60):02d}',
                  bitrate=f'{round(audio.info.bitrate / 1000)} kbps',
                  sample_rate=f'{audio.info.sample_rate} Hz')
    return dict(extras, **{'path': str(path), 'title': value('TIT2') or Path(path).stem,
            'artist': value('TPE1'), 'year': value('TDRC') or value('TYER'),
            'genre': value('TCON'), 'composer': value('TCOM'), 'duration': duration})


def split_artist_title(raw):
    """Extract likely artist and title from noisy YouTube ID3 title text.

    Suggestions only: never modifies files or removes the original title.
    """
    text = re.sub(r"\s+", " ", raw or "").strip()
    # Remove common YouTube decorations wherever they occur, including
    # '(Official HD Video)' before a featured-artist suffix.
    text = re.sub(
        r"\s*[\[(][^\])]*(?:official|music video|lyric video|lyrics?|visuali[sz]er|audio|4k video|hd video)[^\])]*[\])]",
        " ", text, flags=re.I)
    text = re.sub(r"\s*\|\s*(?:official|lyrics?|audio|music video|hd|4k)\b.*$", "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip(' -–—|')
    for separator in (' - ', ' – ', ' — ', ' | '):
        if separator not in text:
            continue
        artist, title = (part.strip() for part in text.split(separator, 1))
        if not artist or not title or len(artist) > 100:
            continue
        # Preserve featured artist in its own suggestion while searching
        # the base song title. Remove trailing YouTube download counters.
        title = re.sub(r"\s+(?:ft\.?|feat\.?|featuring)\s+.+$", "", title, flags=re.I)
        title = re.sub(r"\s+\d{1,2}$", "", title)
        title = re.sub(r"\s+", " ", title).strip(' -–—|')
        if title:
            return artist, title
    return None


def suggest_from_track(track):
    """Use the ID3 title first, falling back to the filename when needed."""
    candidates = [track.get('title', ''), Path(track['path']).stem]
    for candidate in candidates:
        split = split_artist_title(candidate)
        if split:
            return split
    return None


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
        return {'bpm': normalize_analyzed_bpm(np.asarray(tempo).reshape(-1)[0]),
                'cues': [{'label': name, 'seconds': round(t, 2)} for name, t in candidates]}
    except Exception as exc:
        return {'error': str(exc)}


def write_tags(path, year, genre, artist=None, title=None, subgenre=None):
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()
    if year:
        tags.setall('TDRC', [TDRC(encoding=3, text=[year])])
    if genre:
        tags.setall('TCON', [TCON(encoding=3, text=[genre])])
    if subgenre:
        tags.setall('TCOM', [TCOM(encoding=3, text=[subgenre])])
    if artist is not None:
        tags.setall('TPE1', [TPE1(encoding=3, text=[artist])])
    if title is not None:
        tags.setall('TIT2', [TIT2(encoding=3, text=[title])])
    tags.save(path, v2_version=3)



# Only text frames are editable. Never overwrite artwork, Serato GEOB/PRIV,
# or other binary/proprietary frames via the generic metadata editor.
EDITABLE_FIELDS = {k: v for k, v in ID3_TEXT_FIELDS.items()}
EDITABLE_FIELDS['comment'] = 'COMM'

def stage_frame(tags, field, value):
    frame_id = EDITABLE_FIELDS.get(field)
    if frame_id is None:
        raise ValueError('This field is not a supported editable text tag')
    if frame_id == 'COMM':
        tags.delall('COMM')
        if value:
            tags.add(COMM(encoding=3, lang='eng', desc='', text=[value]))
    else:
        frame_type = Frames[frame_id]
        tags.delall(frame_id)
        if value:
            tags.add(frame_type(encoding=3, text=[value]))

def apply_tag_changes(path, changes, custom_changes):
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()
    for field, value in changes.items():
        stage_frame(tags, field, value)
    for description, value in custom_changes.items():
        if not description.strip():
            continue
        tags.delall('TXXX:' + description)
        if value:
            tags.add(TXXX(encoding=3, desc=description, text=[value]))
    tags.save(path, v2_version=3)

class App:
    def __init__(self, root):
        self.root = root
        root.title(APP_NAME + ' 1.7')
        root.geometry('1300x780')
        root.minsize(1050, 650)
        apply_dark_theme(root)
        self.rows = {}
        self.events = queue.Queue()
        self.busy = False
        self.config_path = Path.home() / 'Library' / 'Application Support' / 'DJ Tag Manager' / 'api_keys.json'
        self.config = self.load_config()
        self.auto_lookup = tk.BooleanVar(value=True)
        self.auto_bpm = tk.BooleanVar(value=True)
        self.save_names = tk.BooleanVar(value=False)
        self.layout_path = self.config_path.with_name('column_layout.json')
        self.visible_columns = self.load_column_layout()
        header = ttk.Frame(root, padding=(20, 17, 20, 8))
        header.pack(fill='x')
        ttk.Label(header, text='DJ  /  TAG MANAGER', style='Brand.TLabel').pack(side='left')
        ttk.Label(header, text='  MUSIC LIBRARY  •  METADATA WORKSPACE',
                  style='Muted.TLabel').pack(side='left', padx=(12, 0))
        toolbar = ttk.Frame(root, padding=(16, 8, 16, 12))
        toolbar.pack(fill='x')
        for label, cmd in [('Add MP3s', self.add_files), ('Add Folder', self.add_folder),
                           ('Lookup Selected', self.lookup), ('Analyze Cues', self.analyze),
                           ('Write Selected Tags', self.write), ('Export Cue Suggestions', self.export)]:
            ttk.Button(toolbar, text=label, command=cmd,
                       style='Accent.TButton' if label == 'Write Selected Tags' else 'TButton').pack(side='left', padx=3)
        ttk.Button(toolbar, text='Suggest Artist / Title', command=self.suggest_split).pack(side='left', padx=3)
        ttk.Button(toolbar, text='All Metadata', command=self.all_metadata).pack(side='left', padx=3)
        ttk.Button(toolbar, text='Edit All Tags', command=self.edit_all_tags).pack(side='left', padx=3)
        ttk.Button(toolbar, text='Show in Finder', command=self.reveal_selected).pack(side='left', padx=3)
        # Keep configuration out of the main toolbar. Each menu item opens its
        # existing dialog or toggles a preference without modifying MP3 files.
        self.settings_menu = tk.Menu(root, tearoff=False, bg=COLORS['panel'],
                                     fg=COLORS['text'], activebackground=COLORS['select'],
                                     activeforeground=COLORS['accent'], borderwidth=0)
        self.settings_menu.add_command(label='API Settings…', command=self.settings)
        self.settings_menu.add_command(label='Choose Columns…', command=self.choose_columns)
        self.settings_menu.add_separator()
        self.settings_menu.add_checkbutton(label='Auto lookup on import/drop', variable=self.auto_lookup)
        self.settings_menu.add_checkbutton(label='Auto BPM analysis on import/drop', variable=self.auto_bpm)
        self.settings_menu.add_checkbutton(label='Include artist/title when writing tags', variable=self.save_names)
        self.settings_button = ttk.Button(toolbar, text='⚙ Settings', command=self.open_settings_menu)
        self.settings_button.pack(side='right', padx=(8, 0))
        editor = ttk.Frame(root, padding=(10, 3))
        editor.pack(fill='x')
        ttk.Label(editor, text='Suggested artist:').pack(side='left')
        self.artist_edit = tk.StringVar()
        ttk.Entry(editor, textvariable=self.artist_edit, width=25).pack(side='left', padx=4)
        ttk.Label(editor, text='Suggested title:').pack(side='left')
        self.title_edit = tk.StringVar()
        ttk.Entry(editor, textvariable=self.title_edit, width=37).pack(side='left', padx=4)
        ttk.Button(editor, text='Apply to selected row', command=self.apply_split).pack(side='left', padx=4)
        ttk.Label(editor, text='Double-click any editable tag cell').pack(side='left', padx=4)
        self.drop_label = ttk.Label(root, text='↓   DROP MP3 FILES OR FOLDERS HERE   •   AUTOMATIC LOOKUP ON IMPORT',
                                    anchor='center', padding=17, style='Muted.TLabel')
        self.drop_label.pack(fill='x', padx=10, pady=(3, 3))
        self.dnd_available = False
        if DND_FILES and hasattr(root, 'drop_target_register'):
            try:
                for target in (root, self.drop_label):
                    target.drop_target_register(DND_FILES)
                    target.dnd_bind('<<Drop>>', self.on_drop)
                self.dnd_available = True
            except tk.TclError as exc:
                print(f'Drag-and-drop unavailable: {exc}')
        if not self.dnd_available:
            self.drop_label.config(text='Drag and drop unavailable in this build; use Add MP3s / Add Folder')
        table_frame = ttk.Frame(root)
        table_frame.pack(fill='both', expand=True, padx=16, pady=(8, 6))
        self.tree = ttk.Treeview(table_frame, columns=tuple(COLUMN_LABELS), show='headings', selectmode='extended')
        self.table_vscroll = ttk.Scrollbar(table_frame, orient='vertical', command=self.tree.yview)
        self.table_hscroll = ttk.Scrollbar(table_frame, orient='horizontal', command=self.tree.xview)
        self.tree.configure(yscrollcommand=self.table_vscroll.set, xscrollcommand=self.table_hscroll.set)
        self.table_vscroll.pack(side='right', fill='y')
        self.table_hscroll.pack(side='bottom', fill='x')
        self.configure_columns()
        self.tree.pack(side='left', fill='both', expand=True)
        self.tree.tag_configure('odd', background=COLORS['panel'])
        self.tree.tag_configure('even', background='#19202B')
        self.tree.bind('<<TreeviewSelect>>', self.show_details)
        self.tree.bind('<Double-1>', self.edit_song_cell)
        self.tree.bind('<Button-2>', self.on_header_context_menu)
        self.tree.bind('<Button-3>', self.on_header_context_menu)
        self.tree.bind('<Control-Button-1>', self.on_header_context_menu)
        self.tree.bind('<ButtonPress-1>', self.on_header_press, add='+')
        self.tree.bind('<ButtonRelease-1>', self.on_header_release, add='+')
        self._header_drag = None
        self.inline_editor = None
        if self.dnd_available and hasattr(self.tree, 'drop_target_register'):
            try:
                self.tree.drop_target_register(DND_FILES)
                self.tree.dnd_bind('<<Drop>>', self.on_drop)
            except tk.TclError as exc:
                print(f'Song-list drag-and-drop unavailable: {exc}')
        self.details = tk.Text(root, height=7, wrap='word')
        style_plain_widget(self.details)
        self.details.pack(fill='x', padx=16, pady=(6, 5))
        self.status = ttk.Label(root, text='●  Ready  •  Add MP3s or drop a folder to begin',
                                padding=(20, 12), style='Muted.TLabel')
        self.status.pack(fill='x')
        root.after(100, self.poll)

    def open_settings_menu(self):
        # Anchor the popup to the gear button, rather than the mouse pointer.
        self.root.update_idletasks()
        x = self.settings_button.winfo_rootx()
        y = self.settings_button.winfo_rooty() + self.settings_button.winfo_height()
        try:
            self.settings_menu.tk_popup(x, y)
        finally:
            self.settings_menu.grab_release()

    def configure_columns(self):
        self.tree.configure(displaycolumns=tuple(self.visible_columns))
        for col in COLUMN_LABELS:
            self.tree.heading(col, text=COLUMN_LABELS[col])
            width = 200 if col in ('title', 'path', 'status') else 150 if col in ('artist', 'album', 'composer') else 110
            self.tree.column(col, width=width, minwidth=60, stretch=True)

    def load_column_layout(self):
        """Restore column visibility/order, ignoring fields removed by upgrades."""
        try:
            saved = json.loads(self.layout_path.read_text(encoding='utf-8'))
            fields = saved.get('visible_columns', [])
            valid = list(dict.fromkeys(key for key in fields if key in COLUMN_LABELS))
            return valid or list(DEFAULT_COLUMNS)
        except (OSError, ValueError, TypeError, AttributeError):
            return list(DEFAULT_COLUMNS)

    def save_column_layout(self):
        try:
            self.layout_path.parent.mkdir(parents=True, exist_ok=True)
            self.layout_path.write_text(json.dumps({'visible_columns': self.visible_columns}, indent=2), encoding='utf-8')
        except OSError as exc:
            messagebox.showwarning(APP_NAME, f'Column layout could not be saved: {exc}')

    def choose_columns(self):
        """Choose and reorder visible columns without modifying any MP3 tags."""
        window = tk.Toplevel(self.root)
        style_popup(window)
        window.title('Customize Song List Columns')
        window.geometry('560x610')
        ttk.Label(window, text='Check fields to display. Select a field and use Up / Down to change its position. Hidden tags are never deleted.',
                  wraplength=520).pack(anchor='w', padx=12, pady=10)
        outer = ttk.Frame(window, padding=10)
        outer.pack(fill='both', expand=True)
        ordered = list(self.visible_columns) + [key for key in COLUMN_LABELS if key not in self.visible_columns]
        checked = {key: key in self.visible_columns for key in COLUMN_LABELS}
        listbox = tk.Listbox(outer, selectmode='browse', exportselection=False)
        style_plain_widget(listbox)
        scrollbar = ttk.Scrollbar(outer, orient='vertical', command=listbox.yview)
        listbox.configure(yscrollcommand=scrollbar.set)
        listbox.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='left', fill='y')
        def render(selected=None):
            listbox.delete(0, 'end')
            for key in ordered:
                listbox.insert('end', ('☑  ' if checked[key] else '☐  ') + COLUMN_LABELS[key])
            if selected in ordered:
                index = ordered.index(selected)
                listbox.selection_set(index)
                listbox.see(index)
        def current():
            selection = listbox.curselection()
            return ordered[selection[0]] if selection else None
        def toggle():
            key = current()
            if key:
                checked[key] = not checked[key]
                render(key)
        def move(delta):
            key = current()
            if key is None: return
            index = ordered.index(key)
            new_index = index + delta
            if 0 <= new_index < len(ordered):
                ordered[index], ordered[new_index] = ordered[new_index], ordered[index]
                render(key)
        controls = ttk.Frame(outer, padding=(12, 0))
        controls.pack(side='left', fill='y')
        ttk.Button(controls, text='Show / Hide', command=toggle).pack(fill='x', pady=4)
        ttk.Button(controls, text='Move Up', command=lambda: move(-1)).pack(fill='x', pady=4)
        ttk.Button(controls, text='Move Down', command=lambda: move(1)).pack(fill='x', pady=4)
        ttk.Button(controls, text='Show All', command=lambda: (checked.update({k: True for k in checked}), render(current()))).pack(fill='x', pady=(22,4))
        ttk.Button(controls, text='Hide All', command=lambda: (checked.update({k: False for k in checked}), render(current()))).pack(fill='x', pady=4)
        ttk.Button(controls, text='DJ Defaults', command=lambda: (checked.update({k: k in DEFAULT_COLUMNS for k in checked}), ordered.__setitem__(slice(None), list(DEFAULT_COLUMNS) + [k for k in COLUMN_LABELS if k not in DEFAULT_COLUMNS]), render())).pack(fill='x', pady=(22,4))
        listbox.bind('<Double-1>', lambda event: toggle())
        listbox.bind('<space>', lambda event: (toggle(), 'break')[1])
        render()
        def apply():
            chosen = [key for key in ordered if checked[key]]
            if not chosen:
                messagebox.showwarning(APP_NAME, 'Select at least one visible column.', parent=window)
                return
            self.visible_columns = chosen
            self.configure_columns()
            self.save_column_layout()
            window.destroy()
        footer = ttk.Frame(window, padding=12)
        footer.pack(fill='x')
        ttk.Button(footer, text='Cancel', command=window.destroy).pack(side='right', padx=5)
        ttk.Button(footer, text='Apply & Save Layout', style='Accent.TButton', command=apply).pack(side='right', padx=5)

    def on_header_context_menu(self, event):
        """Show the visibility checklist only when right-clicking a column header."""
        if self.tree.identify_region(event.x, event.y) != 'heading':
            return
        menu = tk.Menu(self.tree, tearoff=False, bg=COLORS['panel'],
                       fg=COLORS['text'], activebackground=COLORS['select'],
                       activeforeground=COLORS['accent'])
        menu.add_command(label='Show / Hide Columns', state='disabled')
        menu.add_separator()
        for key, label in COLUMN_LABELS.items():
            selected = tk.BooleanVar(value=key in self.visible_columns)
            menu.add_checkbutton(
                label=label, variable=selected,
                command=lambda k=key: self.toggle_column(k),
            )
        menu.add_separator()
        menu.add_command(label='More column options…', command=self.choose_columns)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return 'break'

    def toggle_column(self, key):
        if key in self.visible_columns:
            if len(self.visible_columns) == 1:
                messagebox.showinfo(APP_NAME, 'At least one column must remain visible.')
                return
            self.visible_columns.remove(key)
        else:
            self.visible_columns.append(key)
        self.tree.configure(displaycolumns=tuple(self.visible_columns))
        self.save_column_layout()

    def on_header_press(self, event):
        if self.tree.identify_region(event.x, event.y) != 'heading':
            self._header_drag = None
            return
        column = self.tree.identify_column(event.x)
        try:
            index = int(column[1:]) - 1
        except (ValueError, IndexError):
            return
        if 0 <= index < len(self.visible_columns):
            self._header_drag = (index, event.x, event.y)

    def on_header_release(self, event):
        drag = self._header_drag
        self._header_drag = None
        if drag is None or abs(event.x - drag[1]) < 12:
            return
        if self.tree.identify_region(event.x, event.y) != 'heading':
            return
        destination = self.tree.identify_column(event.x)
        try:
            target = int(destination[1:]) - 1
        except (ValueError, IndexError):
            return
        source = drag[0]
        if not (0 <= target < len(self.visible_columns)) or target == source:
            return
        field = self.visible_columns.pop(source)
        self.visible_columns.insert(target, field)
        self.tree.configure(displaycolumns=tuple(self.visible_columns))
        self.save_column_layout()
        return 'break'

    def all_metadata(self):
        """Show all existing ID3 frames, including nonstandard Serato frames, read-only."""
        paths = self.selected()
        if len(paths) != 1:
            messagebox.showinfo(APP_NAME, 'Select exactly one MP3 to inspect all its metadata.')
            return
        path = paths[0]
        window = tk.Toplevel(self.root)
        style_popup(window)
        window.title('All Metadata — ' + Path(path).name)
        window.geometry('850x590')
        ttk.Label(window, text='Full file location: ' + path, wraplength=810).pack(anchor='w', padx=10, pady=5)
        ttk.Label(window, text='Existing MP3 tags. Edit text tags with Edit All Tags; binary artwork and Serato frames are protected.',
                  wraplength=810).pack(anchor='w', padx=10, pady=8)
        table = ttk.Treeview(window, columns=('frame', 'value'), show='headings')
        table.heading('frame', text='ID3 Frame / Identifier')
        table.heading('value', text='Current Value')
        table.column('frame', width=240, stretch=False)
        table.column('value', width=570)
        scroll = ttk.Scrollbar(window, orient='vertical', command=table.yview)
        table.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        table.pack(fill='both', expand=True, padx=10, pady=5)
        try:
            entries = inspect_metadata(path)
            for frame, value in entries:
                table.insert('', 'end', values=(frame, value))
        except (OSError, ValueError) as exc:
            messagebox.showerror(APP_NAME, f'Could not read metadata: {exc}', parent=window)
        def copy_selected():
            items = table.selection()
            if items:
                data = '\n'.join('\t'.join(map(str, table.item(item, 'values'))) for item in items)
                window.clipboard_clear()
                window.clipboard_append(data)
        ttk.Button(window, text='Copy Selected Metadata', command=copy_selected).pack(pady=8)

    def reveal_selected(self):
        paths = self.selected()
        if not paths:
            messagebox.showinfo(APP_NAME, 'Select one or more songs first.')
            return
        for path in paths:
            subprocess.run(['open', '-R', path], check=False)

    def edit_all_tags(self):
        paths = self.selected()
        if len(paths) != 1:
            messagebox.showinfo(APP_NAME, 'Select exactly one song to edit its metadata.')
            return
        path = paths[0]
        row = self.rows[path]
        window = tk.Toplevel(self.root)
        style_popup(window)
        window.title('Edit Metadata — ' + Path(path).name)
        window.geometry('700x680')
        ttk.Label(window, text='File: ' + path, wraplength=660).pack(anchor='w', padx=12, pady=8)
        ttk.Label(window, text='Changes are staged until Write Selected Tags. Empty values clear tags. Binary/Serato frames remain read-only.', wraplength=660).pack(anchor='w', padx=12)
        canvas = tk.Canvas(window, highlightthickness=0)
        style_plain_widget(canvas)
        scrollbar = ttk.Scrollbar(window, orient='vertical', command=canvas.yview)
        body = ttk.Frame(canvas)
        body.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.create_window((0, 0), window=body, anchor='nw')
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side='left', fill='both', expand=True, padx=12, pady=8)
        scrollbar.pack(side='right', fill='y')
        vars_ = {}
        for field in EDITABLE_FIELDS:
            line = ttk.Frame(body)
            line.pack(fill='x', pady=3)
            ttk.Label(line, text=COLUMN_LABELS.get(field, field), width=22).pack(side='left')
            initial = display_value(row, field)
            var = tk.StringVar(value=initial)
            ttk.Entry(line, textvariable=var, width=58).pack(side='left', fill='x', expand=True)
            vars_[field] = var
        ttk.Separator(body).pack(fill='x', pady=12)
        ttk.Label(body, text='Custom text tags (TXXX) — add or edit').pack(anchor='w')
        custom = {}
        try:
            tags = ID3(path)
            for frame in tags.getall('TXXX'):
                custom[frame.desc] = ' / '.join(map(str, frame.text))
        except ID3NoHeaderError:
            pass
        custom.update(row.get('pending_custom', {}))
        custom_rows = []
        def add_custom(name='', value=''):
            line = ttk.Frame(body)
            line.pack(fill='x', pady=3)
            name_var = tk.StringVar(value=name)
            value_var = tk.StringVar(value=value)
            ttk.Entry(line, textvariable=name_var, width=22).pack(side='left', padx=(0, 6))
            ttk.Entry(line, textvariable=value_var, width=48).pack(side='left', fill='x', expand=True)
            custom_rows.append((name_var, value_var))
        for name, value in sorted(custom.items()):
            add_custom(name, value)
        ttk.Button(body, text='+ Add Custom Text Tag', command=add_custom).pack(anchor='w', pady=8)
        def stage():
            pending = row.setdefault('pending_tags', {})
            for field, var in vars_.items():
                original = row.get(field, '')
                value = var.get().strip()
                if value != original:
                    pending[field] = value
                else:
                    pending.pop(field, None)
                if field in ('artist', 'title') and field in pending:
                    row['suggested_' + field] = value
                    self.save_names.set(True)
            updates = {}
            for name_var, value_var in custom_rows:
                name = name_var.get().strip()
                if name:
                    updates[name] = value_var.get().strip()
            row['pending_custom'] = {k: v for k, v in updates.items() if custom.get(k) != v}
            row['status'] = 'Metadata edits staged — click Write Selected Tags'
            self.refresh(path)
            self.show_details()
            window.destroy()
        ttk.Button(body, text='Stage Changes', style='Accent.TButton', command=stage).pack(anchor='w', pady=12)

    def load_config(self):
        try:
            return json.loads(self.config_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {}

    def settings(self):
        window = tk.Toplevel(self.root)
        style_popup(window)
        window.title('Music Database API Settings')
        window.geometry('560x300')
        fields = [('lastfm', 'Last.fm API key'), ('discogs', 'Discogs personal access token'),
                  ('spotify_id', 'Spotify client ID'), ('spotify_secret', 'Spotify client secret')]
        entries = {}
        for i, (key, label) in enumerate(fields):
            ttk.Label(window, text=label).grid(row=i, column=0, padx=10, pady=12, sticky='w')
            var = tk.StringVar(value=self.config.get(key, ''))
            ttk.Entry(window, textvariable=var, width=43, show='*' if key in ('lastfm','discogs','spotify_secret') else '').grid(row=i, column=1, padx=10)
            entries[key] = var
        ttk.Label(window, text='Keys are stored locally in your user Application Support folder. Do not share them.').grid(row=4, column=0, columnspan=2, padx=10, pady=6)
        def save():
            self.config = {key: var.get().strip() for key,var in entries.items()}
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            self.config_path.write_text(json.dumps(self.config), encoding='utf-8')
            self.config_path.chmod(0o600)
            window.destroy()
        ttk.Button(window, text='Save API Settings', style='Accent.TButton', command=save).grid(row=5, column=1, pady=12)

    def add_files(self):
        self.add_paths(filedialog.askopenfilenames(filetypes=[('MP3 files', '*.mp3')]))

    def add_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.add_paths(sorted(Path(folder).rglob('*.mp3')))

    def on_drop(self, event):
        # Tk's splitlist handles filenames containing spaces and braces.
        paths = self.root.tk.splitlist(event.data)
        self.add_paths(paths)

    def suggest_split(self):
        paths = self.selected()
        if not paths:
            messagebox.showinfo(APP_NAME, 'Select tracks to suggest artist/title.')
            return
        count = 0
        for path in paths:
            r = self.rows[path]
            split = suggest_from_track(r)
            if split:
                r['suggested_artist'], r['suggested_title'] = split
                r['status'] = 'Artist/title suggestion ready'
                count += 1
                self.refresh(path)
        self.show_details()
        self.status.config(text=f'Suggested artist/title for {count}/{len(paths)} selected tracks. Review before writing.')

    def apply_split(self):
        paths = self.selected()
        if len(paths) != 1:
            messagebox.showinfo(APP_NAME, 'Select exactly one track to edit its artist/title suggestion.')
            return
        artist, title = self.artist_edit.get().strip(), self.title_edit.get().strip()
        if not artist or not title:
            messagebox.showwarning(APP_NAME, 'Artist and title must both be filled in.')
            return
        r = self.rows[paths[0]]
        r['suggested_artist'], r['suggested_title'] = artist, title
        r['status'] = 'Edited artist/title suggestion ready'
        self.save_names.set(True)
        self.refresh(paths[0])
        self.show_details()

    def edit_song_cell(self, event):
        """Open a readable editor above the tree, never a tiny clipped cell overlay."""
        if self.tree.identify_region(event.x, event.y) != 'cell':
            return
        column = self.tree.identify_column(event.x)
        path = self.tree.identify_row(event.y)
        if not path:
            return
        try:
            index = int(column[1:]) - 1
        except (ValueError, IndexError):
            return
        if not (0 <= index < len(self.visible_columns)):
            return
        field = self.visible_columns[index]
        if field not in EDITABLE_FIELDS:
            return
        if self.inline_editor is not None:
            self.inline_editor.destroy()
            self.inline_editor = None
        row = self.rows[path]
        original = display_value(row, field)
        window = tk.Toplevel(self.root)
        style_popup(window)
        self.inline_editor = window
        window.title('Edit ' + COLUMN_LABELS[field])
        window.geometry('780x170')
        window.minsize(460, 150)
        window.transient(self.root)
        window.resizable(True, False)
        window.columnconfigure(0, weight=1)
        ttk.Label(window, text=f'{COLUMN_LABELS[field]} — {Path(path).name}',
                  wraplength=730).grid(row=0, column=0, sticky='w', padx=16, pady=(12, 6))
        value = tk.StringVar(value=str(original))
        entry = ttk.Entry(window, textvariable=value, font=('Helvetica', 16))
        entry.grid(row=1, column=0, sticky='ew', padx=16, pady=4, ipady=5)
        entry.focus_set()
        entry.select_range(0, tk.END)
        footer = ttk.Frame(window)
        footer.grid(row=2, column=0, sticky='e', padx=16, pady=10)
        finished = [False]

        def finish(save):
            if finished[0]:
                return
            finished[0] = True
            new_text = value.get().strip()
            if self.inline_editor is window:
                self.inline_editor = None
            window.destroy()
            if not save:
                return
            row.setdefault('pending_tags', {})[field] = new_text
            if field in ('title', 'artist'):
                row['suggested_' + field] = new_text
                self.save_names.set(True)
            row['status'] = f'Edited {field} — pending save'
            self.refresh(path)
            self.tree.selection_set(path)
            self.show_details()

        ttk.Button(footer, text='Cancel', command=lambda: finish(False)).pack(side='right', padx=4)
        ttk.Button(footer, text='Apply Edit', style='Accent.TButton', command=lambda: finish(True)).pack(side='right', padx=4)
        entry.bind('<Return>', lambda e: finish(True))
        entry.bind('<Escape>', lambda e: finish(False))
        window.protocol('WM_DELETE_WINDOW', lambda: finish(False))

    def add_paths(self, paths):
        errors = 0
        expanded = []
        for incoming in paths:
            incoming = Path(incoming).expanduser()
            if incoming.is_dir():
                expanded.extend(p for p in incoming.rglob('*') if p.is_file() and p.suffix.lower() == '.mp3')
            elif incoming.is_file() and incoming.suffix.lower() == '.mp3':
                expanded.append(incoming)
        newly_added = []
        for path in expanded:
            path = str(path.resolve())
            if path in self.rows:
                continue
            try:
                track = read_track(path)
                track.update(match='', bpm='', status='Imported', cues=[])
                split = suggest_from_track(track)
                if split:
                    track['suggested_artist'], track['suggested_title'] = split
                    track['status'] = 'Artist/title suggestion ready — review'
                self.rows[path] = track
                newly_added.append(path)
                self.refresh(path)
            except Exception:
                errors += 1
        self.status.config(text=f'{len(self.rows)} MP3s loaded. {errors} unreadable files skipped.')
        if newly_added and (self.auto_lookup.get() or self.auto_bpm.get()):
            self.run_job('import', newly_added)

    def refresh(self, path):
        r = self.rows[path]
        values = tuple(display_value(r, c) for c in COLUMN_LABELS)
        if self.tree.exists(path):
            self.tree.item(path, values=values)
        else:
            self.tree.insert('', 'end', iid=path, values=values,
                             tags=('even' if len(self.rows) % 2 == 0 else 'odd',))

    def selected(self):
        return list(self.tree.selection())

    def run_job(self, kind, paths=None):
        paths = self.selected() if paths is None else paths
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
                if kind in ('lookup', 'import') and (kind == 'lookup' or self.auto_lookup.get()):
                    result = multi_lookup(r.get('suggested_artist') or r['artist'], r.get('suggested_title') or r['title'], self.config)
                    self.events.put(('result', 'lookup', path, result))
                if kind in ('analyze', 'import') and (kind == 'analyze' or self.auto_bpm.get()):
                    result = analyze_cues(path)
                    self.events.put(('result', 'analyze', path, result))
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
                if result.get('error'):
                    r['status'] = result['error'][:65]
                elif kind == 'lookup':
                    # Stage metadata for review; the Year/Genre/Composer columns
                    # display these values immediately, but MP3s change only on Save.
                    for field in ('year', 'genre', 'subgenre'):
                        value = result.get(field, '')
                        key = 'suggested_' + field
                        if value:
                            r[key] = value
                        else:
                            r.pop(key, None)
                    r['sources'] = result['sources']
                    r['lookup_warnings'] = result['errors']
                    r['match'] = str(result['score'])
                    r['status'] = 'Lookup: ' + ', '.join(result['sources']) if result['sources'] else 'No match'
                else:
                    r['bpm'] = result['bpm']
                    if not r.get('bpm_tag'):
                        r.setdefault('pending_tags', {})['bpm_tag'] = str(result['bpm'])
                    r['cues'] = result['cues']
                    r['status'] = 'BPM analyzed — save to write tag'
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
            self.artist_edit.set(r.get('suggested_artist', r.get('artist', '')))
            self.title_edit.set(r.get('suggested_title', r.get('title', '')))
            self.details.insert('end', json.dumps({k:v for k,v in r.items() if k != 'duration'}, indent=2))

    def write(self):
        paths = self.selected()
        ready = [p for p in paths if self.rows[p].get('pending_tags') or self.rows[p].get('pending_custom')
                 or any(self.rows[p].get(k) for k in ('suggested_year', 'suggested_genre', 'suggested_subgenre'))
                 or (self.save_names.get() and any(k in self.rows[p] for k in ('suggested_artist', 'suggested_title')))]
        if not ready:
            messagebox.showinfo(APP_NAME, 'Nothing to write. Edit tags or run a lookup first.')
            return
        if not messagebox.askyesno(APP_NAME,
                f'Write pending metadata to {len(ready)} original MP3(s)?\n\n'
                'No duplicate MP3 or backup will be created. These edits cannot be automatically undone.\n'
                'Composer will be replaced by a suggested subgenre if one is available.'):
            return
        success = 0
        for path in ready:
            r = self.rows[path]
            changes = {}
            if r.get('suggested_year'):
                changes['year'] = r['suggested_year']
            if r.get('suggested_genre'):
                changes['genre'] = r['suggested_genre']
            if r.get('suggested_subgenre'):
                changes['composer'] = r['suggested_subgenre']
            if self.save_names.get():
                for field in ('artist', 'title'):
                    if 'suggested_' + field in r:
                        changes[field] = r['suggested_' + field]
            changes.update(r.get('pending_tags', {}))  # Manual edits always win over lookup suggestions.
            try:
                apply_tag_changes(path, changes, r.get('pending_custom', {}))
                for key in ('pending_tags', 'pending_custom', 'suggested_year', 'suggested_genre', 'suggested_subgenre', 'suggested_artist', 'suggested_title'):
                    r.pop(key, None)
                r.update(read_track(path))
                r['status'] = 'Tags written in place'
                success += 1
            except Exception as exc:
                r['status'] = f'Write failed: {exc}'
            self.refresh(path)
        self.show_details()
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
    if TkinterDnD is not None:
        try:
            root = TkinterDnD.Tk()
        except (tk.TclError, RuntimeError, OSError) as exc:
            print(f'Native drag-and-drop could not initialize: {exc}')
            root = tk.Tk()
    else:
        root = tk.Tk()
    App(root)
    root.mainloop()