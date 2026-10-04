"""Exercise real transactional writers with isolated KZone fixtures."""
import copy
import unittest
from unittest.mock import patch
import test_story_space_isolation as fixtures
b = fixtures.b
from social import POST_DEFAULT, COMMENT_DEFAULT

class SocialInputRoundTripTests(unittest.TestCase):
    setUp = fixtures.StorySpaceIsolationTests.setUp
    write = fixtures.StorySpaceIsolationTests.write

    def test_existing_comment_edits_update_incoming_delays_and_preserve_rows(self):
        self.write('PersonCfg', {'3': {'id': 3, 'name': '杰哥'}, '4': {'id': 4, 'name': '小雅'}})
        profile = b.read_json(self.cfg/'KZoneProfileCfg.json')['3']
        self.write('KZoneProfileCfg', {'3': profile, '4': {**profile, 'id': 4, 'name': '小雅'}})
        post = {**copy.deepcopy(POST_DEFAULT), 'id': 12345, 'role': 3, 'content': '测试', 'comments': [[1234501, 2]], 'future': {'post': True}}
        comment = {**copy.deepcopy(COMMENT_DEFAULT), 'id': 1234501, 'roles': [3], 'content': '原评论', 'comments': [[1234502, 2]], 'future': {'keep': [1, 2]}}
        reply = {**copy.deepcopy(COMMENT_DEFAULT), 'id': 1234502, 'roles': [4, 3], 'parent': 1234501, 'content': '原回复'}
        self.write('KZoneContentCfg', {'12345': post})
        self.write('KZoneCommentCfg', {'1234501': comment, '1234502': reply})
        protected = (self.cfg/'TalkCfg.json').read_bytes()
        data = self.store.social.load(self.ident)
        data['posts']['12345']['comments'][0][1] = 1
        data['comments']['1234501']['content'] = '修改后的评论'
        data['comments']['1234501']['roles'] = [4]
        data['comments']['1234501']['comments'][0][1] = 1
        data['comments']['1234502']['roles'] = [3, 4]
        data['comments']['1234502']['content'] = '修改后的回复'
        del data['comments']['1234501']['future']
        self.store.social.save({'projectId': self.ident, 'revision': data['revision'], 'posts': data['posts'], 'comments': data['comments'], 'editor': data['editor']})
        data = self.store.social.load(self.ident)
        self.assertEqual(data['posts']['12345']['comments'], [[1234501, 1]])
        self.assertEqual(data['comments']['1234501']['comments'], [[1234502, 1]])
        self.assertEqual(data['comments']['1234501']['content'], '修改后的评论')
        self.assertEqual(data['comments']['1234501']['roles'], [4])
        self.assertEqual(data['comments']['1234501']['future'], {'keep': [1, 2]})
        self.assertEqual(data['comments']['1234502']['content'], '修改后的回复')
        self.assertEqual(data['comments']['1234502']['parent'], 1234501)
        self.assertEqual(set(data['comments']), {'1234501', '1234502'})
        self.assertEqual((self.cfg/'TalkCfg.json').read_bytes(), protected)

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
