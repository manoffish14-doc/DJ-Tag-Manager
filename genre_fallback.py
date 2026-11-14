"""Conservative artist-based fallback for empty genre tags only."""
import re

ARTIST_GENRES = {
    'chris brown': 'R&B', 'usher': 'R&B', 'drake': 'Hip-Hop',
    'burna boy': 'Afrobeats', 'future': 'Hip-Hop',
    'rihanna': 'Pop', 'bad bunny': 'Reggaeton',
}

def artist_baseline(artist):
    name = re.sub(r'\s+', ' ', str(artist or '')).strip().casefold()
    name = re.split(r'\s+(?:ft\.?|feat\.?|featuring|with|x)\s+', name, maxsplit=1)[0]
    return ARTIST_GENRES.get(name, '')

def genre_decision(existing, database_genre, artist):
    """Return (genre, source), without guessing over a populated field."""
    if database_genre and str(database_genre).strip():
        return str(database_genre).strip(), 'database'
    if existing and str(existing).strip():
        return str(existing).strip(), 'existing'
    guess = artist_baseline(artist)
    return (guess, 'artist_baseline') if guess else ('', 'none')
