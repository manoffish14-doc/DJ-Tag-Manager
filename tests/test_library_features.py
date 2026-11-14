import json
import tempfile
import unittest
from pathlib import Path
from library_features import duplicate_groups, preferred_copy, archive_files, restore_archive, name_suggestions, LibraryStore


class LibraryFeatureTests(unittest.TestCase):
    def test_duplicates_and_preferred(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp)/'one.mp3', Path(tmp)/'two.mp3'
            a.write_bytes(b'a'); b.write_bytes(b'bb')
            rows = {str(a):{'title':'Song','artist':'DJ','bitrate':'192 kbps'},
                    str(b):{'title':'Song','artist':'DJ','bitrate':'320 kbps'}}
            groups = duplicate_groups(rows)
            self.assertEqual(len(groups), 1)
            self.assertEqual(preferred_copy(groups[0], rows), str(b))

    def test_archive_restore_and_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp)/'song.mp3'; src.write_bytes(b'music')
            archive = Path(tmp)/'archive'; archive.mkdir()
            manifest, filename = archive_files([str(src)], archive, {str(src):{}})
            self.assertFalse(src.exists())
            self.assertTrue((archive/'song.mp3').exists())
            self.assertTrue(filename.is_file())
            self.assertEqual(restore_archive(filename), 1)
            self.assertEqual(src.read_bytes(), b'music')
            (archive/'song.mp3').write_bytes(b'existing')
            with self.assertRaises(FileExistsError):
                archive_files([str(src)], archive, {str(src):{}})
            self.assertEqual(src.read_bytes(), b'music')

    def test_cues_persist(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'db.sqlite3'
            store = LibraryStore(path)
            store.save_cue('track', 2, 32.5, 'Drop')
            self.assertEqual(LibraryStore(path).cues('track')[0]['label'], 'Drop')
            store.clear_cue('track', 2)
            self.assertEqual(store.cues('track'), [])

    def test_name_suggestions(self):
        suggestion = name_suggestions({'title':'DJ - My Song', 'artist':'DJ'})
        self.assertEqual(suggestion['title'][0], 'My Song')

if __name__ == '__main__': unittest.main()
