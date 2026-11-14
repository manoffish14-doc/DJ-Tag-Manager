import unittest
from unittest.mock import patch
import requests
from metadata_sources import clean_query, lookup

class LookupRepairTests(unittest.TestCase):
    def test_youtube_title_and_featured_artist(self):
        self.assertEqual(clean_query('Chris Brown ft. Juelz Santana',
            'Chris Brown - Run It! (Official HD Video) ft. Juelz Santana'), ('Chris Brown','Run It!'))
    def test_uploader_replaced_for_video_search_only(self):
        self.assertEqual(clean_query('SoundKream','Chris Brown - Wall To Wall (Lyrics)'),
                         ('Chris Brown','Wall To Wall'))
    def test_provider_failure_is_not_no_match(self):
        with patch('metadata_sources.musicbrainz',side_effect=requests.HTTPError('bad')):
            result=lookup('Chris Brown','Run It!',{})
        self.assertIn('failed',result['error'])
        self.assertEqual(result['lookup_debug']['search_title'],'Run It!')
