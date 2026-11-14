import unittest
from mac_feedback_fixes import normalized_visible_columns


class MacFeedbackTests(unittest.TestCase):
    def test_track_identity_restored(self):
        self.assertEqual(normalized_visible_columns(['year', 'genre'], ['title','artist','year','genre']),
                         ['title','artist','year','genre'])

    def test_duplicate_and_unknown_columns_removed(self):
        self.assertEqual(normalized_visible_columns(['title','title','bad','artist','genre'],
                         ['title','artist','genre']), ['title','artist','genre'])

    def test_user_order_preserved(self):
        self.assertEqual(normalized_visible_columns(['artist','title','genre'],
                         ['title','artist','genre']), ['artist','title','genre'])


if __name__ == '__main__':
    unittest.main()
