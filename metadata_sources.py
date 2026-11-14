"""Independent metadata providers. Only high-confidence exact-ish matches contribute."""
import re
import time
from difflib import SequenceMatcher
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

UA = 'DJTagManager/3.1 (music library metadata lookup; contact: https://github.com/manoffish14-doc/DJ-Tag-Manager)'
HEADERS = {'User-Agent': UA}

def norm(s):
    s = re.sub(r'\([^)]*(official|video|lyrics|audio)[^)]*\)', '', s or '', flags=re.I)
    s = re.sub(r'\b(feat\.?|ft\.?)\b.*$', '', s, flags=re.I)
    return re.sub(r'[^a-z0-9]+', '', s.casefold())

def similar(a,b):
    a,b=norm(a),norm(b)
    return bool(a and b) and (a==b or SequenceMatcher(None,a,b).ratio()>=.88)

def clean_query(artist, title):
    """Normalize video-derived metadata for searching; never alter the source tags."""
    artist = (artist or '').strip()
    title = (title or '').strip()
    video_title = bool(re.search(r'\b(?:official|lyrics|lyric video|music video)\b', title, re.I))
    # Titles downloaded from video sites frequently start with the credited artist.
    title = re.sub(r'\s*\([^)]*\b(?:official|music video|lyric|lyrics|audio|visualizer|video)\b[^)]*\)', '', title, flags=re.I)
    title = re.sub(r'\s*\[[^]]*\b(?:official|lyric|lyrics|audio|video)\b[^]]*\]', '', title, flags=re.I)
    artist = re.split(r'\s+(?:ft\.?|feat\.?|featuring)\s+', artist, maxsplit=1, flags=re.I)[0].strip()
    # The leading artist may be embedded in the title, even if the artist tag is an uploader.
    if ' - ' in title:
        lead, remainder = title.split(' - ', 1)
        if not artist or similar(lead, artist) or video_title:
            artist, title = lead.strip(), remainder.strip()
    title = re.sub(r'\s+(?:ft\.?|feat\.?|featuring)\s+.+$', '', title, flags=re.I)
    title = re.sub(r'\s+', ' ', title).strip(' -')
    return artist, title

_SESSION = requests.Session()
_RETRY = Retry(total=2, connect=1, read=1, status=2,
               status_forcelist=[429, 500, 502, 503, 504],
               allowed_methods=frozenset(['GET']), backoff_factor=0.8,
               respect_retry_after_header=True)
_SESSION.mount('https://', HTTPAdapter(max_retries=_RETRY))

def get(url, params=None, headers=None, auth=None):
    r=_SESSION.get(url, params=params, headers=headers or HEADERS, auth=auth, timeout=(4, 8))
    r.raise_for_status()
    return r.json()

def musicbrainz(artist, title):
    """Try strict then broad recording searches; retrieve tags beyond search results."""
    queries = [f'artist:"{artist}" AND recording:"{title}"',
               f'recording:"{title}" AND artist:{artist}',
               f'{artist} {title}']
    recs = []
    for query in queries:
        data = get('https://musicbrainz.org/ws/2/recording/',
                   {'query': query, 'fmt': 'json', 'limit': 25})
        recs = [r for r in data.get('recordings', [])
                if similar(r.get('title', ''), title) and
                (any(similar(a.get('name', ''), artist)
                     for a in r.get('artist-credit', []) if isinstance(a, dict))
                 or similar(r.get('artist-credit-phrase', ''), artist))]
        if recs:
            break
        time.sleep(1.1)  # Respect MusicBrainz request rate limits.
    if not recs:
        return None
    best = max(recs, key=lambda x: int(x.get('score') or 0))
    years = [int(r['first-release-date'][:4]) for r in recs
             if re.match(r'^\d{4}', r.get('first-release-date', ''))]
    tags = best.get('genres', []) or best.get('tags', [])
    if best.get('id'):
        try:
            time.sleep(1.1)
            details = get('https://musicbrainz.org/ws/2/recording/' + best['id'],
                          {'inc': 'genres+tags+releases', 'fmt': 'json'})
            tags = details.get('genres', []) or details.get('tags', []) or tags
            if not years:
                for release in details.get('releases', []):
                    date = release.get('date', '')
                    if re.match(r'^\d{4}', date):
                        years.append(int(date[:4]))
        except (requests.RequestException, ValueError):
            pass
    return {'source': 'MusicBrainz', 'year': min(years) if years else None,
            'tags': [x['name'] for x in sorted(tags, key=lambda t: t.get('count', 0), reverse=True)
                     if x.get('name')], 'confidence': best.get('score', 0), 'recording_id': best.get('id')}

def lastfm(artist,title,key):
    if not key:return None
    data=get('https://ws.audioscrobbler.com/2.0/', {'method':'track.getTopTags','artist':artist,'track':title,'autocorrect':1,'api_key':key,'format':'json'})
    if data.get('error'):raise ValueError(data.get('message','Last.fm error'))
    tags=data.get('toptags',{}).get('tag',[])
    if isinstance(tags, dict): tags=[tags]
    return {'source':'Last.fm','tags':[t['name'] for t in tags[:12] if t.get('name')], 'year':None}

def discogs(artist,title,token):
    if not token:return None
    data=get('https://api.discogs.com/database/search',{'q':f'{artist} {title}','type':'release','per_page':15},headers={**HEADERS,'Authorization':f'Discogs token={token}'})
    matches=[]
    for item in data.get('results',[]):
        name=item.get('title','')
        if ' - ' not in name:continue
        a,t=name.split(' - ',1)
        if similar(a,artist) and similar(t,title):matches.append(item)
    if not matches:return None
    years=[int(m['year']) for m in matches if str(m.get('year','')).isdigit() and int(m['year'])>1900]
    best=min(matches,key=lambda m:int(m.get('year') or 9999))
    return {'source':'Discogs','year':min(years) if years else None,'tags':best.get('styles',[])+best.get('genre',[])}

def spotify(artist,title,client_id,secret):
    if not client_id or not secret:return None
    r=requests.post('https://accounts.spotify.com/api/token',data={'grant_type':'client_credentials'},auth=(client_id,secret),timeout=12)
    r.raise_for_status(); token=r.json()['access_token']
    data=get('https://api.spotify.com/v1/search',{'q':f'track:{title} artist:{artist}','type':'track','limit':10,'market':'US'},headers={'Authorization':f'Bearer {token}'})
    matches=[t for t in data.get('tracks',{}).get('items',[]) if similar(t.get('name',''),title) and any(similar(a.get('name',''),artist) for a in t.get('artists',[]))]
    if not matches:return None
    years=[int(t['album']['release_date'][:4]) for t in matches if re.match(r'^\d{4}',t.get('album',{}).get('release_date',''))]
    return {'source':'Spotify','year':min(years) if years else None,'tags':[]}

# Order matters: specific labels first, broad fallbacks afterward.
GENRES={
 'R&B':['contemporary r&b','alternative r&b','new jack swing','neo soul','rhythm and blues','r&b','rnb','r&b/soul','urban contemporary','soul','funk / soul','funk/soul','funk and soul'],
 'Hip Hop':['southern hip hop','east coast hip hop','west coast hip hop','trap','drill','boom bap','hip-hop','hip hop','hip hop/rap','rap'],
 'Afrobeats':['afrobeats','afropop','afro pop','afro-fusion','afroswing'],
 'Dancehall':['dancehall','ragga'],
 'Reggae':['roots reggae','reggae','dub'],
 'House':['afro house','deep house','tech house','house'],
 'Electronic':['edm','electronic','dance music','dubstep','drum and bass'],
 'Pop':['dance pop','electropop','pop'],
 'Rock':['alternative rock','indie rock','rock'],
 'Latin':['reggaeton','latin pop','bachata','salsa','latin'],
 'Country':['country'],
 'Jazz':['jazz'],
 'Funk':['funk'],
}
GENERIC = {'seen live', 'favorites', 'favorite', 'american', 'male vocalists',
           'female vocalists', '00s', '2000s', '2010s', '90s', '80s',
           'awesome', 'love', 'music', 'audio', 'unknown', 'official video',
           'lyrics', 'video', 'youtube', 'subscribe', 'other', 'miscellaneous'}


def valid_genre(tag):
    """Reject noise, not unfamiliar but legitimate styles."""
    cleaned = re.sub(r'\s+', ' ', str(tag or '')).strip()
    lower = cleaned.casefold()
    return bool(cleaned and len(cleaned) <= 75 and lower not in GENERIC
                and not re.fullmatch(r'[0-9\W_]+', cleaned)
                and not re.fullmatch(r'(?:19|20)\d{2}s?', lower))


def classify(tags):
    """Prefer broad genres; preserve valid niche labels as a fallback."""
    usable = [str(t).strip() for t in tags if valid_genre(t)]
    for tag in usable:
        cleaned = tag.casefold()
        for broad, variants in GENRES.items():
            if cleaned == broad.casefold() or cleaned in variants:
                subgenre = tag if cleaned != broad.casefold() else ''
                return broad, subgenre
    # Never silently drop a legitimate style just because our mapping is incomplete.
    if usable:
        return usable[0], ''
    return '', ''

def lookup(artist, title, config):
    """Return per-provider, redacted diagnostics to explain missing genres."""
    original_artist, original_title = artist, title
    artist, title = clean_query(artist, title)
    debug = {'search_artist': artist, 'search_title': title,
             'original_search_artist': original_artist, 'original_search_title': original_title, 'providers': {},
             'genre_candidates': [], 'rejected_tags': [], 'genre_decision': {}}
    if not artist or not title:
        return {'error': 'Artist and title are needed for lookup.', 'lookup_debug': debug,
                'sources': [], 'errors': []}
    results, errors = [], []
    providers = [
        ('MusicBrainz', True, lambda: musicbrainz(artist, title)),
        ('Last.fm', bool(config.get('lastfm')), lambda: lastfm(artist, title, config.get('lastfm', ''))),
        ('Discogs', bool(config.get('discogs')), lambda: discogs(artist, title, config.get('discogs', ''))),
        ('Spotify', bool(config.get('spotify_id') and config.get('spotify_secret')),
         lambda: spotify(artist, title, config.get('spotify_id', ''), config.get('spotify_secret', ''))),
    ]
    for name, configured, fn in providers:
        if not configured:
            debug['providers'][name] = {'status': 'not_configured', 'tags': []}
            continue
        try:
            item = fn()
            if item:
                results.append(item)
                debug['providers'][name] = {'status': 'matched', 'year': item.get('year'),
                    'tags': item.get('tags', [])[:30], 'confidence': item.get('confidence')}
            else:
                debug['providers'][name] = {'status': 'no_matching_recording', 'tags': []}
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            # Never include request URLs, headers, or exception text: they can contain API keys.
            reason = f'HTTP {status}' if status else 'HTTP error'
            debug['providers'][name] = {'status': 'request_failed', 'reason': reason, 'tags': []}
            errors.append(f'{name}: {reason}')
        except Exception as exc:
            # A provider can include credential values in raw exception strings.
            reason = type(exc).__name__
            debug['providers'][name] = {'status': 'request_failed', 'reason': reason, 'tags': []}
            errors.append(f'{name}: {reason}')
        if name == 'MusicBrainz':
            time.sleep(1.05)
    years = [r['year'] for r in results if r.get('year')]
    tags = []
    for name in ('Last.fm', 'Discogs', 'MusicBrainz'):
        tags.extend(t for r in results if r['source'] == name for t in r.get('tags', []))
    genre, subgenre = classify(tags)
    debug['genre_candidates'] = tags[:40]
    debug['rejected_tags'] = [t for t in tags if not valid_genre(t)]
    debug['genre_decision'] = {'genre': genre or None, 'subgenre': subgenre or None,
        'reason': ('recognized_or_preserved_genre' if genre else ('only_generic_or_invalid_tags' if tags else 'no_genre_tags_returned'))}
    return {'year': str(min(years)) if years else '', 'genre': genre, 'subgenre': subgenre,
            'sources': [r['source'] for r in results], 'errors': errors, 'tags': tags[:20],
            'score': 'Review', 'lookup_debug': debug,
            'recording_id': next((r.get('recording_id') for r in results if r.get('recording_id')), None),
            'error': ('Metadata lookup failed: ' + '; '.join(errors) if errors and not results else
                      'No matching metadata found.' if not results else None)}