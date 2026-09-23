"""Exercise real transactional writers with isolated KZone fixtures."""
import copy
import unittest
from unittest.mock import patch
import test_story_space_isolation as fixtures
b = fixtures.b
from social import POST_DEFAULT

class SocialInputRoundTripTests(unittest.TestCase):
    setUp = fixtures.StorySpaceIsolationTests.setUp
    write = fixtures.StorySpaceIsolationTests.write

    def test_like_delay_and_signature_survive_disk_roundtrip(self):
        self.write('PersonCfg', {'3': {'id': 3, 'name': '小雅'}})
        self.write('KZoneColorCfg', {'1': {'id': 1}})
        profile = {**b.read_json(self.cfg/'KZoneProfileCfg.json')['3'], 'isVip': 1, 'theme': 1}
        self.write('KZoneProfileCfg', {'3': profile})
        post = {**copy.deepcopy(POST_DEFAULT), 'id': 12345, 'role': 3, 'content': '测试', 'thumbs': [[3, 0]]}
        self.write('KZoneContentCfg', {'12345': post})
        post['thumbs'] = [[3, 45]]
        self.store.social.save({'projectId': self.ident, 'revision': self.store.revision(self.project), 'posts': {'12345': post}, 'comments': {}, 'editor': {'disabledOptions': {}}})
        self.assertEqual(b.read_json(self.cfg/'KZoneContentCfg.json')['12345']['thumbs'], [[3, 45]])
        profile['desc'] = '荀彧，字文若。'
        with patch('character_rules.references', return_value={'KZoneFontCfg': {}}):
            self.store.space.save({'projectId': self.ident, 'revision': self.store.revision(self.project), 'profiles': {'3': profile}})
        self.assertEqual(b.read_json(self.cfg/'KZoneProfileCfg.json')['3']['desc'], profile['desc'])
        self.assertEqual(b.read_json(self.cfg/'KZoneContentCfg.json')['12345']['thumbs'], [[3, 45]])

if __name__ == '__main__': unittest.main()
