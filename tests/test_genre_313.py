import unittest
from genre_workspace import family_track_count

class Genre313Tests(unittest.TestCase):
    def test_parent_count_uses_unique_paths(self):
        self.assertEqual(family_track_count('R&B', {'R&B': ['R&B', 'Neo Soul']}, {'R&B': ['a.mp3', 'b.mp3'], 'Neo Soul': ['b.mp3', 'c.mp3']}), 3)
    def test_empty_parent(self):
        self.assertEqual(family_track_count('Hip Hop', {'Hip Hop': []}, {}), 0)
