import tempfile
import unittest
from pathlib import Path
from cleanup_engine import similar_duplicate_clusters, discover_audio_files, incremental_name_scan


class CleanupExtensionTests(unittest.TestCase):
    def test_similar_matches_and_version_separation(self):
        rows = {'a': {'artist': 'DJ Test', 'title': 'Summer Vibes (Clean)'},
                'b': {'artist': 'DJ Test', 'title': 'Summer Vibe (Clean)'},
                'c': {'artist': 'DJ Test', 'title': 'Summer Vibes (Explicit)'},
                'd': {'artist': 'Another', 'title': 'Summer Vibes (Clean)'}}
        self.assertEqual(similar_duplicate_clusters(rows, .8), [['a', 'b']])

    def test_similar_does_not_merge_versions_or_artists(self):
        rows = {'a': {'artist': 'A', 'title': 'Mix (Clean)'},
                'b': {'artist': 'A', 'title': 'Mix (Dirty)'},
                'c': {'artist': 'B', 'title': 'Mix (Clean)'}}
        self.assertEqual(similar_duplicate_clusters(rows), [])

    def test_invalid_threshold(self):
        with self.assertRaises(ValueError): similar_duplicate_clusters({}, 1.1)

    def test_recursive_folder_discovery(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root/'sub').mkdir()
            (root/'a.MP3').write_bytes(b'a')
            (root/'sub'/'b.flac').write_bytes(b'b')
            (root/'sub'/'notes.txt').write_text('ignore')
            self.assertEqual(len(discover_audio_files(d, False)), 1)
            self.assertEqual(len(discover_audio_files(d, True)), 2)

    def test_incremental_scan_skips_unchanged_and_rechecks_changed(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'a.mp3'; path.write_bytes(b'a')
            calls = []
            def read(p): calls.append(p); return {'title': 'Hello'}
            rows, cache, failures = incremental_name_scan([path], {}, read)
            self.assertEqual(len(rows), 1); self.assertFalse(failures)
            rows, cache, failures = incremental_name_scan([path], cache, read)
            self.assertEqual(len(rows), 0); self.assertEqual(len(calls), 1)
            path.write_bytes(b'longer')
            rows, cache, failures = incremental_name_scan([path], cache, read)
            self.assertEqual(len(rows), 1); self.assertEqual(len(calls), 2)
            rows, cache, failures = incremental_name_scan([path], cache, read, force=True)
            self.assertEqual(len(rows), 1); self.assertEqual(len(calls), 3)

    def test_failed_read_not_cached(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'broken.mp3'; path.write_bytes(b'x')
            def fail(p): raise ValueError('unreadable')
            rows, cache, failures = incremental_name_scan([path], {}, fail)
            self.assertFalse(rows); self.assertFalse(cache); self.assertIn(str(path), failures)

if __name__ == '__main__': unittest.main()
