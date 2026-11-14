import tempfile
import unittest
from pathlib import Path
from cleanup_engine import (duplicate_clusters, group_id, best_copy, archive_plan,
                            genre_group, genre_inventory, genre_changes, cleanup_name,
                            name_candidates, version_kind)


class CleanupEngineTests(unittest.TestCase):
    def test_clean_dirty_unknown_separate(self):
        rows = {f'{i}': {'artist': 'A', 'title': title} for i, title in enumerate([
            'Song (Clean)', 'Song [Clean]', 'Song (Explicit)', 'Song (Dirty)', 'Song', 'Song'])}
        groups = duplicate_clusters(rows)
        self.assertEqual(sorted(len(g) for g in groups), [2, 2, 2])
        self.assertEqual(len({version_kind(rows[g[0]]) for g in groups}), 3)

    def test_missing_tags_not_duplicates(self):
        self.assertFalse(duplicate_clusters({'a': {'artist': '', 'title': 'A'}, 'b': {'artist': '', 'title': 'A'}}))

    def test_keep_bitrate_then_plays(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = [str(Path(tmp) / name) for name in ('a.mp3', 'b.mp3')]
            Path(a).write_bytes(b'x'); Path(b).write_bytes(b'xx')
            rows = {a: {'bitrate': '320', 'plays': 1}, b: {'bitrate': '320', 'plays': 10}}
            self.assertEqual(best_copy([a, b], rows), b)
            self.assertEqual(best_copy([a, b], rows, False), b)
            rows[a]['bitrate'] = '320'; rows[b]['bitrate'] = '256'
            self.assertEqual(best_copy([a, b], rows), a)

    def test_review_required_and_keep_required(self):
        groups = [['a', 'b']]
        gid = group_id(groups[0])
        self.assertEqual(archive_plan(groups, {}), [])
        with self.assertRaises(ValueError): archive_plan(groups, {gid: {'reviewed': True, 'keeps': []}})
        self.assertEqual(archive_plan(groups, {gid: {'reviewed': True, 'keeps': ['a']}}), ['b'])

    def test_grouping_is_organizational_only(self):
        rows = {'a': {'genre': 'Hip-Hop'}, 'b': {'genre': 'R&B'}, 'c': {'genre': 'New Genre'}}
        groups = genre_inventory(rows)
        self.assertIn('Hip-Hop', groups['Hip Hop'])
        self.assertIn('R&B', groups['R&B'])
        self.assertIn('New Genre', groups['Other'])
        self.assertEqual(rows['a']['genre'], 'Hip-Hop')
        self.assertEqual(genre_group('New Genre', {'New Genre': 'Rock'}), 'Rock')

    def test_genre_changes_preserve_original(self):
        rows = {'a': {'genre': 'Old', 'composer': 'Existing'}}
        self.assertEqual(genre_changes(rows, ['a'], 'New', True)['a'], {'genre': 'New', 'composer': 'Old'})
        self.assertEqual(rows['a']['composer'], 'Existing')
        with self.assertRaises(ValueError): genre_changes(rows, ['a'], '')

    def test_name_cleanup_keeps_remix_suffix(self):
        self.assertEqual(cleanup_name(' Track   feat John (Club Remix) ', 'title'), 'Track ft. John (Club Remix)')
        rows = {'song': {'title': ' Track   feat John (Club Remix) ', 'artist': 'DJ'}}
        proposals = name_candidates(rows)
        self.assertTrue(any(p['after'] == 'Track ft. John (Club Remix)' for p in proposals))
        self.assertFalse(any(p['after'] == 'Track ft. John (Club Remix)' for p in name_candidates(rows, [proposals[0]['id']])))


if __name__ == '__main__': unittest.main()
