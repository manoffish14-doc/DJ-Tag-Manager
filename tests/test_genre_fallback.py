import unittest
from genre_fallback import genre_decision, artist_baseline

class GenreFallbackTests(unittest.TestCase):
    def test_known_artist(self):
        self.assertEqual(artist_baseline('Chris Brown ft. Juelz Santana'), 'R&B')
    def test_database_replaces_existing(self):
        self.assertEqual(genre_decision('Hip-Hop','R&B','Chris Brown'), ('R&B','database'))
    def test_database_fills_blank(self):
        self.assertEqual(genre_decision('','Hip-Hop','Chris Brown'), ('Hip-Hop','database'))
    def test_existing_without_database(self):
        self.assertEqual(genre_decision('Hip-Hop','','Chris Brown'), ('Hip-Hop','existing'))
    def test_blank_fallback(self):
        self.assertEqual(genre_decision('','','Chris Brown'), ('R&B','artist_baseline'))
    def test_unknown(self):
        self.assertEqual(genre_decision('','','Unknown Artist'), ('','none'))
if __name__ == '__main__': unittest.main()
