import unittest
from workspace_layout import sidebar_width, valid_column_filters, shortcut_conflicts


class WorkspaceLayoutTests(unittest.TestCase):
    def test_width_clamped(self):
        self.assertEqual(sidebar_width(500), 350)
        self.assertEqual(sidebar_width(80), 180)
        self.assertEqual(sidebar_width('bad'), 240)

    def test_filters_drop_unknown_and_oversized(self):
        self.assertEqual(valid_column_filters({'title':'house', 'bad':'x', 'artist':1}, {'title','artist'}), {'title':'house'})
        self.assertEqual(valid_column_filters([], {'title'}), {})
        self.assertEqual(valid_column_filters({'title':'x'*201}, {'title'}), {})

    def test_shortcut_collisions(self):
        self.assertTrue(shortcut_conflicts({'a':'<Command-a>','b':'<Command-a>'}))
        self.assertFalse(shortcut_conflicts({'a':'<Command-a>','b':'<Command-b>'}))

if __name__ == '__main__':
    unittest.main()
