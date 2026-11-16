import unittest
from genre_workspace import plan_genre_writes, family_track_count, is_duplicate_genre

class Release316Tests(unittest.TestCase):
    def test_bulk_group_changes(self):
        rows={'one.mp3':{'genre':'Neo Soul'},'two.mp3':{'genre':'R&B'},'three.mp3':{'genre':'Rock'}}
        result=plan_genre_writes(rows, {'Neo Soul':'Soul', 'R&B':'Soul'})
        self.assertEqual(set(result), {'one.mp3','two.mp3'})
        self.assertEqual(result['one.mp3']['composer'],'Neo Soul')
    def test_family_count_distinct(self):
        self.assertEqual(family_track_count('R&B', {'R&B':['Neo Soul','Soul']}, {'Neo Soul':['a','b'],'Soul':['b','c']}),3)
    def test_duplicate_spelling(self):
        self.assertTrue(is_duplicate_genre('Hip-Hop', ['Hip Hop']))
