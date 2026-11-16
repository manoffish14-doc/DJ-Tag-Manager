import unittest
from genre_workspace import canonical_genre, is_duplicate_genre

class GenreNameTests(unittest.TestCase):
    def test_normalization(self):
        self.assertEqual(canonical_genre('  HIP-Hop '), canonical_genre('hip hop'))
        self.assertEqual(canonical_genre('R & B'), canonical_genre('R&B'))
    def test_duplicates(self):
        self.assertTrue(is_duplicate_genre('hip-hop', {'Hip Hop', 'Trap'}))
        self.assertFalse(is_duplicate_genre('Neo Soul', {'Hip Hop', 'Trap'}))
