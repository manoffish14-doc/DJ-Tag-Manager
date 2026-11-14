import unittest
from genre_workspace import plan_genre_writes, inventory, DEFAULT_GROUPS

class VerticalGenreTests(unittest.TestCase):
    def test_composer_overwritten_with_original_subgenre(self):
        rows = {'a.mp3': {'genre': 'Trap', 'composer': 'Original composer'}}
        self.assertEqual(plan_genre_writes(rows, {'Trap': 'Hip Hop'}), {'a.mp3': {'genre': 'Hip Hop', 'composer': 'Trap'}})
    def test_unselected_untouched(self):
        rows = {'a.mp3': {'genre': 'Trap'}, 'b.mp3': {'genre': 'Neo Soul'}}
        self.assertEqual(list(plan_genre_writes(rows, {'Trap': 'Hip Hop'})), ['a.mp3'])
    def test_parent_genre_unchanged(self):
        self.assertFalse(plan_genre_writes({'a': {'genre': 'R&B'}}, {'R&B': 'R&B'}))
    def test_empty_parents_always_visible(self):
        self.assertTrue(all(x in inventory({}) for x in DEFAULT_GROUPS))
