"""DJ Tag Manager: local macOS-friendly MP3 metadata editor."""
import json
import os
import sys
import sqlite3
import subprocess
from datetime import timezone
import hashlib
import copy
import math
import base64
import struct
import zlib
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
from metadata_automation import proposal as metadata_proposal, field_confidence, analyze_audio, artwork_from_musicbrainz, write_mp3_cover_art
from metadata_safety import safe_write, fingerprint, FileChangedError, history as metadata_history, restore_write
from workspace_layout import sidebar_width, valid_column_filters
from mac_feedback_fixes import MacFeedbackFixes
from update_manager import show_update_dialog
from mutagen.mp3 import MP3
from mutagen import File as MutagenFile

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except ImportError:
    DND_FILES = None
    TkinterDnD = None

# DJ Tag Manager visual system: charcoal surfaces, warm yellow highlights.
COLORS = {
    'bg': '#1D2026', 'panel': '#242830', 'raised': '#30353E',
    'hover': '#3A414B', 'line': '#343A44', 'text': '#F3F5F8',
    'muted': '#A6B0BF', 'accent': '#FACC15', 'accent_hover': '#FFE17B',
    'select': '#3B424B', 'input': '#1B1E24',
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
                    font=('Helvetica Neue', 23, 'bold'))
    # Tk's standard ttk clam buttons have square corners. Build an actual
    # transparent RGBA PNG and use its center as a stretchable 9-slice element.
    # No third-party imaging dependency is needed in the Mac bundle.
    def rounded_image(color, radius=10, size=32):
        rgb = tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
        rows = []
        for y in range(size):
            pixels = bytearray()
            for x in range(size):
                cx = max(radius - 0.5, min(x, size - radius - 0.5))
                cy = max(radius - 0.5, min(y, size - radius - 0.5))
                distance = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
                alpha = max(0, min(255, int((radius + 0.5 - distance) * 255)))
                pixels.extend((*rgb, alpha))
            rows.append(b'\x00' + bytes(pixels))
        def chunk(kind, data):
            return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data) & 0xffffffff)
        png = (b'\x89PNG\r\n\x1a\n' +
               chunk(b'IHDR', struct.pack('!2I5B', size, size, 8, 6, 0, 0, 0)) +
               chunk(b'IDAT', zlib.compress(b''.join(rows))) +
               chunk(b'IEND', b''))
        return tk.PhotoImage(master=root, data=base64.b64encode(png).decode('ascii'))

    images = [rounded_image(COLORS[c]) for c in ('raised', 'hover', 'accent', 'accent_hover')]
    root._dj_rounded_images = images
    for name, normal, hover in [('DJRound', images[0], images[1]),
                                ('DJAccentRound', images[2], images[3])]:
        style.element_create(name, 'image', normal,
                             ('pressed', hover), ('active', hover),
                             border=12, sticky='nsew')
        style.layout(('Accent.TButton' if name == 'DJAccentRound' else 'TButton'),
                     [(name, {'sticky': 'nswe', 'children':
                       [('Button.padding', {'sticky': 'nswe', 'children':
                         [('Button.label', {'sticky': 'nswe'})]})]})])
    style.configure('TButton', background=COLORS['raised'], foreground=COLORS['text'],
                    borderwidth=0, padding=(17, 12), relief='flat',
                    font=('Helvetica', 14, 'bold'))
    style.map('TButton', background=[('pressed', COLORS['hover']),
                                     ('active', COLORS['hover'])],
              foreground=[('disabled', COLORS['muted'])])
    style.configure('Accent.TButton', background=COLORS['accent'],
                    foreground=COLORS['bg'], padding=(18, 12))
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
                    rowheight=36, borderwidth=0, relief='flat',
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
    'year': 'Year', 'genre': 'Genre', 'composer': 'Composer',
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

AUDIO_EXTENSIONS = {'.mp3', '.flac', '.m4a', '.aiff', '.aif', '.wav'}
SERATO_DEFAULTS = {
    'enabled': False, 'read': True, 'write': False, 'show_crates': True,
    'manage_library': False, 'show_cues': True, 'show_loops': True,
    'bpm_beatgrid': True, 'track_colors': False, 'relocate': False,
    'sync_mode': 'manual', 'library_location': ''
}


def read_any_track(path):
    if Path(path).suffix.lower() == '.mp3':
        return dict(read_track(path), disk_fingerprint=fingerprint(path))
    audio = MutagenFile(path, easy=True)
    if audio is None or audio.info is None:
        raise ValueError('Unsupported or unreadable audio file')
    def val(k):
        v = audio.get(k, [])
        return str(v[0]) if v else ''
    duration = float(getattr(audio.info, 'length', 0))
    bitrate = getattr(audio.info, 'bitrate', 0)
    return dict(path=str(path), title=val('title') or Path(path).stem,
        artist=val('artist'), album=val('album'), album_artist=val('albumartist'),
        year=val('date'), genre=val('genre'), composer=val('composer'),
        bpm_tag=val('bpm'), key=val('initialkey'), comment=val('comment'),
        duration=duration, duration_display=f'{int(duration // 60)}:{int(duration % 60):02d}',
        bitrate=f'{round(bitrate / 1000)} kbps' if bitrate else '',
        sample_rate=f'{getattr(audio.info, "sample_rate", 0)} Hz',
        filename=Path(path).name, disk_fingerprint=fingerprint(path))


def write_any_tags(path, changes, custom_changes=None):
    if Path(path).suffix.lower() == '.mp3':
        return apply_tag_changes(path, changes, custom_changes or {})
    # Only supported, standard fields; do not touch proprietary Serato blocks.
    mapping = {'title':'title', 'artist':'artist', 'album':'album',
        'album_artist':'albumartist', 'year':'date', 'genre':'genre',
        'composer':'composer', 'track_number':'tracknumber',
        'disc_number':'discnumber', 'bpm_tag':'bpm'}
    unknown = set(changes) - set(mapping)
    if unknown or custom_changes:
        raise ValueError('These tags are not safely supported for this file format: ' + ', '.join(sorted(unknown)))
    audio = MutagenFile(path, easy=True)
    if audio is None:
        raise ValueError('Unsupported format')
    if audio.tags is None:
        audio.add_tags()
    for key, value in changes.items():
        audio[mapping[key]] = [str(value)] if value else []
    audio.save()


from advanced_ui import AdvancedTools
from integrated_workflows import IntegratedWorkflows
from waveform_player import WaveformController

class App(MacFeedbackFixes, IntegratedWorkflows, AdvancedTools):
    def __init__(self, root):
        self.root = root
        root.title(APP_NAME + ' 3.1.3 Development')
        root.geometry('1300x780')
        root.minsize(1050, 650)
        apply_dark_theme(root)
        self.rows = {}
        self.events = queue.Queue()
        self.busy = False
        self.cancel_requested = threading.Event()
        self.progress_window = None
        self.help_enabled = tk.BooleanVar(value=False)
        self.filters = {}
        self._sidebar_drag_origin = None
        self.undo_stack = []
        self.redo_stack = []
        self.saved_views = {}
        self.genre_groups = {}
        self._tooltip = None
        self._tooltip_after = None
        self.config_path = Path.home() / 'Library' / 'Application Support' / 'DJ Tag Manager v3 Combined Dev' / 'api_keys.json'
        self.config = self.load_config()
        self.auto_lookup = tk.BooleanVar(value=False)
        self.lookup_write_mode = tk.StringVar(value='confirm_each')
        self.auto_bpm = tk.BooleanVar(value=False)
        self.save_names = tk.BooleanVar(value=False)
        self.layout_path = self.config_path.with_name('column_layout.json')
        self.visible_columns = self.load_column_layout()
        self.column_widths = self.load_column_widths()
        self.preferences_path = self.config_path.with_name('v3_preferences.json')
        self.load_preferences()
        self.filters = valid_column_filters(self.extra_settings.get('column_filters', {}), COLUMN_LABELS)
        self.auto_bpm.set(bool(self.extra_settings.get('import_analyze', False)))
        self.auto_lookup.set(bool(self.extra_settings.get('import_lookup', False)))
        self._lookup_job_options = {}
        self.initialize_v3_storage()
        header = ttk.Frame(root, padding=(20, 17, 20, 8))
        header.pack(fill='x')
        ttk.Label(header, text='DJ Tag Manager', style='Brand.TLabel').pack(side='left')
        ttk.Label(header, text='  MUSIC LIBRARY  •  METADATA WORKSPACE',
                  style='Muted.TLabel').pack(side='left', padx=(12, 0))
        # The gear is in the header, not a horizontally overflowing toolbar.
        toolbar = ttk.Frame(root, padding=(16, 8, 16, 8))
        toolbar.pack(fill='x')
        self.main_toolbar = toolbar
        self.toolbar_buttons = {}
        for label, cmd in [('Import Files', self.add_files), ('Import Folder', self.add_folder), ('Scan Library', self.scan_library),
                           ('Find Tags & Art', self.lookup), ('Analyze BPM', self.analyze),
                           ('Save Changes', self.write)]:
            button = ttk.Button(toolbar, text=label, command=cmd,
                       style='Accent.TButton' if label == 'Save Changes' else 'TButton')
            button.pack(side='left', padx=4)
            self.toolbar_buttons[label] = button
        self.more_menu = tk.Menu(root, tearoff=False, bg=COLORS['panel'], fg=COLORS['text'],
                                 activebackground=COLORS['select'], activeforeground=COLORS['accent'])
        for label, cmd in [('Genre Cleanup', self.genre_cleanup), ('Find Duplicates', self.find_duplicates),
                           ('Detect Musical Key', self.detect_keys), ('Smart Filters', self.smart_filters),
                           ('Undo', self.undo), ('Redo', self.redo), ('Auto-Fix Title', self.suggest_split), ('View Metadata', self.all_metadata),
                           ('Edit Metadata', self.edit_all_tags), ('Show in Finder', self.reveal_selected),
                           ('Export Cue Suggestions', self.export)]:
            self.more_menu.add_command(label=label, command=cmd)
        more_button = ttk.Button(toolbar, text='More Actions  ···', command=lambda: self.show_popup(self.more_menu, more_button))
        more_button.pack(side='left', padx=4)
        self.toolbar_buttons['More Actions'] = more_button
        # Keep configuration out of the main toolbar. Each menu item opens its
        # existing dialog or toggles a preference without modifying MP3 files.
        self.settings_menu = tk.Menu(root, tearoff=False, bg=COLORS['panel'],
                                     fg=COLORS['text'], activebackground=COLORS['select'],
                                     activeforeground=COLORS['accent'], borderwidth=0)
        self.settings_menu.add_command(label='Check for Updates…', command=lambda: show_update_dialog(self.root))
        self.settings_menu.add_separator()
        self.settings_menu.add_command(label='API Settings…', command=self.settings)
        self.settings_menu.add_command(label='Import & Automation…', command=self.import_automation_settings)
        self.settings_menu.add_command(label='Metadata Automation…', command=self.metadata_automation_settings)
        self.settings_menu.add_command(label='Find Cover Art for Selected MP3…', command=self.find_cover_art_selected)
        self.settings_menu.add_command(label='Backup Library…', command=self.backup_library)
        self.settings_menu.add_command(label='Restore Library Backup…', command=self.restore_library_backup)
        self.settings_menu.add_command(label='Genre Lookup Diagnostics…', command=self.show_lookup_debug)
        self.settings_menu.add_separator()
        # v3: import never triggers network lookup automatically
        # v3: import never triggers analysis automatically
        self.settings_menu.add_checkbutton(label='Include artist/title when writing tags', variable=self.save_names)
        self.settings_button = ttk.Button(header, text='⚙ Settings', command=self.open_settings_menu)
        self.settings_button.pack(side='right', padx=(8, 0))
        self.help_button = tk.Button(header, text='?', width=3, height=1, font=('Helvetica', 17, 'bold'),
            bg=COLORS['raised'], fg=COLORS['text'], activebackground=COLORS['accent'],
            relief='flat', command=self.toggle_help)
        self.help_button.pack(side='right', padx=(4, 0))
        self.install_help()
        if self.help_enabled.get():
            self.help_button.configure(bg=COLORS['accent'],fg=COLORS['bg'])
        self.drop_label = ttk.Label(root, text='↓   DROP MUSIC FILES OR FOLDERS HERE   •   MANUAL LOOKUP & ANALYSIS',
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
        self.content = ttk.Frame(root)
        self.content.pack(fill='both', expand=True, padx=16, pady=(8, 6))
        self.sidebar = tk.Frame(self.content, bg='#15171B', width=sidebar_width(self.extra_settings.get('sidebar_width', 240)))
        self.sidebar.pack(side='left', fill='y', padx=(0,0))
        self._sidebar_grip = tk.Frame(self.content, bg=COLORS['line'], width=5, cursor='sb_h_double_arrow')
        self._sidebar_grip.pack(side='left', fill='y', padx=(0,10))
        self._sidebar_grip.bind('<ButtonPress-1>', self._sidebar_resize_start)
        self._sidebar_grip.bind('<B1-Motion>', self._sidebar_resize_move)
        self._sidebar_grip.bind('<ButtonRelease-1>', self._sidebar_resize_end)
        self.sidebar.pack_propagate(False)
        table_frame = ttk.Frame(self.content)
        table_frame.pack(side='left', fill='both', expand=True)
        self._library_table_frame = table_frame
        self._genre_workspace = None
        self.tree = ttk.Treeview(table_frame, columns=tuple(COLUMN_LABELS), show='headings', selectmode='extended')
        self.table_vscroll = tk.Scrollbar(table_frame, orient='vertical', command=self.tree.yview,
            width=7, bg=COLORS['raised'], troughcolor=COLORS['bg'], relief='flat',
            borderwidth=0, highlightthickness=0, activebackground=COLORS['hover'])
        self.table_hscroll = tk.Scrollbar(table_frame, orient='horizontal', command=self.tree.xview,
            width=7, bg=COLORS['raised'], troughcolor=COLORS['bg'], relief='flat',
            borderwidth=0, highlightthickness=0, activebackground=COLORS['hover'])
        self.tree.configure(yscrollcommand=self.table_vscroll.set, xscrollcommand=self.table_hscroll.set)
        self.table_vscroll.pack(side='right', fill='y')
        self.table_hscroll.pack(side='bottom', fill='x')
        self.configure_columns()
        self.tree.pack(side='left', fill='both', expand=True)
        self.tree.tag_configure('odd', background=COLORS['panel'])
        self.tree.tag_configure('even', background=COLORS['panel'])
        self.tree.bind('<<TreeviewSelect>>', self.show_details)
        self.tree.bind('<Command-a>', self.select_all_visible)
        self.tree.bind('<Control-a>', self.select_all_visible)
        self.tree.bind('<Escape>', lambda e: self.tree.selection_remove(self.tree.selection()))
        # Keyboard actions are installed by IntegratedWorkflows so remapping is reliable.
        self.tree.bind('<Double-1>', self.play_clicked_song)
        self.tree.bind('<Button-2>', self.on_header_context_menu)
        self.tree.bind('<Button-3>', self.on_header_context_menu)
        self.tree.bind('<Control-Button-1>', self.on_header_context_menu)
        self.tree.bind('<ButtonPress-1>', self.on_header_press, add='+')
        self.tree.bind('<ButtonRelease-1>', self.on_header_release, add='+')
        self.tree.bind('<Shift-Button-1>', self.on_shift_header_sort, add='+')
        self.tree.bind('<space>', self._space_play_pause)
        self.root.bind_all('<space>', self._space_play_pause, add='+')
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
        self.build_player()
        self.status = ttk.Label(root, text='●  Ready  •  Add MP3s or drop a folder to begin',
                                padding=(20, 12), style='Muted.TLabel')
        self.status.pack(fill='x')
        self.selection_status = ttk.Label(root, text='0 of 0 tracks selected', style='Muted.TLabel')
        self.selection_status.pack(anchor='e', padx=20, pady=(0, 4))
        self.build_sidebar()
        self.restore_library()
        self.setup_advanced()
        self.setup_integrated()
        self._setup_sidebar_toggle()
        self.install_mac_feedback_fixes()
        if self.filters:
            self.apply_filters()
        root.protocol('WM_DELETE_WINDOW', self.close_app)
        root.after(100, self.poll)

    def initialize_v3_storage(self):
        self.data_dir = self.config_path.parent
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.library_file = self.data_dir / 'v3_preview_library.json'
        self.player_process = None
        self.player_path = None
        self.last_double_click = 0
        self.sidebar_buttons = {}
        self.current_view = 'All Tracks'

    def persist_library(self):
        self.library_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {'paths':list(self.rows), 'last_track':self.player_path}
        tmp = self.library_file.with_suffix('.tmp')
        tmp.write_text(json.dumps(payload, indent=2), encoding='utf-8')
        os.replace(tmp, self.library_file)

    def restore_library(self):
        try:
            saved = json.loads(self.library_file.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return
        for path in saved.get('paths', []):
            if path in self.rows:
                continue
            if not Path(path).is_file():
                self.rows[path] = dict(path=path, title=Path(path).stem, artist='',
                    status='Missing file', genre='', bitrate='', duration_display='')
            else:
                try:
                    self.rows[path] = read_any_track(path)
                    self.rows[path].update(status='Loaded', match='', bpm='', cues=[])
                except Exception:
                    self.rows[path] = dict(path=path, title=Path(path).stem,
                        artist='', status='Unreadable file')
            self.refresh(path)
        self.player_path = saved.get('last_track')
        self.update_player_label()
        self.update_sidebar_counts()

    def scan_library(self):
        changed = 0
        for path, row in self.rows.items():
            if not Path(path).is_file():
                row['status'] = 'Missing file'
                changed += 1
            else:
                try:
                    current = read_any_track(path)
                    if any(current.get(k) != row.get(k) for k in ('title','artist','genre','year')):
                        row.update(current)
                        row['status'] = 'Updated from disk'
                        changed += 1
                except Exception:
                    row['status'] = 'Unreadable file'
                    changed += 1
            self.refresh(path)
        self.persist_library()
        self.update_sidebar_counts()
        self.status.configure(text=f'Scan complete: {changed} changed or missing tracks.')

    def build_sidebar(self):
        # A separate left panel is placed next to the existing content.
        # Sidebar is embedded in the library content frame.
        tk.Label(self.sidebar, text='LIBRARY', bg='#15171B', fg=COLORS['accent'],
            font=('Helvetica', 11, 'bold')).pack(anchor='w', padx=14, pady=(12,6))
        for name in ('All Tracks','Missing Files','Missing Tags','Low Bitrate','Unreviewed','Possible Revisions'):
            button = tk.Button(self.sidebar, text=name, anchor='w', bg='#15171B', fg='#F5F5F5',
                activebackground='#292D35', activeforeground=COLORS['accent'],
                borderwidth=0, padx=14, pady=8,
                command=lambda n=name:self.choose_view(n))
            button.pack(fill='x')
            self.sidebar_buttons[name] = button
        tk.Label(self.sidebar, text='LIBRARY TOOLS', bg='#15171B', fg=COLORS['accent'],
            font=('Helvetica', 11, 'bold')).pack(anchor='w', padx=14, pady=(15,5))
        for name, action in [('Duplicates',self.find_duplicates),('Genre Cleanup',self.genre_cleanup),('Name Cleanup',self.name_cleanup_review),
            ('Smart Filters',self.smart_filters),('Relocate Missing',self.relocate_missing)]:
            tk.Button(self.sidebar, text=name, anchor='w', bg='#15171B', fg='#F5F5F5',
                borderwidth=0, padx=14, pady=7, command=action).pack(fill='x')
        self.choose_view('All Tracks')

    def update_sidebar_counts(self):
        if not hasattr(self, 'sidebar_buttons'):
            return
        for name, button in self.sidebar_buttons.items():
            count = sum(self.matches_view(r, name) for r in self.rows.values())
            button.configure(text=f'{name}  ({count})')

    def matches_view(self, row, name):
        if name == 'All Tracks': return True
        if name == 'Missing Files': return not Path(row['path']).is_file()
        if name == 'Missing Tags': return not row.get('artist') or not row.get('genre')
        if name == 'Low Bitrate':
            match = re.search(r'\d+', str(row.get('bitrate','')))
            return bool(match and int(match.group()) < self.extra_settings.get('low_bitrate',320))
        if name == 'Unreviewed': return row.get('status') != 'Tags written in place'
        if name == 'Possible Revisions': return 'revision' in row.get('status','').lower()
        return True

    def choose_view(self, name):
        workspace = getattr(self, '_genre_workspace', None)
        if workspace is not None and workspace.winfo_exists():
            closer = getattr(self, '_close_genre_workspace', None)
            if closer: closer()
        self.current_view = name
        for n, button in self.sidebar_buttons.items():
            button.configure(fg=COLORS['accent'] if n == name else '#F5F5F5')
        for path, row in self.rows.items():
            visible = self.matches_view(row,name)
            if visible and self.tree.exists(path): self.tree.move(path, '', 'end')
            elif not visible and self.tree.exists(path): self.tree.detach(path)
        if hasattr(self,'advanced_filter') and self.advanced_filter.get('rules'):
            self._apply_advanced_filter()
        self.show_details()

    def build_player(self):
        # Two rows: waveform above track information and transport.
        panel = tk.Frame(self.root, bg='#171A20', highlightthickness=0)
        panel.pack(fill='x', side='bottom', padx=12, pady=(0, 5))
        self.player_panel = panel
        wave_row = tk.Frame(panel, bg='#22262E', height=78)
        wave_row.pack(fill='x', padx=10, pady=(9, 3))
        wave_row.pack_propagate(False)
        self.player_wave_row = wave_row
        self.player_collapsed = False
        self.player_collapse_button = tk.Label(panel, text='▾  Music Player', bg='#30353E', fg='#FACC15', cursor='hand2', anchor='w', padx=12, pady=5)
        self.player_collapse_button.bind('<Button-1>', lambda _e: self.set_player_collapsed(not self.player_collapsed))
        self.waveform_controller = WaveformController(self, wave_row)
        self.waveform_controller.wave.configure(height=65)
        transport = tk.Frame(panel, bg='#171A20', height=49)
        transport.pack(fill='x', padx=10, pady=(3, 9))
        self.player_button = tk.Button(transport, text='▶', command=self.toggle_playback,
            bg='#FACC15', fg='#171A20', activebackground='#FDE047', activeforeground='#171A20',
            borderwidth=0, relief='flat', font=('Helvetica', 15, 'bold'), width=3)
        self.player_button.pack(side='left', padx=(0, 12))
        self.player_label = tk.Label(transport, text='No track loaded', bg='#171A20', fg='#F5F5F5',
            font=('Helvetica', 12), anchor='w')
        self.player_label.pack(side='left', fill='x', expand=True)
        tk.Button(transport, text='Edit Metadata', command=self.edit_all_tags, bg='#30353E',
                  fg='#F5F5F5', relief='flat', borderwidth=0).pack(side='right', padx=5)

    def set_player_collapsed(self, collapsed):
        """Collapse waveform without stopping playback or recreating the player."""
        self.player_collapsed = bool(collapsed)
        if collapsed:
            self.player_wave_row.pack_forget()
            self.player_collapse_button.configure(text='▸  Music Player — click to expand')
            self.player_collapse_button.pack(fill='x', before=self.player_panel.winfo_children()[-1])
        else:
            self.player_collapse_button.pack_forget()
            self.player_wave_row.pack(fill='x', padx=10, pady=(9, 3), before=self.player_panel.winfo_children()[-1])

    def update_player_label(self):
        if not hasattr(self, 'player_label'): return
        r = self.rows.get(self.player_path, {})
        self.player_label.configure(text=(f"{r.get('title',Path(self.player_path).stem)}  —  {r.get('artist','')}"
            if self.player_path else 'No track loaded'))

    def _space_play_pause(self, event):
        # Never intercept a space while the user is editing or typing.
        if isinstance(event.widget, (tk.Entry, ttk.Entry, tk.Text, ttk.Combobox, tk.Spinbox)):
            return None
        self.toggle_playback()
        return 'break'

    def play_clicked_song(self, event):
        self.last_double_click = time.monotonic()
        path = self.tree.identify_row(event.y)
        if path:
            self.play_track(path)
        return 'break'

    def maybe_edit_selected_cell(self, event):
        # A click on an already-selected cell opens editing; never on the first selection click.
        path = self.tree.identify_row(event.y)
        if path and path in self.tree.selection() and self.tree.identify_region(event.x,event.y) == 'cell':
            self.root.after(240, lambda p=path, x=event.x, y=event.y:
                self.edit_song_cell(type('Click', (), {'x':x,'y':y})())
                if p in self.tree.selection() and time.monotonic()-self.last_double_click > .35 else None)

    def play_track(self, path):
        if not Path(path).is_file():
            return messagebox.showwarning(APP_NAME, 'Track is missing. Relocate it before playing.')
        self.stop_playback()
        self.player_path = path
        self.update_player_label()
        self.waveform_controller.load(path)
        self._launch_playback(0)
        self.persist_library()

    def _launch_playback(self, seconds=0):
        if not self.player_path or not Path(self.player_path).is_file(): return
        self.stop_playback()
        if sys.platform != 'darwin':
            return messagebox.showinfo(APP_NAME, 'Audio preview requires macOS afplay.')
        args=['/usr/bin/afplay','-v',str(self.waveform_controller.volume.get())]
        if seconds>0:
            if not self.waveform_controller.seek_supported:
                return self.status.configure(text='Seeking unavailable on this afplay version.')
            args+=['-s',str(seconds)]
        args.append(self.player_path)
        try:
            self.player_process=subprocess.Popen(args,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
            self.player_button.configure(text='■')
            self.waveform_controller.start_position=seconds
            self.waveform_controller.position=seconds
            self.waveform_controller.started=time.monotonic()
        except OSError as exc:messagebox.showerror(APP_NAME,f'Playback unavailable: {exc}')

    def stop_playback(self):
        if self.player_process and self.player_process.poll() is None:
            self.player_process.terminate()
        self.player_process=None
        if hasattr(self,'waveform_controller'):self.waveform_controller.started=None
        if hasattr(self,'player_button'):self.player_button.configure(text='▶')

    def toggle_playback(self):
        if self.player_process and self.player_process.poll() is None:self.stop_playback()
        elif self.player_path:self._launch_playback(self.waveform_controller.position)
        elif self.selected():self.play_track(self.selected()[0])

    def serato_settings(self):
        win=tk.Toplevel(self.root)
        win.title('Serato Integration — Preview')
        win.geometry('570x680')
        win.configure(bg=COLORS['bg'])
        ttk.Label(win,text='Serato Integration',style='Brand.TLabel').pack(anchor='w',padx=18,pady=15)
        ttk.Label(win,text='Read-only foundation. Proprietary writes are disabled until tested.',
            style='Muted.TLabel').pack(anchor='w',padx=18,pady=(0,12))
        options = [
            ('enabled','Enable Serato Integration'),('read','Read Serato Data'),
            ('write','Write Serato Data (not yet supported)'),('show_crates','Show Serato Crates'),
            ('manage_library','Create & Manage Serato Library (not yet supported)'),
            ('show_cues','Show Serato Hot Cues'),('show_loops','Show Saved Loops'),
            ('bpm_beatgrid','Read BPM & Beatgrids'),('track_colors','Track Colors & Ratings'),
            ('relocate','Relocate Serato Tracks (not yet supported)')]
        vars = {}
        for key,label in options:
            v=tk.BooleanVar(value=self.serato_options.get(key,False))
            vars[key]=v
            cb=ttk.Checkbutton(win,text=label,variable=v)
            cb.pack(anchor='w',padx=24,pady=6)
            if key in ('write','manage_library','relocate'):
                cb.configure(state='disabled')
        ttk.Label(win,text='Serato Library Location',style='Muted.TLabel').pack(anchor='w',padx=18,pady=(15,4))
        location=tk.StringVar(value=self.serato_options.get('library_location',''))
        ttk.Entry(win,textvariable=location).pack(fill='x',padx=18)
        def browse():
            folder=filedialog.askdirectory(parent=win)
            if folder:location.set(folder)
        ttk.Button(win,text='Choose Folder…',command=browse).pack(anchor='w',padx=18,pady=8)
        def save():
            self.serato_options.update({k:v.get() for k,v in vars.items()})
            self.serato_options['write']=False
            self.serato_options['manage_library']=False
            self.serato_options['relocate']=False
            self.serato_options['sync_mode']='manual'
            self.serato_options['library_location']=location.get().strip()
            self.save_preferences()
            win.destroy()
        ttk.Button(win,text='Save Settings',style='Accent.TButton',command=save).pack(pady=12)

    def backup_library(self):
        dest = filedialog.asksaveasfilename(title='Backup DJ Tag Manager library',
            defaultextension='.json', filetypes=[('JSON backup','*.json')])
        if not dest: return
        payload = {'schema':1, 'created':datetime.now(timezone.utc).isoformat(),
            'tracks':list(self.rows), 'settings':self.serato_options,
            'saved_views':self.saved_views, 'genre_groups':self.genre_groups}
        Path(dest).write_text(json.dumps(payload, indent=2), encoding='utf-8')
        messagebox.showinfo(APP_NAME, 'Library paths and preferences backed up. Music files were not copied.')

    def restore_library_backup(self):
        source = filedialog.askopenfilename(filetypes=[('JSON backup','*.json')])
        if not source:return
        try:
            data = json.loads(Path(source).read_text(encoding='utf-8'))
            if data.get('schema') != 1 or not isinstance(data.get('tracks'),list):
                raise ValueError('Unrecognized backup format')
            paths = data['tracks']
            if not all(isinstance(p,str) for p in paths):
                raise ValueError('Invalid track paths')
        except (OSError, ValueError) as exc:
            return messagebox.showerror(APP_NAME,f'Cannot restore backup: {exc}')
        if not messagebox.askyesno(APP_NAME,
            f'Restore {len(paths)} library entries? Existing library entries will be retained.'):
            return
        self.add_paths([p for p in paths if Path(p).is_file()])
        for path in paths:
            if path not in self.rows and not Path(path).exists():
                self.rows[path] = dict(path=path,title=Path(path).stem,artist='',
                    genre='',status='Missing file')
                self.refresh(path)
        self.persist_library()
        self.update_sidebar_counts()

    def relocate_missing(self):
        selected = [p for p in self.selected() if not Path(p).is_file()]
        if len(selected) != 1:
            return messagebox.showinfo(APP_NAME,'Select one missing track to relocate.')
        old = selected[0]
        replacement = filedialog.askopenfilename(title='Locate ' + Path(old).name)
        if not replacement:return
        if Path(replacement).suffix.lower() not in AUDIO_EXTENSIONS:
            return messagebox.showwarning(APP_NAME,'Choose a supported audio file.')
        try:
            track = read_any_track(replacement)
        except Exception as exc:
            return messagebox.showerror(APP_NAME,f'Could not read replacement: {exc}')
        if Path(old).name.casefold() != Path(replacement).name.casefold():
            if not messagebox.askyesno(APP_NAME,
                f'The replacement filename differs from {Path(old).name}. Use it anyway?'):
                return
        self.tree.delete(old)
        self.rows.pop(old)
        replacement = str(Path(replacement).resolve())
        track.update(status='Relocated', match='', bpm='', cues=[])
        self.rows[replacement] = track
        self.refresh(replacement)
        self.persist_library()
        self.update_sidebar_counts()
        self.status.configure(text='Library path repaired. Serato crate references were not changed.')

    def close_app(self):
        if self.busy and not messagebox.askyesno(APP_NAME,'A task is running. Cancel it and close?'):
            return
        self.cancel_requested.set()
        self.queue_engine.stop()
        self.stop_playback()
        self.persist_library()
        self.save_preferences()
        self.root.destroy()

    def show_popup(self, menu, button):
        self.root.update_idletasks()
        try:
            menu.tk_popup(button.winfo_rootx(), button.winfo_rooty() + button.winfo_height())
        finally:
            menu.grab_release()

    def open_settings_menu(self):
        # Anchor the popup to the gear button, rather than the mouse pointer.
        self.root.update_idletasks()
        x = self.settings_button.winfo_rootx()
        y = self.settings_button.winfo_rooty() + self.settings_button.winfo_height()
        try:
            self.settings_menu.tk_popup(x, y)
        finally:
            self.settings_menu.grab_release()

    def _sidebar_resize_start(self, event):
        self._sidebar_drag_origin = (event.x_root, self.sidebar.winfo_width())

    def _sidebar_resize_move(self, event):
        if self._sidebar_drag_origin is None or self.extra_settings.get('sidebar_collapsed', False):
            return
        origin_x, origin_width = self._sidebar_drag_origin
        width = max(180, min(350, origin_width + event.x_root - origin_x))
        self.sidebar.configure(width=width)

    def _sidebar_resize_end(self, event):
        if self._sidebar_drag_origin is not None:
            self._sidebar_resize_move(event)
            self._sidebar_drag_origin = None
            self.extra_settings['sidebar_width'] = self.sidebar.winfo_width()
            self.save_preferences()

    def _setup_sidebar_toggle(self):
        self._sidebar_toggle = ttk.Button(self.sidebar, text='◀ Collapse sidebar', command=self.toggle_sidebar)
        self._sidebar_toggle.pack(side='bottom', fill='x', padx=8, pady=10)
        if self.extra_settings.get('sidebar_collapsed', False):
            self.toggle_sidebar(force=True)

    def toggle_sidebar(self, force=False):
        collapsed = bool(self.extra_settings.get('sidebar_collapsed', False))
        new_collapsed = collapsed if force else not collapsed
        if new_collapsed:
            self.sidebar.configure(width=54)
            for child in self.sidebar.winfo_children():
                if child is not self._sidebar_toggle:
                    child.pack_forget()
            self._sidebar_toggle.configure(text='▶')
        else:
            self.sidebar.configure(width=sidebar_width(self.extra_settings.get('sidebar_width', 240)))
            # Rebuild the sidebar instead of guessing old pack positions.
            for child in list(self.sidebar.winfo_children()):
                if child is not self._sidebar_toggle:
                    child.destroy()
            active_view = self.current_view
            self.build_sidebar()
            self.choose_view(active_view)
            self.add_advanced_sidebar()
            self._build_sidebar_additions()
            self._sidebar_toggle.configure(text='◀ Collapse sidebar')
        self.extra_settings['sidebar_collapsed'] = new_collapsed
        self.save_preferences()

    def configure_columns(self):
        self.tree.configure(displaycolumns=tuple(self.visible_columns))
        for col in COLUMN_LABELS:
            self.tree.heading(col, text='⌕  ' + COLUMN_LABELS[col] + '  ▾',
                command=lambda c=col: self.header_search(c))
            width = self.column_widths.get(col, 200 if col in ('title', 'path', 'status') else 150 if col in ('artist', 'album', 'composer') else 110)
            self.tree.column(col, width=width, minwidth=60, stretch=True, anchor='center')

    def load_column_layout(self):
        """Restore column visibility/order, ignoring fields removed by upgrades."""
        try:
            saved = json.loads(self.layout_path.read_text(encoding='utf-8'))
            fields = saved.get('visible_columns', [])
            valid = list(dict.fromkeys(key for key in fields if key in COLUMN_LABELS))
            return valid or list(DEFAULT_COLUMNS)
        except (OSError, ValueError, TypeError, AttributeError):
            return list(DEFAULT_COLUMNS)

    def load_column_widths(self):
        try:
            data = json.loads(self.layout_path.read_text(encoding='utf-8'))
            return {k: max(60, min(900, int(v))) for k, v in data.get('widths', {}).items()
                    if k in COLUMN_LABELS}
        except (OSError, ValueError, TypeError, AttributeError):
            return {}

    def capture_column_widths(self):
        if not hasattr(self, 'tree'):
            return
        for key in COLUMN_LABELS:
            try:
                self.column_widths[key] = int(self.tree.column(key, 'width'))
            except (tk.TclError, ValueError):
                pass

    def save_column_layout(self):
        try:
            self.layout_path.parent.mkdir(parents=True, exist_ok=True)
            self.layout_path.write_text(json.dumps({'visible_columns': self.visible_columns, 'widths': self.column_widths}, indent=2), encoding='utf-8')
        except OSError as exc:
            messagebox.showwarning(APP_NAME, f'Column layout could not be saved: {exc}')

    def choose_columns(self):
        """Searchable, scrollable, clearly checked column picker."""
        window = tk.Toplevel(self.root)
        style_popup(window)
        window.title('Customize Columns')
        window.geometry('490x650')
        window.minsize(400, 450)
        ordered = list(self.visible_columns) + [k for k in COLUMN_LABELS if k not in self.visible_columns]
        checked = {k: k in self.visible_columns for k in COLUMN_LABELS}
        ttk.Label(window, text='Customize Columns', style='Brand.TLabel').pack(anchor='w', padx=18, pady=(15, 3))
        counter = ttk.Label(window, style='Muted.TLabel')
        counter.pack(anchor='w', padx=18)
        search = tk.StringVar()
        ttk.Entry(window, textvariable=search).pack(fill='x', padx=18, pady=10)
        controls = ttk.Frame(window)
        controls.pack(fill='x', padx=16, pady=(0, 8))
        ttk.Button(controls, text='Show All', command=lambda: set_preset('all')).pack(side='left', padx=2)
        ttk.Button(controls, text='Hide All', command=lambda: set_preset('none')).pack(side='left', padx=2)
        ttk.Button(controls, text='DJ Default', command=lambda: set_preset('default')).pack(side='left', padx=2)
        holder = ttk.Frame(window)
        holder.pack(fill='both', expand=True, padx=18)
        listbox = tk.Listbox(holder, selectmode='browse', exportselection=False, activestyle='none')
        style_plain_widget(listbox)
        scroller = ttk.Scrollbar(holder, orient='vertical', command=listbox.yview)
        listbox.configure(yscrollcommand=scroller.set)
        listbox.pack(side='left', fill='both', expand=True)
        scroller.pack(side='right', fill='y')
        filtered = []
        def render(keep=None):
            nonlocal filtered
            filtered = [k for k in ordered if search.get().lower() in COLUMN_LABELS[k].lower()]
            listbox.delete(0, 'end')
            for k in filtered:
                listbox.insert('end', ('☑  ' if checked[k] else '☐  ') + COLUMN_LABELS[k])
            if keep in filtered:
                i = filtered.index(keep)
                listbox.selection_set(i)
                listbox.see(i)
            counter.configure(text=f'{sum(checked.values())} of {len(checked)} columns visible  •  Yellow = enabled')
        def current():
            selection = listbox.curselection()
            return filtered[selection[0]] if selection else None
        def toggle(event=None):
            k = current()
            if k:
                checked[k] = not checked[k]
                render(k)
        def move(direction):
            k = current()
            if not k: return
            i = ordered.index(k)
            j = i + direction
            if 0 <= j < len(ordered):
                ordered[i], ordered[j] = ordered[j], ordered[i]
                render(k)
        def set_preset(mode):
            if mode == 'default':
                ordered[:] = list(DEFAULT_COLUMNS) + [k for k in COLUMN_LABELS if k not in DEFAULT_COLUMNS]
            for k in checked:
                checked[k] = mode == 'all' or (mode == 'default' and k in DEFAULT_COLUMNS)
            render()
        search.trace_add('write', lambda *_: render())
        listbox.bind('<Double-1>', toggle)
        listbox.bind('<space>', lambda e: (toggle(), 'break')[1])
        buttons = ttk.Frame(window)
        buttons.pack(fill='x', padx=18, pady=8)
        ttk.Button(buttons, text='Toggle Selected', command=toggle).pack(side='left', padx=2)
        ttk.Button(buttons, text='↑ Move Up', command=lambda: move(-1)).pack(side='left', padx=2)
        ttk.Button(buttons, text='↓ Move Down', command=lambda: move(1)).pack(side='left', padx=2)
        def apply():
            chosen = [k for k in ordered if checked[k]]
            if not chosen:
                messagebox.showwarning(APP_NAME, 'Keep at least one column visible.', parent=window)
                return
            self.visible_columns = chosen
            self.configure_columns()
            self.save_column_layout()
            window.destroy()
        footer = ttk.Frame(window)
        footer.pack(fill='x', padx=18, pady=(2, 15))
        ttk.Button(footer, text='Cancel', command=window.destroy).pack(side='right', padx=4)
        ttk.Button(footer, text='Apply Columns', style='Accent.TButton', command=apply).pack(side='right', padx=4)
        render()

    def on_header_context_menu(self, event):
        if self.tree.identify_region(event.x, event.y) != 'heading':
            return
        self.column_dropdown(event.x_root, event.y_root)
        return 'break'

    def column_dropdown(self, x=None, y=None):
        """Immediate, persistent two-column visibility chooser anchored to header."""
        if getattr(self, '_column_popup', None) and self._column_popup.winfo_exists():
            self._column_popup.destroy()
        pop = tk.Toplevel(self.root)
        self._column_popup = pop
        pop.overrideredirect(True)
        pop.configure(bg=COLORS['line'])
        pop.geometry(f'+{x or self.tree.winfo_rootx()}+{y or self.tree.winfo_rooty()}')
        body = tk.Frame(pop, bg=COLORS['panel'], padx=10, pady=10)
        body.pack(padx=1, pady=1)
        tk.Label(body, text='VISIBLE COLUMNS    (click to toggle)', bg=COLORS['panel'],
            fg=COLORS['accent'], font=('Helvetica', 12, 'bold')).grid(row=0,column=0,columnspan=2,sticky='w',pady=(0,8))
        for i,(key,label) in enumerate(COLUMN_LABELS.items()):
            var=tk.BooleanVar(value=key in self.visible_columns)
            def toggle(k=key):
                self.toggle_column(k)
            cb=tk.Checkbutton(body,text=label,variable=var,command=toggle,
                bg=COLORS['panel'],fg=COLORS['text'],selectcolor=COLORS['raised'],
                activebackground=COLORS['panel'],activeforeground=COLORS['accent'],
                font=('Helvetica',12),anchor='w',indicatoron=True)
            cb.grid(row=1+i%14,column=i//14,sticky='ew',padx=8,pady=3)
        tk.Button(body,text='Close ×',command=pop.destroy,bg=COLORS['raised'],fg=COLORS['text'],
            relief='flat').grid(row=16,column=0,columnspan=2,sticky='ew',pady=(8,0))
        pop.lift()

    def header_search(self, field):
        """An inline filter floats directly over its column heading (no popup dialog)."""
        self._last_column_search = field
        old = getattr(self, '_inline_header_entry', None)
        if old is not None and old.winfo_exists():
            old.destroy()
        if field not in self.visible_columns:
            return
        self.root.update_idletasks()
        display_index = self.visible_columns.index(field)
        x = sum(self.tree.column(c, 'width') for c in self.visible_columns[:display_index])
        width = self.tree.column(field, 'width')
        var = tk.StringVar(value=self.filters.get(field, ''))
        entry = ttk.Entry(self.tree, textvariable=var)
        self._inline_header_entry = entry
        entry.place(x=x+2, y=2, width=max(75,width-4), height=28)
        def changed(*_):
            value = var.get().strip()
            if value: self.filters[field] = value
            else: self.filters.pop(field, None)
            self.apply_filters()
        var.trace_add('write', changed)
        entry.bind('<Escape>', lambda e: (entry.destroy(), 'break')[-1])
        entry.bind('<Return>', lambda e: (entry.destroy(), 'break')[-1])
        entry.focus_set()
        entry.selection_range(0, 'end')

    def sort_column(self, field):
        """Cycle ascending, descending, and original import order."""
        state = getattr(self, '_sort_state', None)
        if state is None:
            state = self._sort_state = {}
        direction = (state.get(field, 0) + 1) % 3
        state[field] = direction
        if direction == 0:
            paths = [p for p in self.rows if self.tree.exists(p)]
        else:
            def key(path):
                raw = str(display_value(self.rows[path], field) or '').strip()
                if field in ('bpm','bpm_tag','year','bitrate','duration'):
                    match = re.search(r'\d+(?:\.\d+)?',raw)
                    return (0,float(match.group())) if match else (1,0)
                return (0,raw.casefold())
            paths = sorted((p for p in self.rows if self.tree.exists(p)),
                           key=key, reverse=(direction == 2))
        for position,path in enumerate(paths):
            if self.tree.parent(path) == '' and path in self.tree.get_children(''):
                self.tree.move(path, '', position)

    def column_header_menu(self, field, x, y):
        menu = tk.Menu(self.root, tearoff=False, bg=COLORS['panel'], fg=COLORS['text'],
                       activebackground=COLORS['raised'], activeforeground=COLORS['accent'])
        menu.add_command(label='Search this column', command=lambda: self.header_search(field))
        menu.add_command(label='Sort ascending / descending / original', command=lambda: self.sort_column(field))
        menu.add_command(label='Clear this filter', command=lambda: (self.filters.pop(field,None),self.apply_filters()))
        menu.tk_popup(x,y)
        menu.grab_release()

    def apply_filters(self):
        self.extra_settings['column_filters'] = dict(self.filters)
        self.save_preferences()
        selected=set(self.tree.selection())
        for path in self.rows:
            visible=True
            for field,term in self.filters.items():
                value=str(display_value(self.rows[path],field))
                if field in ('bpm','bpm_tag') and re.fullmatch(r'\d+\s*-\s*\d+',term):
                    lo,hi=map(float,term.split('-'))
                    try: visible=lo<=float(value)<=hi
                    except ValueError:visible=False
                else: visible=term.casefold() in value.casefold()
                if not visible:break
            if visible and self.tree.exists(path) and not self.tree.parent(path) and path not in self.tree.get_children(''):
                self.tree.move(path,'','end')
            elif visible and not self.tree.exists(path):
                self.refresh(path)
            elif not visible and self.tree.exists(path):
                self.tree.detach(path)
        self.show_details()

    def select_all_visible(self,event=None):
        if isinstance(self.root.focus_get(),(tk.Entry,ttk.Entry,tk.Text)):
            return
        self.tree.selection_set(self.tree.get_children(''))
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

    def on_shift_header_sort(self, event):
        if self.tree.identify_region(event.x,event.y) != 'heading':
            return
        try: index=int(self.tree.identify_column(event.x)[1:])-1
        except (ValueError, IndexError): return
        if 0 <= index < len(self.visible_columns):
            self.sort_column(self.visible_columns[index])
            return 'break'

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
        self.capture_column_widths()
        self.save_column_layout()
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

    def show_lookup_debug(self):
        paths = self.selected()
        if not paths:
            messagebox.showinfo(APP_NAME, 'Select a track to inspect its lookup diagnostics.')
            return
        r = self.rows[paths[0]]
        if 'lookup_debug' not in r:
            messagebox.showinfo(APP_NAME, 'Run Lookup Metadata first. Diagnostic results will appear in the raw JSON panel.')
            return
        self.show_details()
        messagebox.showinfo(APP_NAME, 'The selected track’s lookup_debug object is in the raw JSON panel below the song list. No API keys are included.')

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
        ttk.Label(window, text='Save Changes writes to the selected MP3 with a recovery backup. Empty values clear tags.', wraplength=660).pack(anchor='w', padx=12)
        canvas = tk.Canvas(window, highlightthickness=0)
        style_plain_widget(canvas)
        scrollbar = ttk.Scrollbar(window, orient='vertical', command=canvas.yview)
        body = ttk.Frame(canvas)
        body.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.create_window((0, 0), window=body, anchor='nw')
        canvas.configure(yscrollcommand=scrollbar.set)
        def wheel_scroll(event):
            delta = -1 if event.delta > 0 else 1
            canvas.yview_scroll(delta * 3, 'units')
            return 'break'
        def bind_wheel(widget):
            widget.bind('<MouseWheel>', wheel_scroll, add='+')
            for child in widget.winfo_children():
                bind_wheel(child)
        window.after_idle(lambda: bind_wheel(body) if window.winfo_exists() else None)
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
            self.push_undo()
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
            row['status'] = 'Manual metadata edits ready to save'
            self.refresh(path)
            self.show_details()
            window.destroy()
            self.tree.selection_set(path)
            self.write()
        ttk.Button(body, text='Save Changes', style='Accent.TButton', command=stage).pack(anchor='w', pady=12)

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
        self.add_paths(filedialog.askopenfilenames(filetypes=[('Audio files', '*.mp3 *.flac *.m4a *.aiff *.aif *.wav'), ('All files', '*.*')]))

    def add_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.add_paths([folder])

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
        """Edit text tags directly in the table; never open a separate dialog."""
        if self.tree.identify_region(event.x, event.y) != 'cell':
            return
        path = self.tree.identify_row(event.y)
        column = self.tree.identify_column(event.x)
        if not path or not column.startswith('#'):
            return
        index = int(column[1:]) - 1
        if not 0 <= index < len(self.visible_columns):
            return
        field = self.visible_columns[index]
        if field not in EDITABLE_FIELDS:
            return
        self._start_inline_edit(path, field)

    def _start_inline_edit(self, path, field):
        if self.inline_editor is not None:
            self.inline_editor.destroy()
            self.inline_editor = None
        try:
            column_number = self.visible_columns.index(field) + 1
        except ValueError:
            return
        bbox = self.tree.bbox(path, f'#{column_number}')
        if not bbox:
            self.tree.see(path)
            bbox = self.tree.bbox(path, f'#{column_number}')
        if not bbox:
            return
        x, y, width, height = bbox
        original = str(display_value(self.rows[path], field))
        value = tk.StringVar(value=original)
        editor = ttk.Entry(self.tree, textvariable=value, font=('Helvetica', 14))
        self.inline_editor = editor
        # Extend a narrow cell into available empty space so long titles are legible.
        available = max(width, self.tree.winfo_width() - x - 8)
        editor.place(x=x, y=y, width=min(max(width, min(available, 580)), available), height=max(height, 28))
        editor.focus_set()
        editor.icursor(tk.END)
        finished = [False]

        def finish(save, next_field=False):
            if finished[0]:
                return
            finished[0] = True
            new_text = value.get().strip()
            if self.inline_editor is editor:
                self.inline_editor = None
            editor.destroy()
            if save:
                row = self.rows[path]
                self.push_undo()
                if new_text == str(row.get(field,'')):
                    row.setdefault('pending_tags',{}).pop(field,None)
                else:
                    row.setdefault('pending_tags', {})[field] = new_text
                if field in ('title', 'artist'):
                    row['suggested_' + field] = new_text
                    self.save_names.set(True)
                row['status'] = f'Edited {field} — pending save'
                self.refresh(path)
                self.tree.selection_set(path)
                self.show_details()
            if next_field and save:
                following = [c for c in self.visible_columns if c in EDITABLE_FIELDS]
                if field in following:
                    self.root.after_idle(lambda: self._start_inline_edit(path, following[(following.index(field)+1)%len(following)]))

        editor.bind('<Return>', lambda e: (finish(True), 'break')[1])
        editor.bind('<Escape>', lambda e: (finish(False), 'break')[1])
        editor.bind('<Tab>', lambda e: (finish(True, True), 'break')[1])
        # Do not save silently when clicking elsewhere: preserve edits on focus-out.
        editor.bind('<FocusOut>', lambda e: finish(True))

    def add_paths(self, paths):
        errors = 0
        expanded = []
        for incoming in paths:
            incoming = Path(incoming).expanduser()
            if incoming.is_dir():
                expanded.extend(p for p in incoming.rglob('*') if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS)
            elif incoming.is_file() and incoming.suffix.lower() in AUDIO_EXTENSIONS:
                expanded.append(incoming)
        newly_added = []
        for path in expanded:
            path = str(path.resolve())
            if path in self.rows:
                continue
            try:
                track = read_any_track(path)
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
        self.status.config(text=f'{len(self.rows)} tracks loaded. {errors} unreadable files skipped.')
        self.persist_library()
        self.update_sidebar_counts()
        if newly_added:
            if self.auto_lookup.get():
                # Import lookup uses the saved field preferences and still requires
                # confirmation before writing to an audio file.
                self.run_job('lookup_analyze' if self.auto_bpm.get() else 'lookup', newly_added,
                             options=self._saved_lookup_options())
            elif self.auto_bpm.get():
                self.run_job('analyze', newly_added)

    def refresh(self, path):
        r = self.rows[path]
        values = tuple(('●  ' if c=='title' and (r.get('pending_tags') or r.get('pending_custom')) else '') + str(display_value(r,c)) for c in COLUMN_LABELS)
        if self.tree.exists(path):
            self.tree.item(path, values=values)
        else:
            self.tree.insert('', 'end', iid=path, values=values,
                             tags=('even' if len(self.rows) % 2 == 0 else 'odd',))

    def selected(self):
        return list(self.tree.selection())

    def _saved_lookup_options(self):
        stored = self.extra_settings.get('lookup_dialog', {})
        return {'fields': list(stored.get('fields', ['year', 'genre', 'subgenre', 'art'])),
                'mode': stored.get('mode', 'missing')}

    def import_automation_settings(self):
        win = tk.Toplevel(self.root)
        win.title('Import & Automation')
        win.geometry('540x290')
        win.configure(bg=COLORS['bg'])
        body = ttk.Frame(win, padding=20)
        body.pack(fill='both', expand=True)
        ttk.Label(body, text='Import & Automation', style='Brand.TLabel').pack(anchor='w', pady=(0, 12))
        ttk.Label(body, text='Every import reads existing tags and checks for duplicate paths.').pack(anchor='w')
        analyze = tk.BooleanVar(value=self.auto_bpm.get())
        lookup = tk.BooleanVar(value=self.auto_lookup.get())
        ttk.Checkbutton(body, text='Analyze BPM and Camelot key on import', variable=analyze).pack(anchor='w', pady=(15, 5))
        ttk.Checkbutton(body, text='Find tags and artwork on import', variable=lookup).pack(anchor='w', pady=5)
        ttk.Label(body, text='Off by default. Genre saves automatically; other tags need approval.').pack(anchor='w', pady=10)
        def save():
            self.auto_bpm.set(analyze.get())
            self.auto_lookup.set(lookup.get())
            self.extra_settings['import_analyze'] = analyze.get()
            self.extra_settings['import_lookup'] = lookup.get()
            self.save_preferences()
            win.destroy()
        ttk.Button(body, text='Save Settings', command=save, style='Accent.TButton').pack(anchor='e', pady=8)

    def run_job(self, kind, paths=None, options=None):
        paths = self.selected() if paths is None else list(paths)
        if not paths:
            return messagebox.showinfo(APP_NAME, 'Select one or more tracks first.')
        if kind not in ('lookup', 'analyze', 'lookup_analyze', 'analyze_metadata'):
            return messagebox.showwarning(APP_NAME, 'Unsupported queued operation')
        job_id = self.queue_engine.add(kind, paths)
        if kind in ('lookup', 'lookup_analyze', 'analyze_metadata'):
            self._lookup_job_options[job_id] = dict(options or self._saved_lookup_options())
        self.status.configure(text=f'{self._task_name(kind)} queued for {len(paths)} tracks (task #{job_id}).')

    def lookup(self):
        paths = self.selected()
        if not paths:
            return messagebox.showinfo(APP_NAME, 'Select one or more tracks first.')
        win = tk.Toplevel(self.root)
        win.title('Find Tags & Art — Search Options')
        win.geometry('540x610')
        win.configure(bg=COLORS['bg'])
        win.transient(self.root)
        win.grab_set()
        body = ttk.Frame(win, padding=20)
        body.pack(fill='both', expand=True)
        ttk.Label(body, text='Find Tags & Art', style='Brand.TLabel').pack(anchor='w')
        ttk.Label(body, text=f'{len(paths)} selected track(s) • choose what to find').pack(anchor='w', pady=(2, 14))
        defaults = self._saved_lookup_options()
        fields = [('year', 'Original release year'), ('genre', 'Genre'),
                  ('subgenre', 'Subgenre (Composer tag)'), ('bpm_tag', 'BPM (audio analysis)'),
                  ('key', 'Musical key (Camelot, audio analysis)'), ('art', 'Album artwork')]
        flags = {}
        for key, label in fields:
            flags[key] = tk.BooleanVar(value=key in defaults['fields'])
            ttk.Checkbutton(body, text=label, variable=flags[key]).pack(anchor='w', pady=5)
        ttk.Label(body, text='Search scope', style='Brand.TLabel').pack(anchor='w', pady=(15, 6))
        mode = tk.StringVar(value=defaults['mode'])
        for key, label in [('missing', 'Find missing fields only'),
                           ('review', 'Find missing or potentially incorrect fields'),
                           ('all', 'Compare all selected fields')]:
            ttk.Radiobutton(body, text=label, value=key, variable=mode).pack(anchor='w', pady=3)
        ttk.Label(body, text='Genres save automatically; other fields require approval.').pack(anchor='w', pady=(12, 8))
        buttons = ttk.Frame(body)
        buttons.pack(side='bottom', fill='x', pady=(12, 0))
        ttk.Button(buttons, text='Cancel', command=win.destroy).pack(side='right', padx=(8, 0))
        def start():
            selected_fields = [k for k, flag in flags.items() if flag.get()]
            if not selected_fields:
                return messagebox.showwarning('Find Tags & Art', 'Choose at least one field.', parent=win)
            options = {'fields': selected_fields, 'mode': mode.get()}
            self.extra_settings['lookup_dialog'] = options
            self.save_preferences()
            win.destroy()
            needs_analysis = bool({'bpm_tag', 'key'} & set(selected_fields))
            needs_lookup = bool({'year', 'genre', 'subgenre', 'art'} & set(selected_fields))
            kind = 'lookup_analyze' if needs_lookup and needs_analysis else ('lookup' if needs_lookup else 'analyze_metadata')
            self.run_job(kind, paths, options=options)
        ttk.Button(buttons, text='Start Lookup', command=start, style='Accent.TButton').pack(side='right')

    def analyze(self):
        self.run_job('analyze')

    def poll(self):
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == 'cover_art_result':
                    _,path,art,error=event
                    self._apply_cover_art(path,art,error)
                    continue
                if event[0] == 'waveform_ready':
                    _,path,bands,duration=event
                    self.waveform_controller.ready(path,bands,duration)
                    continue
                if event[0] == 'queue_progress':
                    _,job_id,index,total=event
                    self.status.configure(text=f'Task #{job_id}: {index}/{total} processed')
                    continue
                if event[0] == 'queue_skip':
                    _,job_id,path,reason=event
                    if path in self.rows:
                        self.rows[path]['status']='Task skipped: '+reason[:65]
                        self.refresh(path)
                    continue
                if event[0] == 'queue_done':
                    _,job_id,kind,cancelled=event
                    self.status.configure(text=f'Task #{job_id} {"cancelled" if cancelled else "completed"}.')
                    continue
                if event[0] == 'queue_result':
                    _,job_id,kind,path,result=event
                    if any(j['id']==job_id and j['state']=='cancelled' for j in self.queue_engine.snapshot()):
                        continue
                    event=('result',kind,path,result)
                if event[0] == 'key_result':
                    _,path,value=event
                    if path in self.rows:
                        if not value.startswith('Error:'):
                            self.rows[path].setdefault('pending_tags',{})['key']=value
                            self.rows[path]['status']='Key estimated — pending save'
                        else:self.rows[path]['status']=value
                        self.refresh(path)
                    continue
                if event[0] == 'progress':
                    self.update_progress(*event[1:])
                    continue
                if event[0] == 'done':
                    self.busy = False
                    self.close_progress()
                    self.status.config(text=f'{event[1].title()} finished: {event[2]} tracks.')
                    continue
                _, kind, path, result = event
                r = self.rows.get(path)
                if not r:
                    continue
                if result.get('error') and kind not in ('lookup', 'lookup_analyze'):
                    if kind == 'lookup':
                        r['lookup_debug'] = result.get('lookup_debug', {})
                        r['lookup_warnings'] = result.get('errors', [])
                    r['status'] = result['error'][:65]
                elif kind == 'analyze_metadata':
                    options = self._lookup_job_options.get(job_id, self._saved_lookup_options())
                    if result.get('error'):
                        r['status'] = 'Audio analysis failed: ' + str(result['error'])[:70]
                    else:
                        self._confirm_lookup_write(path, {}, result, options=options)
                        if result.get('bpm'):
                            r['bpm'] = result['bpm']
                        r['status'] = 'Audio analysis completed — reviewed'
                elif kind in ('lookup', 'lookup_analyze'):
                    # Lookup + audio analysis are proposed together. Only explicit
                    # per-track confirmation can commit to the original music file.
                    analysis = result.get('analysis', {})
                    lookup_result = result.get('lookup', result)
                    result = lookup_result
                    options = self._lookup_job_options.get(job_id, self._saved_lookup_options())
                    r['field_confidence'] = {**field_confidence(result), **analysis.get('confidence', {})}
                    r['possible_revision'] = any(0 < v < 70 for v in r['field_confidence'].values())
                    if analysis.get('bpm'):
                        r['bpm'] = analysis['bpm']
                    # Stage metadata for review; the Year/Genre/Composer columns
                    # display these values immediately, but MP3s change only on Save.
                    for field in ('year', 'genre', 'subgenre'):
                        value = result.get(field, '') if field in options['fields'] else ''
                        key = 'suggested_' + field
                        if value:
                            r[key] = value
                        else:
                            r.pop(key, None)
                    r['lookup_debug'] = result.get('lookup_debug', {})
                    r['sources'] = result.get('sources', [])
                    r['lookup_warnings'] = result.get('errors', [])
                    provider_count=len(result.get('sources',[]))
                    confidence=result.get('lookup_debug',{}).get('providers',{}).get('MusicBrainz',{}).get('confidence')
                    r['match'] = (f'{confidence}% MusicBrainz' if isinstance(confidence,(int,float)) else
                                  ('Multiple sources' if provider_count>1 else 'Review'))
                    r['status'] = 'Lookup: ' + ', '.join(result.get('sources', [])) if result.get('sources') else 'No match'
                    self._confirm_lookup_write(path, result, analysis, options=options)
                    if 'art' in options['fields'] and result.get('recording_id') and Path(path).suffix.lower() == '.mp3':
                        self._queue_artwork_preview(path, result['recording_id'])
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

    def _queue_artwork_preview(self, path, recording_id):
        def fetch():
            try:
                art = artwork_from_musicbrainz(recording_id)
                self.events.put(('cover_art_result', path, art, None))
            except Exception as exc:
                self.events.put(('cover_art_result', path, None, type(exc).__name__))
        threading.Thread(target=fetch, daemon=True).start()

    def find_cover_art_selected(self):
        paths=self.selected()
        if len(paths)!=1:
            return messagebox.showinfo('Cover Art','Select exactly one MP3 track.',parent=self.root)
        path=paths[0]
        if Path(path).suffix.lower()!='.mp3':
            return messagebox.showinfo('Cover Art','Embedded cover art currently supports MP3 only.',parent=self.root)
        r=self.rows[path]
        if not messagebox.askyesno('Find Cover Art',
                f'Search MusicBrainz and Cover Art Archive for {Path(path).name}?\n\n'
                'Artwork will not be written without another confirmation.',parent=self.root):
            return
        # Network retrieval is off the UI thread; only the main thread opens dialogs.
        def fetch():
            from metadata_sources import musicbrainz
            try:
                match=musicbrainz(r.get('artist',''),r.get('title',''))
                art=artwork_from_musicbrainz(match.get('recording_id')) if match else None
                self.events.put(('cover_art_result',path,art,None))
            except Exception as exc:
                self.events.put(('cover_art_result',path,None,type(exc).__name__))
        threading.Thread(target=fetch,daemon=True).start()
        self.status.configure(text='Searching for cover art…')

    def _apply_cover_art(self,path,art,error):
        if error or not art:
            return messagebox.showinfo('Cover Art','No usable artwork found. '+(error or ''),parent=self.root)
        if path not in self.rows:return
        if not messagebox.askyesno('Confirm cover art write',
                f'Write {len(art["data"]):,} bytes of {art["mime"]} cover art to\n{Path(path).name}?\n\n'
                'A recovery copy will be retained.',parent=self.root):
            return
        def writer(temp,changes,custom):
            write_mp3_cover_art(temp,art)
        try:
            safe_write(path,{}, {'__cover_art__':'front'},writer,read_any_track,
                       self.data_dir/'metadata_recovery',expected=self.rows[path].get('disk_fingerprint'))
            self.rows[path].update(read_any_track(path))
            self.rows[path]['status']='Cover art written in place'
            self.rows[path]['written']=True
            self.refresh(path);self.persist_library()
        except Exception as exc:
            messagebox.showerror('Cover Art Write Blocked',str(exc),parent=self.root)

    def metadata_automation_settings(self):
        win=tk.Toplevel(self.root);win.title('Metadata Automation');win.geometry('510x440')
        body=ttk.Frame(win,padding=18);body.pack(fill='both',expand=True)
        ttk.Label(body,text='Find Tags & Art — Write Preferences',style='Brand.TLabel').pack(anchor='w',pady=(0,12))
        ttk.Label(body,text='Each lookup always asks before changing the audio file.').pack(anchor='w')
        current=self.extra_settings.get('metadata_automation',{})
        enabled=set(current.get('fields',['year','genre','bpm_tag','key']))
        flags={}
        for field,label in [('year','Original release year'),('genre','Genre'),('subgenre','Subgenre → Composer'),('bpm_tag','Analyzed BPM'),('key','Camelot key')]:
            v=tk.BooleanVar(value=field in enabled);flags[field]=v
            ttk.Checkbutton(body,text=label,variable=v).pack(anchor='w',pady=5)
        replace=tk.BooleanVar(value=bool(current.get('replace_existing',False)))
        ttk.Checkbutton(body,text='Propose replacement of already-filled fields',variable=replace).pack(anchor='w',pady=10)
        ttk.Label(body,text='Artist and Title are never overwritten by automatic lookup.').pack(anchor='w')
        def save():
            self.extra_settings['metadata_automation']={'fields':[k for k,v in flags.items() if v.get()],
                                                          'replace_existing':replace.get()}
            self.save_preferences();win.destroy()
        ttk.Button(body,text='Save Preferences',command=save,style='Accent.TButton').pack(anchor='e',pady=18)

    def _confirm_lookup_write(self, path, lookup, analysis, options=None):
        """Automatically save lookup genre; ask before writing other fields."""
        from genre_fallback import genre_decision
        r = self.rows.get(path)
        if not r:
            return
        options = options or self._saved_lookup_options()
        enabled = [field for field in options['fields'] if field != 'art']
        changes = metadata_proposal(r, lookup, analysis, fields=enabled,
                                    replace_existing=(options['mode'] != 'missing'))
        # Genre is deliberately exempt from the 'missing only' search scope:
        # a database result updates an existing genre; an artist guess never does.
        genre_source = 'none'
        if 'genre' in enabled:
            artist = r.get('suggested_artist') or r.get('artist') or ''
            chosen, genre_source = genre_decision(r.get('genre'), lookup.get('genre'), artist)
            if chosen and chosen != (r.get('genre') or ''):
                changes['genre'] = chosen
            else:
                changes.pop('genre', None)
        genre_change = changes.pop('genre', None)
        if genre_change:
            try:
                safe_write(path, {'genre': genre_change}, {}, write_any_tags, read_any_track,
                           self.data_dir / 'metadata_recovery', expected=r.get('disk_fingerprint'))
                r.update(read_any_track(path))
                r['disk_fingerprint'] = fingerprint(path)
                r.pop('suggested_genre', None)
                r['genre_lookup_source'] = genre_source
                r['status'] = 'Genre saved automatically (' + genre_source + ')'
                r['written'] = True
                self.undo_stack.clear(); self.redo_stack.clear()
                self.persist_library()
            except Exception as exc:
                r['status'] = 'Genre write blocked: ' + str(exc)[:100]
                messagebox.showerror('Genre write blocked', str(exc), parent=self.root)
                return
        if not changes:
            if not genre_change:
                r['status'] = 'Lookup complete — genre unchanged'
            return
        lines = '\n'.join(f'{COLUMN_LABELS.get(k,k)}: {r.get(k) or "(blank)"} → {v}'
                          for k,v in changes.items())
        if not messagebox.askyesno('Confirm other metadata changes',
                f'{Path(path).name}\n\n{lines}\n\n'
                'Write these non-genre fields to the audio file?\n'
                'The original is backed up and can be restored from Write History.',
                parent=self.root):
            r['status'] = 'Genre handled; other changes declined'
            return
        try:
            safe_write(path, changes, {}, write_any_tags, read_any_track,
                       self.data_dir / 'metadata_recovery', expected=r.get('disk_fingerprint'))
            r.update(read_any_track(path))
            r['disk_fingerprint'] = fingerprint(path)
            for field in ('year','subgenre'):
                r.pop('suggested_'+field,None)
            r['status'] = 'Metadata written in place'
            r['written'] = True
            self.undo_stack.clear(); self.redo_stack.clear()
            self.persist_library()
        except Exception as exc:
            r['status'] = 'Safe write blocked: '+str(exc)[:100]
            messagebox.showerror('Metadata write blocked',str(exc),parent=self.root)

    def show_details(self, _event=None):
        selected = self.selected()
        self.details.delete('1.0', 'end')
        if hasattr(self,'selection_status'):
            self.selection_status.configure(text=f'{len(selected)} of {len(self.tree.get_children())} visible tracks selected')
        if selected:
            r = self.rows[selected[0]]
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
                f'Write pending metadata to {len(ready)} music file(s)?\n\n'
                'Each file will be backed up and verified before replacement.\n'
                'Writes can be restored from Metadata Write History.\n'
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
            for protected in self.protected_fields:
                if protected in changes and r.get(protected) and changes[protected] != r[protected]:
                    if not messagebox.askyesno(APP_NAME,
                        f'Protected field {COLUMN_LABELS.get(protected,protected)} on {Path(path).name} already has a value. Overwrite?',
                        parent=self.root):
                        changes.pop(protected,None)
            try:
                safe_write(path, changes, r.get('pending_custom', {}),
                           write_any_tags, read_any_track, self.data_dir / 'metadata_recovery',
                           expected=r.get('disk_fingerprint'))
                for key in ('pending_tags', 'pending_custom', 'suggested_year', 'suggested_genre', 'suggested_subgenre', 'suggested_artist', 'suggested_title'):
                    r.pop(key, None)
                r.update(read_any_track(path))
                r['disk_fingerprint'] = fingerprint(path)
                r['status'] = 'Tags written in place'
                success += 1
            except Exception as exc:
                r['status'] = f'Write failed: {exc}'
            self.refresh(path)
        self.show_details()
        self.status.config(text=f'Tags written to {success}/{len(ready)} files.')
        if success:
            self.undo_stack.clear()
            self.redo_stack.clear()
        self.persist_library()

    def metadata_write_history_dialog(self):
        """Show durable recovery copies; restore only if track has not changed."""
        db = self.data_dir / 'metadata_recovery' / 'metadata_writes.sqlite3'
        entries = metadata_history(db)
        win = tk.Toplevel(self.root)
        win.title('Metadata Write History / Restore')
        win.geometry('850x450')
        cols = ('date', 'track', 'state')
        table = ttk.Treeview(win, columns=cols, show='headings', selectmode='browse')
        for key, label, width in [('date','Written UTC',230), ('track','File',460), ('state','State',120)]:
            table.heading(key, text=label)
            table.column(key, width=width)
        table.pack(fill='both', expand=True, padx=12, pady=12)
        by_id = {}
        for record in entries:
            by_id[record['id']] = record
            table.insert('', 'end', iid=record['id'], values=(record['created_utc'],
                         Path(record['path']).name, 'Restored' if record['restored_utc'] else 'Available'))
        def restore():
            chosen = table.selection()
            if not chosen: return
            record = by_id[chosen[0]]
            if not messagebox.askyesno('Restore metadata',
                f"Restore the entire original audio file from its verified recovery copy?\n\n{record['path']}\n\n"
                'This will be blocked if the file has changed since the write.', parent=win):
                return
            try:
                path = restore_write(db, record['id'])
                if path in self.rows:
                    self.rows[path].update(read_any_track(path))
                    self.rows[path]['status'] = 'Metadata restored'
                    self.refresh(path)
                self.persist_library()
                table.set(record['id'], 'state', 'Restored')
                messagebox.showinfo('Restore complete', 'Verified original audio restored.', parent=win)
            except Exception as exc:
                messagebox.showerror('Restore blocked', str(exc), parent=win)
        ttk.Button(win, text='Restore Selected Write', command=restore).pack(pady=(0,12))

    def load_preferences(self):
        try:
            data=json.loads(self.preferences_path.read_text(encoding='utf-8'))
        except (OSError,ValueError):data={}
        self.help_enabled.set(bool(data.get('help',False)))
        self.genre_groups=data.get('genre_groups',{})
        self.saved_views=data.get('saved_views',{})
        self.protected_fields=set(data.get('protected_fields',['publisher']))
        self.serato_options={**SERATO_DEFAULTS, **data.get('serato',{})}
        self.extra_settings=data.get('extra_settings',{})
        self.advanced_filter=data.get('advanced_filter',{})
        self.shortcut_settings=data.get('shortcuts',{})

    def save_preferences(self):
        try:
            self.preferences_path.parent.mkdir(parents=True,exist_ok=True)
            self.preferences_path.write_text(json.dumps({'help':self.help_enabled.get(),
                'genre_groups':self.genre_groups,'saved_views':self.saved_views,
                'protected_fields':sorted(self.protected_fields), 'serato':self.serato_options,
                'extra_settings':self.extra_settings,'advanced_filter':self.advanced_filter,
                'shortcuts':self.shortcut_settings},indent=2),encoding='utf-8')
        except OSError as exc:messagebox.showwarning(APP_NAME,str(exc))

    def toggle_help(self):
        self.help_enabled.set(not self.help_enabled.get())
        self.help_button.configure(bg=COLORS['accent'] if self.help_enabled.get() else COLORS['raised'],
            fg=COLORS['bg'] if self.help_enabled.get() else COLORS['text'])
        self.save_preferences()

    def install_help(self):
        explanations={'Add Music':'Import individual MP3 files.','Add Folder':'Import MP3s from a folder.',
            'Lookup Metadata':'Search MusicBrainz, Last.fm, Discogs and optional Spotify.',
            'Analyze BPM':'Analyze BPM for selected tracks.','Save Changes':'Write pending edits to original MP3s.',
            'More Actions':'Genre Cleanup, duplicates, keys and other tools.'}
        for name,widget in self.toolbar_buttons.items():
            widget.bind('<Enter>',lambda e,n=name:self.help_hover(e,explanations[n]))
            widget.bind('<Leave>',self.help_leave)

    def help_hover(self,event,description):
        if not self.help_enabled.get():return
        self.help_leave()
        widget=event.widget
        def show():
            if not self.help_enabled.get():return
            tip=tk.Toplevel(self.root)
            tip.overrideredirect(True)
            tip.configure(bg=COLORS['accent'])
            tip.geometry(f'+{widget.winfo_rootx()}+{widget.winfo_rooty()+widget.winfo_height()+7}')
            tk.Label(tip,text=description,bg=COLORS['panel'],fg=COLORS['text'],
                padx=12,pady=9,font=('Helvetica',12)).pack(padx=1,pady=1)
            self._tooltip=tip
        self._tooltip_after=self.root.after(500,show)

    def help_leave(self,event=None):
        if self._tooltip_after:
            self.root.after_cancel(self._tooltip_after)
            self._tooltip_after=None
        if self._tooltip and self._tooltip.winfo_exists():self._tooltip.destroy()
        self._tooltip=None

    def push_undo(self):
        self.undo_stack.append({p:(copy.deepcopy(r.get('pending_tags',{})),
            copy.deepcopy(r.get('pending_custom',{}))) for p,r in self.rows.items()})
        if len(self.undo_stack)>40:self.undo_stack.pop(0)
        self.redo_stack.clear()

    def restore_edit_state(self,state):
        for p,(tags,custom) in state.items():
            if p in self.rows:
                self.rows[p]['pending_tags']=copy.deepcopy(tags)
                self.rows[p]['pending_custom']=copy.deepcopy(custom)
                self.refresh(p)
        self.show_details()

    def undo(self,event=None):
        if isinstance(self.root.focus_get(),(tk.Entry,ttk.Entry,tk.Text)):return
        if self.undo_stack:
            self.redo_stack.append({p:(copy.deepcopy(r.get('pending_tags',{})),
                copy.deepcopy(r.get('pending_custom',{}))) for p,r in self.rows.items()})
            self.restore_edit_state(self.undo_stack.pop())
        return 'break'

    def redo(self,event=None):
        if isinstance(self.root.focus_get(),(tk.Entry,ttk.Entry,tk.Text)):return
        if self.redo_stack:
            self.undo_stack.append({p:(copy.deepcopy(r.get('pending_tags',{})),
                copy.deepcopy(r.get('pending_custom',{}))) for p,r in self.rows.items()})
            self.restore_edit_state(self.redo_stack.pop())
        return 'break'

    def show_progress(self,kind,total):
        win=tk.Toplevel(self.root)
        self.progress_window=win
        win.title('Processing Music')
        win.configure(bg=COLORS['panel'])
        win.geometry('440x220')
        win.resizable(False,False)
        win.transient(self.root)
        win.grab_set()
        self.root.update_idletasks()
        x=self.root.winfo_rootx()+(self.root.winfo_width()-440)//2
        y=self.root.winfo_rooty()+(self.root.winfo_height()-220)//2
        win.geometry(f'+{max(0,x)}+{max(0,y)}')
        tk.Label(win,text='Processing '+kind.title(),bg=COLORS['panel'],fg=COLORS['accent'],
            font=('Helvetica',18,'bold')).pack(pady=(23,10))
        self.progress_text=tk.StringVar(value=f'0 of {total} tracks')
        ttk.Label(win,textvariable=self.progress_text).pack(pady=6)
        self.progress_bar=ttk.Progressbar(win,maximum=max(total,1),length=365,mode='determinate')
        self.progress_bar.pack(pady=8)
        ttk.Label(win,text='Click × to cancel remaining tracks safely.').pack(pady=7)
        def cancel():
            self.cancel_requested.set()
            self.progress_text.set('Cancel requested — finishing current track…')
        win.protocol('WM_DELETE_WINDOW',cancel)
        tk.Button(win,text='×',command=cancel,bg=COLORS['raised'],fg=COLORS['text'],
            relief='flat',font=('Helvetica',15,'bold')).place(x=402,y=8,width=29,height=29)

    def update_progress(self,index,total,name):
        if self.progress_window and self.progress_window.winfo_exists():
            self.progress_bar.configure(value=index)
            self.progress_text.set(f'{index} of {total} tracks  •  {name[:45]}')

    def close_progress(self):
        win=self.progress_window
        self.progress_window=None
        if win and win.winfo_exists():
            try:win.grab_release()
            except tk.TclError:pass
            win.destroy()

    def smart_filters(self):
        win=tk.Toplevel(self.root);win.title('Smart Filters');win.geometry('420x330')
        win.configure(bg=COLORS['bg'])
        ttk.Label(win,text='Saved Filter Views',style='Brand.TLabel').pack(pady=12)
        name=tk.StringVar()
        ttk.Entry(win,textvariable=name).pack(fill='x',padx=15)
        box=tk.Listbox(win,bg=COLORS['panel'],fg=COLORS['text'])
        box.pack(fill='both',expand=True,padx=15,pady=10)
        def redraw():
            box.delete(0,'end')
            for k in sorted(self.saved_views):box.insert('end',k)
        def save():
            if name.get().strip():
                self.saved_views[name.get().strip()]=dict(self.filters)
                self.save_preferences();redraw()
        def load():
            if box.curselection():
                self.filters=dict(self.saved_views[box.get(box.curselection()[0])]);self.apply_filters();win.destroy()
        def clear():self.filters.clear();self.apply_filters()
        bar=ttk.Frame(win);bar.pack(pady=8)
        for title,fn in [('Save View',save),('Load View',load),('Clear Filters',clear)]:
            ttk.Button(bar,text=title,command=fn).pack(side='left',padx=3)
        redraw()

    def find_duplicates(self):
        groups={}
        for p,r in self.rows.items():
            key=(re.sub(r'\W+','',r.get('artist','').casefold()),
                re.sub(r'\W+','',r.get('title','').casefold()))
            if all(key):groups.setdefault(key,[]).append(p)
        matches=[v for v in groups.values() if len(v)>1]
        win=tk.Toplevel(self.root);win.title('Possible Duplicates — no files deleted')
        win.geometry('780x470')
        txt=tk.Text(win,bg=COLORS['panel'],fg=COLORS['text'],font=('Menlo',11))
        txt.pack(fill='both',expand=True)
        for group in matches:
            txt.insert('end','POSSIBLE DUPLICATES:\n'+'\n'.join(group)+'\n\n')
        if not matches:txt.insert('end','No matching artist/title pairs found in loaded tracks.')
        txt.configure(state='disabled')

    def detect_keys(self):
        paths=self.selected()
        if not paths:return messagebox.showinfo(APP_NAME,'Select tracks first.')
        if self.busy:return
        self.busy=True;self.cancel_requested.clear();self.show_progress('key detection',len(paths))
        def worker():
            for i,path in enumerate(paths):
                if self.cancel_requested.is_set():break
                self.events.put(('progress',i,len(paths),Path(path).name))
                try:
                    import librosa,numpy as np
                    y,sr=librosa.load(path,sr=11025,mono=True)
                    chroma=librosa.feature.chroma_stft(y=y,sr=sr)
                    profile=np.mean(chroma,axis=1)
                    major=np.array([6.35,2.23,3.48,2.33,4.38,4.09,2.52,5.19,2.39,3.66,2.29,2.88])
                    minor=np.array([6.33,2.68,3.52,5.38,2.60,3.53,2.54,4.75,3.98,2.69,3.34,3.17])
                    candidates=[(float(np.corrcoef(profile,np.roll(t,i))[0,1]),i,mode)
                        for mode,t in [('major',major),('minor',minor)] for i in range(12)]
                    score,note,mode=max(candidates)
                    names=['C','C#','D','D#','E','F','F#','G','G#','A','A#','B']
                    camelot_major=['8B','3B','10B','5B','12B','7B','2B','9B','4B','11B','6B','1B']
                    camelot_minor=['5A','12A','7A','2A','9A','4A','11A','6A','1A','8A','3A','10A']
                    value=f'{names[note]} {mode} ({(camelot_major if mode=="major" else camelot_minor)[note]})'
                    self.events.put(('key_result',path,value))
                except Exception as exc:self.events.put(('key_result',path,'Error: '+str(exc)[:70]))
            self.events.put(('done','key detection',len(paths)))
        threading.Thread(target=worker,daemon=True).start()

    def genre_cleanup(self):
        """Open the integrated Genre Cleanup workspace, never the legacy popup."""
        from genre_workspace import open_genre_workspace
        open_genre_workspace(self)

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