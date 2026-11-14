import unittest
from metadata_automation import camelot, field_confidence, proposal, identify_from_filename

class MetadataAutomationTests(unittest.TestCase):
    def test_camelot(self):
        self.assertEqual(camelot('C','major'),'8B')
        self.assertEqual(camelot('A','minor'),'8A')
        self.assertEqual(camelot('F#','minor'),'11A')
    def test_protect_existing_and_identity(self):
        old={'artist':'Original','title':'Song','year':'2020','genre':'House','composer':'Original composer'}
        found={'artist':'Other','title':'Other','year':'2019','genre':'Pop','subgenre':'Dance pop'}
        self.assertEqual(proposal(old,found),{})
        self.assertEqual(proposal(old,found,fields={'year','genre'},replace_existing=True),{'year':'2019','genre':'Pop'})
    def test_selected_fields_and_analysis(self):
        self.assertEqual(proposal({}, {'year':'2020'}, {'bpm_tag':'120','key':'8A'},fields={'key'}),{'key':'8A'})
    def test_subgenre_explicit(self):
        self.assertEqual(proposal({}, {'subgenre':'Deep House'},fields={'subgenre'}),{'composer':'Deep House'})
    def test_filename_identity(self):
        self.assertEqual(identify_from_filename('/a/Artist - Title.mp3'),{'artist':'Artist','title':'Title'})
        self.assertEqual(identify_from_filename('/a/Title.mp3'),{})
    def test_confidence(self):
        scores=field_confidence({'year':'2020','genre':'House','sources':['MusicBrainz'],'lookup_debug':{'providers':{'MusicBrainz':{'confidence':82}}}})
        self.assertEqual(scores['year'],82)
        self.assertEqual(scores['subgenre'],0)
if __name__=='__main__':unittest.main()
