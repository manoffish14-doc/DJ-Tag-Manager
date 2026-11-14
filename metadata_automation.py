"""Provider proposals, harmonic analysis, and explicit safe-write decisions.

No network or audio file modification happens on import. Provider proposals never
silently overwrite identity tags, and each lookup is confirmed in the GUI.
"""
from __future__ import annotations
import re
from dataclasses import dataclass

CAMELOT_MAJOR = ('8B','3B','10B','5B','12B','7B','2B','9B','4B','11B','6B','1B')
CAMELOT_MINOR = ('5A','12A','7A','2A','9A','4A','11A','6A','1A','8A','3A','10A')
NOTES = ('C','C#','D','D#','E','F','F#','G','G#','A','A#','B')


def camelot(note, mode):
    key = re.sub(r'\s+', '', str(note)).upper().replace('♯','#').replace('♭','B')
    if key not in NOTES:
        raise ValueError('Unknown musical note')
    mode = str(mode).lower()
    if mode not in ('major', 'minor'):
        raise ValueError('Mode must be major or minor')
    return (CAMELOT_MAJOR if mode == 'major' else CAMELOT_MINOR)[NOTES.index(key)]


def analyze_audio(path, *, loader=None):
    """Return BPM, Camelot key and confidence from the same audio decode.

    Correlation is a heuristic, not a ground-truth musical key classifier.
    """
    import librosa
    import numpy as np
    if loader is None:
        loader = librosa.load
    y, sr = loader(path, sr=11025, mono=True)
    if len(y) < sr:
        raise ValueError('Not enough audio to analyze')
    tempo, _ = librosa.beat.beat_track(y=y, sr=sr, trim=False)
    from app import normalize_analyzed_bpm
    bpm = normalize_analyzed_bpm(float(np.asarray(tempo).reshape(-1)[0]))
    chroma = librosa.feature.chroma_stft(y=y, sr=sr)
    profile = np.asarray(chroma).mean(axis=1)
    if not np.isfinite(profile).all() or np.std(profile) < 1e-8:
        raise ValueError('Audio has no reliable harmonic profile')
    major = np.array([6.35,2.23,3.48,2.33,4.38,4.09,2.52,5.19,2.39,3.66,2.29,2.88])
    minor = np.array([6.33,2.68,3.52,5.38,2.60,3.53,2.54,4.75,3.98,2.69,3.34,3.17])
    candidates = []
    for mode, template in (('major',major),('minor',minor)):
        for idx in range(12):
            score = float(np.corrcoef(profile, np.roll(template,idx))[0,1])
            if np.isfinite(score):
                candidates.append((score,idx,mode))
    if not candidates:
        raise ValueError('Could not estimate key')
    score,idx,mode = max(candidates)
    return {'bpm': bpm, 'bpm_tag': str(bpm), 'key': camelot(NOTES[idx],mode),
            'key_label': f'{NOTES[idx]} {mode}',
            'confidence': {'bpm_tag': 55, 'key': max(0,min(85,int((score+1)*40)))}}


def field_confidence(result):
    """Conservative per-field estimates, not a probability of correctness."""
    sources = result.get('sources') or []
    providers = result.get('lookup_debug',{}).get('providers',{})
    mb = providers.get('MusicBrainz',{}).get('confidence')
    match = max(0,min(100,int(mb))) if isinstance(mb,(int,float)) else 55
    multi = len(sources) > 1
    return {
        'year': min(90, (match if mb is not None else 55) + (5 if multi else 0)) if result.get('year') else 0,
        'genre': min(85, 50 + 10 * (len(sources)-1)) if result.get('genre') else 0,
        'subgenre': min(75, 45 + 10 * (len(sources)-1)) if result.get('subgenre') else 0,
    }


def proposal(existing, lookup, analysis=None, *, fields=None, replace_existing=False):
    """Only explicitly enabled fields; protect artist/title and existing values.

    Subgenre uses Composer for MP3 compatibility with the existing UI; the
    caller must opt into that mapping explicitly.
    """
    allowed = set(fields or ('year','genre','subgenre','bpm_tag','key'))
    result = {}
    mapping = {'year':'year','genre':'genre','subgenre':'composer','bpm_tag':'bpm_tag','key':'key'}
    data = {**(lookup or {}), **(analysis or {})}
    for src,dst in mapping.items():
        value = data.get(src)
        if src not in allowed or value is None or str(value).strip() == '':
            continue
        if src == 'subgenre' and not (lookup or {}).get('subgenre'):
            continue
        current = str(existing.get(dst) or '').strip()
        if current and not replace_existing:
            continue
        if current != str(value):
            result[dst] = str(value)
    return result


def identify_from_filename(path):
    """Optional non-network fallback; never overwrite existing artist/title."""
    from pathlib import Path
    stem = Path(path).stem
    if ' - ' not in stem:
        return {}
    artist,title = (s.strip() for s in stem.split(' - ',1))
    return {'artist':artist,'title':title} if artist and title else {}


def artwork_from_musicbrainz(recording_id, *, get=None):
    """Find optional release cover art; caller decides whether to write it.

    MusicBrainz release relation is fetched separately from cover-art bytes.
    Only JPEG/PNG and <= 8 MiB are accepted.
    """
    if not re.fullmatch(r'[0-9a-fA-F-]{36}',recording_id or ''):
        return None
    import requests
    getter = get or requests.get
    response = getter('https://musicbrainz.org/ws/2/recording/'+recording_id,
                      params={'inc':'releases','fmt':'json'},timeout=12,
                      headers={'User-Agent':'DJTagManager/3.1 (personal music metadata)'})
    response.raise_for_status()
    for release in response.json().get('releases',[])[:5]:
        release_id = release.get('id','')
        if not re.fullmatch(r'[0-9a-fA-F-]{36}',release_id):
            continue
        try:
            art = getter('https://coverartarchive.org/release/'+release_id+'/front-250',timeout=12,
                         headers={'User-Agent':'DJTagManager/3.1 (personal music metadata)'})
            art.raise_for_status()
            content = art.content
            mime = art.headers.get('Content-Type','').split(';')[0].lower()
            if mime in ('image/jpeg','image/png') and len(content) <= 8*1024*1024:
                return {'mime':mime,'data':content,'release_id':release_id}
        except requests.RequestException:
            continue
    return None


def write_mp3_cover_art(path, artwork):
    """Apply a validated JPEG/PNG front cover on a temporary MP3 copy only.

    Must be invoked through metadata_safety.safe_write, never on the original.
    """
    from mutagen.id3 import ID3, ID3NoHeaderError, APIC
    if not str(path).lower().endswith('.mp3'):
        raise ValueError('Embedded artwork is currently supported only for MP3')
    if not artwork or artwork.get('mime') not in ('image/jpeg','image/png'):
        raise ValueError('Unsupported artwork MIME type')
    data=artwork.get('data',b'')
    if not data or len(data)>8*1024*1024:
        raise ValueError('Artwork size outside safe limits')
    try: tags=ID3(path)
    except ID3NoHeaderError:tags=ID3()
    # Preserve existing cover art: replace only the front-cover frame.
    for frame in list(tags.getall('APIC')):
        if getattr(frame,'type',None)==3:
            tags.delall('APIC:'+frame.desc)
    tags.add(APIC(encoding=3,mime=artwork['mime'],type=3,desc='Front cover',data=data))
    tags.save(path,v2_version=3)
