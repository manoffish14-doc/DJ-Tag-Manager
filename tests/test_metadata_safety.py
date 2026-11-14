import tempfile
import unittest
from pathlib import Path
from metadata_safety import safe_write, fingerprint, history, restore_write, FileChangedError, UnsafeWriteError


def reader(path):
    return {'title': Path(path).read_text()}


def writer(path, changes, custom):
    Path(path).write_text(changes['title'])

class MetadataSafetyTests(unittest.TestCase):
    def test_verified_write_and_restore(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);audio=root/'song.mp3';audio.write_text('Original')
            before=fingerprint(audio)
            record=safe_write(audio,{'title':'Updated'},{},writer,reader,root/'recovery',expected=before)
            self.assertEqual(audio.read_text(),'Updated')
            self.assertEqual(len(history(root/'recovery'/'metadata_writes.sqlite3')),1)
            restore_write(root/'recovery'/'metadata_writes.sqlite3',record['id'])
            self.assertEqual(audio.read_text(),'Original')
            with self.assertRaises(UnsafeWriteError):
                restore_write(root/'recovery'/'metadata_writes.sqlite3',record['id'])

    def test_external_change_blocks_write(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);audio=root/'song.mp3';audio.write_text('Original')
            expected=fingerprint(audio);audio.write_text('Someone else edited this')
            with self.assertRaises(FileChangedError):
                safe_write(audio,{'title':'Updated'},{},writer,reader,root/'recovery',expected=expected)
            self.assertEqual(audio.read_text(),'Someone else edited this')

    def test_failed_writer_keeps_original(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);audio=root/'song.mp3';audio.write_text('Original')
            def broken(path,changes,custom):
                Path(path).write_text('Bad partial edit')
                raise RuntimeError('broken')
            with self.assertRaises(RuntimeError):
                safe_write(audio,{'title':'Updated'},{},broken,reader,root/'recovery')
            self.assertEqual(audio.read_text(),'Original')

    def test_restore_refuses_newer_edits(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);audio=root/'song.mp3';audio.write_text('Original')
            record=safe_write(audio,{'title':'Updated'},{},writer,reader,root/'recovery')
            audio.write_text('Newer edit')
            with self.assertRaises(FileChangedError):
                restore_write(root/'recovery'/'metadata_writes.sqlite3',record['id'])
            self.assertEqual(audio.read_text(),'Newer edit')

if __name__=='__main__': unittest.main()
