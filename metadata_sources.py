"""Independent metadata providers. Only high-confidence exact-ish matches contribute."""
import re
import time
from difflib import SequenceMatcher
import requests

UA = 'DJTagManager/0.5 (personal music library tagging)'
HEADERS = {'User-Agent': UA}

def norm(s):
    s = re.sub(r'\([^)]*(official|video|lyrics|audio)[^)]*\)', '', s or '', flags=re.I)
    s = re.sub(r'\b(feat\.?|ft\.?)\b.*$', '', s, flags=re.I)
    return re.sub(r'[^a-z0-9]+', '', s.casefold())

def similar(a,b):
    a,b=norm(a),norm(b)
    return bool(a and b) and (a==b or SequenceMatcher(None,a,b).ratio()>=.88)

def get(url, params=None, headers=None, auth=None):
    r=requests.get(url, params=params, headers=headers or HEADERS, auth=auth, timeout=12)
    r.raise_for_status()
    return r.json()

def musicbrainz(artist,title):
    # Prefer precise matching, then retry with a less restrictive query.
    data=get('https://musicbrainz.org/ws/2/recording/', {'query':f'artist:"{artist}" AND recording:"{title}"','fmt':'json','limit':10})
    if not data.get('recordings'):
        data=get('https://musicbrainz.org/ws/2/recording/', {'query':f'{artist} {title}','fmt':'json','limit':20})
    recs=[r for r in data.get('recordings',[]) if similar(r.get('title',''),title) and any(similar(a.get('name',''),artist) for a in r.get('artist-credit',[]) if isinstance(a,dict))]
    if not recs:return None
    best=max(recs,key=lambda x:x.get('score',0))
    years=[int(r['first-release-date'][:4]) for r in recs if re.match(r'^\d{4}',r.get('first-release-date',''))]
    # Search results often omit genre tags. Fetch the recording directly.
    tags=best.get('tags',[]) or best.get('genres',[])
    if not tags and best.get('id'):
        try:
            details=get('https://musicbrainz.org/ws/2/recording/'+best['id'], {'inc':'genres+tags','fmt':'json'})
            tags=details.get('genres',[]) or details.get('tags',[])
        except (requests.RequestException, ValueError):
            pass
    return {'source':'MusicBrainz','year':min(years) if years else None,'tags':[x['name'] for x in sorted(tags,key=lambda t:t.get('count',0),reverse=True) if x.get('name')], 'confidence':best.get('score',0)}

def lastfm(artist,title,key):
    if not key:return None
    data=get('https://ws.audioscrobbler.com/2.0/', {'method':'track.getTopTags','artist':artist,'track':title,'autocorrect':1,'api_key':key,'format':'json'})
    if data.get('error'):raise ValueError(data.get('message','Last.fm error'))
    tags=data.get('toptags',{}).get('tag',[])
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
 'R&B':['contemporary r&b','alternative r&b','new jack swing','neo soul','rhythm and blues','r&b','rnb','soul'],
 'Hip Hop':['southern hip hop','east coast hip hop','west coast hip hop','trap','drill','boom bap','hip-hop','hip hop','rap'],
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
GENERIC={'seen live','favorites','favorite','american','male vocalists','female vocalists','00s','2000s','2010s','90s','80s','awesome','love','music'}

def classify(tags):
    for tag in tags:
        cleaned=tag.casefold().strip()
        if cleaned in GENERIC:continue
        for broad,variants in GENRES.items():
            if cleaned in variants:
                # Preserve specific source tag in Composer; for broad-only tags leave subgenre blank.
                return broad, tag.title() if cleaned != broad.casefold() else ''
    return '', ''

def lookup(artist,title,config):
    if not artist or not title:return {'error':'Artist and title are needed for lookup.'}
    results=[];errors=[]
    providers=[('MusicBrainz',lambda:musicbrainz(artist,title)),('Last.fm',lambda:lastfm(artist,title,config.get('lastfm',''))),('Discogs',lambda:discogs(artist,title,config.get('discogs',''))),('Spotify',lambda:spotify(artist,title,config.get('spotify_id',''),config.get('spotify_secret','')))]
    for name,fn in providers:
        try:
            item=fn()
            if item:results.append(item)
        except Exception as e:errors.append(f'{name}: {str(e)[:90]}')
        if name=='MusicBrainz':time.sleep(1.05)
    years=[r['year'] for r in results if r.get('year')]
    # Track-specific tags first (Last.fm), then release styles (Discogs), then MusicBrainz.
    tags=[]
    for name in ('Last.fm','Discogs','MusicBrainz'):
        tags.extend(t for r in results if r['source']==name for t in r.get('tags',[]))
    genre,subgenre=classify(tags)
    # When only a broad tag is available, don't invent a specific subgenre.
    return {'year':str(min(years)) if years else '', 'genre':genre,'subgenre':subgenre,
            'sources':[r['source'] for r in results], 'errors':errors,'tags':tags[:20],
            'score':'Review', 'error': 'No matching metadata found.' if not results else None}
