"""Phase 3: deterministic, non-destructive cleanup planning.

No filesystem mutations occur here. UI callers must obtain confirmation and use
metadata_safety.safe_write for audio metadata changes.
"""
import hashlib
import re
import unicodedata
from collections import defaultdict
from pathlib import Path


def fold(value):
    return ''.join(ch for ch in unicodedata.normalize('NFKD', str(value or '').casefold()) if ch.isalnum())


def version_kind(row):
    text = ' '.join(str(row.get(k) or '') for k in ('title', 'version', 'mix'))
    if re.search(r'\b(clean|radio edit|radio version)\b', text, re.I): return 'clean'
    if re.search(r'\b(dirty|explicit|uncensored)\b', text, re.I): return 'dirty'
    return 'unknown'


def normalized_title(title):
    return fold(re.sub(r'\s*[\(\[]\s*(?:clean|dirty|explicit|radio edit|radio version)\s*[\)\]]', '', str(title or ''), flags=re.I))


def duplicate_clusters(rows, similar=False):
    groups = defaultdict(list)
    for path, row in rows.items():
        artist = fold(row.get('artist'))
        title = normalized_title(row.get('title'))
        if not artist or not title: continue
        # Exact groups keep clean/dirty/unknown completely separate.
        key = (artist, title, version_kind(row))
        groups[key].append(path)
    clusters = [sorted(paths) for paths in groups.values() if len(paths) > 1]
    return sorted(clusters, key=lambda g: (fold(rows[g[0]].get('artist')), fold(rows[g[0]].get('title'))))


def group_id(paths):
    return hashlib.sha256('\0'.join(sorted(map(str, paths))).encode('utf-8')).hexdigest()


def bitrate(row):
    m = re.search(r'\d+', str(row.get('bitrate', '')))
    return int(m.group()) if m else 0


def play_count(row):
    for key in ('play_count', 'plays', 'playcount'):
        try: return int(row.get(key) or 0)
        except (TypeError, ValueError): pass
    return 0


def best_copy(paths, rows, prefer_plays=True):
    def score(path):
        row = rows[path]
        try: size = Path(path).stat().st_size
        except OSError: size = 0
        return (bitrate(row), play_count(row) if prefer_plays else 0, size, str(path))
    return max(paths, key=score)


def archive_plan(clusters, decisions):
    """Require a reviewed group and at least one Keep before selecting files."""
    targets = []
    for group in clusters:
        decision = decisions.get(group_id(group), {})
        if not decision.get('reviewed'): continue
        keeps = set(decision.get('keeps', []))
        if not keeps.intersection(group):
            raise ValueError('Every reviewed group must retain at least one track')
        targets.extend(path for path in group if path not in keeps)
    return list(dict.fromkeys(targets))


GENRE_GROUPS = ('Hip Hop', 'R&B', 'Pop', 'Classic Rock', 'Rock', 'African', 'Other')
GENRE_ALIASES = {'hiphop': 'Hip Hop', 'hiphoprap': 'Hip Hop', 'rap': 'Hip Hop',
                 'rnb': 'R&B', 'rb': 'R&B', 'randb': 'R&B', 'rhythmandblues': 'R&B',
                 'afrobeats': 'African', 'afrobeat': 'African', 'amapiano': 'African',
                 'pop': 'Pop', 'classicrock': 'Classic Rock', 'rock': 'Rock'}


def genre_group(genre, overrides=None):
    if overrides and genre in overrides: return overrides[genre]
    return GENRE_ALIASES.get(fold(genre), 'Other')


def genre_inventory(rows, overrides=None):
    inventory = defaultdict(lambda: defaultdict(list))
    for path, row in rows.items():
        label = str(row.get('genre') or '').strip()
        inventory[genre_group(label, overrides)][label or '(Missing Genre)'].append(path)
    return {g: dict(labels) for g, labels in inventory.items()}


def genre_changes(rows, paths, replacement, preserve_original=False):
    replacement = str(replacement).strip()
    if not replacement: raise ValueError('Replacement genre cannot be empty')
    changes = {}
    for path in dict.fromkeys(paths):
        row = rows[path]
        update = {'genre': replacement}
        if preserve_original: update['composer'] = str(row.get('genre') or '')
        changes[path] = update
    return changes


def cleanup_name(value, field):
    """Conservative formatting: never remove mix/remix/version suffixes."""
    old = str(value or '')
    new = re.sub(r'\s+', ' ', old).strip()
    new = re.sub(r'\s*\b(?:featuring|feat\.?|ft\.?)\s+', ' ft. ', new, flags=re.I)
    new = re.sub(r'\s+([,;])', r'\1', new)
    new = re.sub(r'\s*([–—])\s*', r' \1 ', new)
    return new.strip()


def name_candidates(rows, dismissed=()):
    """Return stable proposals without writing tags or files."""
    dismissed = set(dismissed)
    output = []
    for path, row in rows.items():
        for field in ('title', 'artist'):
            original = str(row.get(field) or '')
            updated = cleanup_name(original, field)
            if updated and updated != original:
                key = f'{path}|{field}|{updated}'
                if key not in dismissed:
                    output.append({'id': key, 'path': path, 'field': field, 'before': original,
                                   'after': updated, 'confidence': 91, 'reason': 'Consistent spacing and featured-artist notation'})
        # Existing library heuristics can supplement these conservative proposals.
        from library_features import name_suggestions
        for field, (updated, confidence) in name_suggestions(row).items():
            key = f'{path}|{field}|{updated}'
            if key not in dismissed and not any(p['id'] == key for p in output):
                output.append({'id': key, 'path': path, 'field': field,
                               'before': str(row.get(field) or ''), 'after': updated,
                               'confidence': confidence, 'reason': 'Possible artist/title correction'})
    return output


# Fuzzy matches are review suggestions, never automatic archive targets.
def similar_duplicate_clusters(rows, threshold=0.86):
    """Conservative same-artist, same-version title similarity.

    Uses bounded title similarity, ignoring punctuation but NOT remix/version words.
    Returns groups of paths with two or more members; does not mutate the library.
    """
    from difflib import SequenceMatcher
    if not 0.5 <= threshold <= 1.0:
        raise ValueError('threshold must be between 0.5 and 1.0')
    buckets = defaultdict(list)
    for path, row in rows.items():
        artist = fold(row.get('artist'))
        title = normalized_title(row.get('title'))
        if artist and title:
            buckets[(artist, version_kind(row))].append((path, title))
    result = []
    for bucket in buckets.values():
        # Connected components: a path belongs to at most one review group.
        parent = list(range(len(bucket)))
        def root(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i
        for i in range(len(bucket)):
            for j in range(i + 1, len(bucket)):
                a, b = bucket[i][1], bucket[j][1]
                if a == b or SequenceMatcher(None, a, b).ratio() >= threshold:
                    parent[root(j)] = root(i)
        components = defaultdict(list)
        for i, (path, _) in enumerate(bucket):
            components[root(i)].append(path)
        result.extend(sorted(paths) for paths in components.values() if len(paths) > 1)
    return sorted(result, key=lambda paths: (fold(rows[paths[0]].get('artist')), paths[0]))


def discover_audio_files(folder, recursive=True, extensions=None):
    """Enumerate files without importing or changing them; reject invalid folders."""
    base = Path(folder).expanduser().resolve(strict=True)
    if not base.is_dir():
        raise NotADirectoryError(str(base))
    suffixes = set(extensions or ('.mp3', '.flac', '.m4a', '.mp4', '.aif', '.aiff', '.wav', '.ogg', '.opus'))
    iterator = base.rglob('*') if recursive else base.iterdir()
    return sorted(str(path) for path in iterator if path.is_file() and path.suffix.lower() in suffixes)


def incremental_name_scan(paths, fingerprint_cache, reader, force=False):
    """Read only new/changed files. Return (rows, new_cache, failures).

    Fingerprints include mtime_ns and size. A changed file is never skipped.
    The caller decides whether to persist the cache after reviewing results.
    """
    output, updated, failures = {}, dict(fingerprint_cache), {}
    for name in dict.fromkeys(map(str, paths)):
        try:
            stat = Path(name).stat()
            signature = f'{stat.st_size}:{stat.st_mtime_ns}'
            if not force and updated.get(name) == signature:
                continue
            output[name] = reader(name)
            updated[name] = signature
        except Exception as exc:
            failures[name] = str(exc)
    return output, updated, failures
