"""Saved audio cues produce the UP contract as well as native audio boundaries."""
import copy
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server as b


class UpAudioSaveTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        env = patch.dict(os.environ, {
            'STUDIO_USER_DATA_ROOT': str(self.root / 'User'),
            'STUDIO_CACHE_ROOT': str(self.root / 'Cache'),
        })
        env.start()
        self.addCleanup(env.stop)
        self.store = b.StudioStore(self.root / 'Mods', self.root / 'Workshop',
                                   self.root / 'Game', asset_settings_path=self.root / 'assets.json')
        def close():
            deadline = time.monotonic() + 5
            while self.store.asset_catalog.hash_progress()['running'] and time.monotonic() < deadline:
                time.sleep(.01)
            self.store.close()
        self.addCleanup(close)
        self.ident = self.store.create('UP audio')['id']
        self.project = self.store.project(self.ident)
        self.cfg = self.project.path / 'Cfgs/zh-cn'
        self.rows = {str(i): {'id': i, 'content': 'line ' + str(i), 'audio': 0,
                              'nextTalk': [i + 1] if i < 8 else [], 'effect': [],
                              'future': {'keep': [1, 2]}} for i in range(1, 9)}
        self.write('TalkCfg', self.rows)
        self.write('EvtCfg', {'1': {'id': 1, 'talkId': [1]}})
        self.write('AudioCfg', {
            '7': {'id': 7, 'name': 'BGM', 'type': 1, 'url': 'bgm/a', 'volumn': .8},
            '8': {'id': 8, 'name': 'other BGM', 'type': 1, 'url': 'bgm/b'},
            '9': {'id': 9, 'name': 'SFX', 'type': 2, 'url': 'sound/door'},
            '10': {'id': 10, 'name': 'custom SFX', 'type': 2,
                   'url': 'Mods\\fixture\\Audios\\door.wav', 'future': 'keep'},
        })

    def write(self, name, rows):
        (self.cfg / (name + '.json')).write_bytes(b.json_bytes(rows))

    def read(self, name='TalkCfg'):
        return b.read_json(self.cfg / (name + '.json'))

    def group(self, ident='music', audio=7, talks=(1, 2, 3), **settings):
        return {'id': ident, 'audioId': audio, 'talkIds': list(talks),
                'loop': True, 'volume': 1, **settings}

    def save(self, **payload):
        return self.store.save({'projectId': self.ident,
                                'revision': self.store.revision(self.project), **payload})

    def test_bgm_and_sfx_save_to_actual_runtime_fields(self):
        self.save(audioCues={'sfx': {'2': [{'audioId': 9, 'volume': 1}]},
                             'bgm': [self.group()]})
        rows = self.read()
        self.assertEqual(rows['1']['audio'], 7)
        self.assertEqual(rows['2']['audio'], 0)
        self.assertIn([1163, 3, 9, 1], rows['2']['effect'])
        self.assertEqual(rows['2']['future'], {'keep': [1, 2]})
        self.assertEqual(self.store.load(self.ident)['audioCues']['sfx']['2'][0]['audioId'], 9)

    def test_nullable_effects_survive_native_audio_and_text_saves(self):
        rows = self.read(); rows['2']['effect'] = None; rows['3'].pop('effect')
        manual = [[1163, 99, 2], [55, 2]]
        rows['4']['effect'] = copy.deepcopy(manual); self.write('TalkCfg', rows)
        result = self.save(audioCues={'sfx': {}, 'bgm': [self.group()]})
        saved = self.read()
        self.assertTrue(result['ok'])
        self.assertEqual(saved['1']['audio'], 7)
        self.assertIsNone(saved['2']['effect'])
        self.assertNotIn('effect', saved['3'])
        self.assertEqual(saved['4']['effect'], manual)
        self.assertEqual(saved['2']['future'], rows['2']['future'])
        self.assertIsNone(b.read_json(Path(result['backup']) / 'Cfgs/zh-cn/TalkCfg.json')['2']['effect'])
        reopened = self.store.load(self.ident)
        changed = {**saved['2'], 'content': 'saved nullable draft'}
        self.save(talkPatch={'version': 1, 'upsert': {'2': changed}, 'deleted': []})
        self.save(audioCues=reopened['audioCues'])
        self.assertEqual(self.read()['2'], changed)
        self.assertNotIn('effect', self.read()['3'])
        self.assertEqual(self.read()['4']['effect'], manual)

    def test_up_commands_initialize_only_the_targeted_nullable_effects(self):
        rows = self.read(); rows['1']['effect'] = None; rows['2']['effect'] = None
        rows['5']['effect'] = None
        manual = [[1163, 99, 2], [55, 2]]
        rows['4']['effect'] = copy.deepcopy(manual); self.write('TalkCfg', rows)
        cues = {'sfx': {'2': [{'audioId': 9}]}, 'bgm': [self.group(loop=False)]}
        self.save(audioCues=cues)
        self.save(audioCues=self.store.load(self.ident)['audioCues'])
        saved = self.read()
        self.assertEqual(saved['1']['effect'], [[1163, 10, 7, 1, -1, 0]])
        self.assertEqual(saved['2']['effect'], [[1163, 3, 9, 1]])
        self.assertIsNone(saved['5']['effect'])
        self.assertEqual(saved['4']['effect'], manual)
        self.assertTrue(all(saved[key]['future'] == rows[key]['future'] for key in rows))

    def test_native_single_music_and_single_sfx_need_no_up(self):
        self.save(audioCues={'sfx': {'1': [{'audioId': 9}]}, 'bgm': []})
        self.assertEqual(self.read()['1']['audio'], 9)
        self.assertEqual(self.read()['1']['effect'], [])
        self.assertFalse((self.project.path / 'BetterAudio/BetterAudio.json').exists())
        self.save(audioCues={'sfx': {}, 'bgm': [self.group()]})
        self.assertEqual(self.read()['1']['audio'], 7)
        self.assertTrue(all(not row['effect'] for row in self.read().values()))

    def test_native_music_and_zero_or_gap_preserve_all_sfx(self):
        rows = self.read(); rows['1']['audio'] = 7; self.write('TalkCfg', rows)
        self.save(audioCues={'sfx': {'1': [{'audioId': 9}], '3': [{'audioId': 9}, {'audioId': 10}],
                                   '5': [{'audioId': 10}]},
                             'bgm': [self.group('continue', 0, [2])]})
        rows = self.read()
        self.assertEqual(rows['1']['audio'], 7)
        self.assertEqual(rows['1']['effect'], [[1163, 3, 9, 1]])
        self.assertEqual(rows['3']['audio'], 0)
        self.assertEqual(rows['3']['effect'], [[1163, 3, 9, 1], [1163, 3, 10, 1]])
        self.assertEqual(rows['5']['audio'], 0)
        self.assertEqual(rows['5']['effect'], [[1163, 3, 10, 1]])

    def test_branch_join_continues_music_with_sfx(self):
        rows = self.read(); rows['1']['nextTalk'] = [2, 3]; rows['2']['nextTalk'] = [4]
        rows['3']['nextTalk'] = [4]; self.write('TalkCfg', rows)
        self.save(audioCues={'sfx': {'3': [{'audioId': 9}], '4': [{'audioId': 10}]},
                             'bgm': [self.group(talks=[1, 2])]})
        rows = self.read()
        self.assertEqual([rows[str(i)]['audio'] for i in range(1, 5)], [7, 0, 0, 0])
        self.assertEqual(rows['3']['effect'], [[1163, 3, 9, 1]])
        self.assertEqual(rows['4']['effect'], [[1163, 3, 10, 1]])

    def test_repeat_remove_shrink_preserve_manual_effects_and_unknown_fields(self):
        rows = self.read(); manual = [[1163, 3, 9, 1], [1163, 99, 2], [55, 2]]
        rows['2']['effect'] = copy.deepcopy(manual); self.write('TalkCfg', rows)
        cues = {'sfx': {'2': [{'audioId': 9}]}, 'bgm': [self.group()], 'futureCues': {'keep': True}}
        self.save(audioCues=cues)
        self.save(audioCues=cues)
        self.assertEqual(self.read()['2']['effect'], manual + [[1163, 3, 9, 1]])
        self.save(audioCues={'sfx': {}, 'bgm': [self.group(talks=[1])]})
        self.assertEqual(self.read()['2']['effect'], manual)
        self.save(audioCues={'sfx': {}, 'bgm': []})
        self.assertEqual(self.read()['2']['effect'], manual)
        self.assertEqual(self.store.load(self.ident)['audioCues']['futureCues'], {'keep': True})

    def test_volume_aliases_keep_source_and_manual_better_audio(self):
        config = self.project.path / 'BetterAudio/BetterAudio.json'; config.parent.mkdir()
        manual = {'audios': [{'id': 777, 'name': 'author', 'audioPath': 'Audio/author.wav', 'future': 'keep'}],
                  'musics': [{'id': 778, 'name': 'legacy author'}], 'future': {'keep': True}}
        config.write_bytes(b.json_bytes(manual)); original = self.read('AudioCfg')
        cues = {'sfx': {'2': [{'audioId': 9, 'volume': .35}, {'audioId': 10, 'volume': 0}]},
                'bgm': [self.group()]}
        result = self.save(audioCues=cues)
        effects = self.read()['2']['effect']; aliases = self.read('AudioCfg')
        better = b.read_json(config)
        for effect, source, volume in zip(effects, (9, 10), (.35, 0)):
            alias = str(effect[2]); self.assertNotEqual(alias, str(source))
            self.assertEqual(aliases[alias], {**original[str(source)], 'id': int(alias)})
            entry = next(e for e in better['audios'] if e['id'] == int(alias))
            self.assertEqual((entry['type'], entry['audioPath'], entry['volume']), (2, '', volume))
        self.assertEqual({k:aliases[k] for k in original}, original)
        self.assertEqual(better['audios'][0], manual['audios'][0])
        self.assertEqual(better['future'], manual['future'])
        self.assertEqual(better['musics'], manual['musics'])
        backup = Path(result['backup'])
        self.assertEqual(b.read_json(backup / 'BetterAudio/BetterAudio.json'), manual)
        self.save(audioCues=cues)
        self.assertEqual(self.read()['2']['effect'], effects)
        self.assertEqual(self.read('AudioCfg'), aliases)
        self.save(audioCues={'sfx': {}, 'bgm': [self.group()]})
        self.assertEqual(self.read('AudioCfg'), original)
        self.assertEqual(b.read_json(config), manual)

    def test_music_volume_once_and_native_transition(self):
        cues = {'sfx': {'2': [{'audioId': 9}]}, 'bgm': [
            self.group('quiet', 7, [1, 2], volume=.4, loop=False),
            self.group('continue', 0, [3]), self.group('normal', 7, [4, 5])]}
        self.save(audioCues=cues)
        rows = self.read(); alias = rows['1']['effect'][0][2]
        self.assertEqual(rows['1']['effect'], [[1163, 10, alias, 1, -1, 0]])
        self.assertEqual(rows['1']['audio'], 0)
        self.assertEqual(rows['2']['effect'], [[1163, 3, 9, 1]])
        self.assertEqual(rows['3']['effect'], [])
        self.assertEqual(rows['4']['audio'], 7)
        self.assertEqual(rows['4']['effect'], [[1163, 99, 1]])
        self.assertEqual(rows['5']['audio'], 0)

    def test_once_music_default_volume_uses_original_id(self):
        self.save(audioCues={'sfx': {}, 'bgm': [self.group(loop=False)]})
        self.assertEqual(self.read()['1']['effect'], [[1163, 10, 7, 1, -1, 0]])
        self.assertFalse((self.project.path / 'BetterAudio/BetterAudio.json').exists())

    def test_legacy_cues_upgrade_on_audio_edit_and_external_audio_edit_wins(self):
        rows = self.read(); rows['1']['audio'] = 7; self.write('TalkCfg', rows)
        path = self.project.path / 'StudentAgeStudio/audio-cues.json'; path.parent.mkdir(exist_ok=True)
        path.write_bytes(b.json_bytes({'version': 1, 'sfx': {'2': [{'audioId': 9}]}, 'bgm': [self.group()]}))
        with patch('native_audio.export', side_effect=AssertionError('legacy text must not rebuild audio')), \
             patch.object(self.store, 'story_save_maps', side_effect=AssertionError('legacy text must not load tables')):
            self.save(talkPatch={'version': 1, 'upsert': {'2': {**rows['2'], 'content': 'text first'}}, 'deleted': []})
        self.assertEqual(self.read()['2']['effect'], [])
        self.save(audioCues=b.read_json(path))
        self.assertEqual(self.read()['2']['effect'], [[1163, 3, 9, 1]])
        rows = self.read(); rows['2']['audio'] = 8; self.write('TalkCfg', rows)
        self.assertNotIn('2', self.store.load(self.ident)['audioCues']['sfx'])
        self.save(talkPatch={'version': 1, 'upsert': {'3': {**rows['3'], 'content': 'after external edit'}}, 'deleted': []})
        self.assertEqual(self.read()['2']['audio'], 8)
        self.assertEqual(self.read()['2']['effect'], [])

    def test_delete_and_renumber_do_not_duplicate_owned_commands(self):
        self.save(audioCues={'sfx': {'2': [{'audioId': 9}]}, 'bgm': [self.group()]})
        rows = self.read(); row = rows.pop('2'); row['id'] = 20; rows['20'] = row
        rows['1']['nextTalk'] = [20]
        cues = self.store.load(self.ident)['audioCues']; cues['sfx']['20'] = cues['sfx'].pop('2')
        cues['bgm'][0]['talkIds'] = [1, 20, 3]
        self.save(talks=rows, audioCues=cues, idMappings={'TalkCfg': {'2': 20}}, deletedIds=[2], replacements={'2': [20]})
        self.assertEqual(self.read()['20']['effect'], [[1163, 3, 9, 1]])
        self.save(talkPatch={'version': 1, 'upsert': {}, 'deleted': [20]})
        self.assertNotIn('20', self.read())
        self.assertNotIn('20', self.store.load(self.ident)['audioCues']['upAudio']['effects'])

    def test_manual_edit_to_generated_command_is_preserved(self):
        self.save(audioCues={'sfx': {'2': [{'audioId': 9}]}, 'bgm': [self.group()]})
        rows = self.read(); rows['2']['effect'][0][2] = 10; self.write('TalkCfg', rows)
        self.save(audioCues={'sfx': {}, 'bgm': [self.group()]})
        self.assertEqual(self.read()['2']['effect'], [[1163, 3, 10, 1]])

    def test_companion_revision_rejects_external_change(self):
        self.save(audioCues={'sfx': {'2': [{'audioId': 9, 'volume': .35}]}, 'bgm': [self.group()]})
        revision = self.store.revision(self.project)
        config = self.project.path / 'BetterAudio/BetterAudio.json'
        data = b.read_json(config); data['future'] = 'external'; config.write_bytes(b.json_bytes(data))
        before = (self.cfg / 'TalkCfg.json').read_bytes()
        with self.assertRaises(b.ApiError) as error:
            self.store.save({'projectId': self.ident, 'revision': revision, 'audioCues': {'sfx': {}, 'bgm': []}})
        self.assertEqual(error.exception.status, 409)
        self.assertEqual((self.cfg / 'TalkCfg.json').read_bytes(), before)

    def test_invalid_sound_type_uses_existing_confirmable_warning_flow(self):
        import save_review
        before = (self.cfg / 'TalkCfg.json').read_bytes()
        payload = {'projectId': self.ident, 'revision': self.store.revision(self.project),
                   'audioCues': {'sfx': {'1': [{'audioId': 7}]}, 'bgm': []}}
        with self.assertRaises(b.ApiError) as error: save_review.perform(self.store.save, payload, b.ApiError)
        self.assertEqual(error.exception.code, 'save_warnings')
        self.assertEqual((self.cfg / 'TalkCfg.json').read_bytes(), before)
        payload['_confirmedSaveWarnings'] = error.exception.warnings
        result = save_review.perform(self.store.save, payload, b.ApiError)
        self.assertTrue(result['ok'])

    def test_compiled_text_only_edit_retains_fast_path(self):
        self.save(audioCues={'sfx': {'2': [{'audioId': 9}]}, 'bgm': [self.group()]})
        row = self.read()['2']; row['content'] = 'text only'
        with patch('native_audio.export', side_effect=AssertionError('compiled text must not rebuild audio')), \
             patch.object(self.store, 'story_save_maps', side_effect=AssertionError('compiled text must not load tables')):
            self.save(talkPatch={'version': 1, 'upsert': {'2': row}, 'deleted': []})
        self.assertEqual(self.read()['2']['effect'], [[1163, 3, 9, 1]])
        self.assertEqual(self.read()['2']['content'], 'text only')

    def test_warm_text_saves_do_not_decode_other_audio_snapshot_rows(self):
        import json
        rows = {str(i): {'id': i, 'content': 'line ' + str(i), 'audio': 0,
                         'nextTalk': [i + 1] if i < 5000 else [], 'effect': []}
                for i in range(1, 5001)}
        self.write('TalkCfg', rows)
        self.save(audioCues={'sfx': {}, 'bgm': [self.group(talks=range(1, 5001))]})
        changed = self.read()['1']
        changed['content'] = 'warm anchor'
        self.save(talkPatch={'version': 1, 'upsert': {'1': changed}, 'deleted': []})
        decoded_rows = []
        decode = json.loads
        def counted(raw, *args, **kwargs):
            value = decode(raw, *args, **kwargs)
            if isinstance(value, dict) and type(value.get('id')) is int and 'audio' in value:
                decoded_rows.append(value['id'])
            return value
        with patch('up_audio.json.loads', side_effect=counted), \
             patch.object(self.store, 'story_save_maps', side_effect=AssertionError('warm text must not load tables')):
            for number in range(3):
                changed['content'] = 'warm text ' + str(number)
                self.save(talkPatch={'version': 1, 'upsert': {'1': changed}, 'deleted': []})
        self.assertEqual(len(decoded_rows), 3)
        self.assertEqual(set(decoded_rows), {1})
        # A concurrent edit after commit must not acquire the text transaction's
        # verified anchor, even though the writer returns the new revision.
        commit = self.store.commit
        def external_edit_after_commit(*args, **kwargs):
            result = commit(*args, **kwargs)
            external = self.read(); external['2']['audio'] = 8
            self.write('TalkCfg', external)
            return result
        with patch.object(self.store, 'commit', side_effect=external_edit_after_commit):
            changed['content'] = 'concurrent edit'
            self.save(talkPatch={'version': 1, 'upsert': {'1': changed}, 'deleted': []})
        current = self.read()['3']; current['content'] = 'after concurrent edit'
        self.save(talkPatch={'version': 1, 'upsert': {'3': current}, 'deleted': []})
        self.assertEqual(self.read()['2']['audio'], 8)
        self.assertNotIn(2, self.store.load(self.ident)['audioCues']['bgm'][0]['talkIds'])

    def test_confirmed_missing_sound_reference_keeps_draft_readable(self):
        import save_review
        payload = {'projectId': self.ident, 'revision': self.store.revision(self.project),
                   'audioCues': {'sfx': {'1': [{'audioId': 12345, 'volume': .3}]}, 'bgm': []}}
        with self.assertRaises(b.ApiError) as error: save_review.perform(self.store.save, payload, b.ApiError)
        payload['_confirmedSaveWarnings'] = error.exception.warnings
        self.assertTrue(save_review.perform(self.store.save, payload, b.ApiError)['ok'])
        self.assertEqual(self.read()['1']['effect'], [[1163, 3, 12345, 1]])
        cues = b.read_json(self.project.path / 'StudentAgeStudio/audio-cues.json')
        self.assertEqual(cues['sfx']['1'][0]['volume'], .3)
        self.assertEqual(cues['upAudio']['aliases'], {})
        self.assertFalse((self.project.path / 'BetterAudio/BetterAudio.json').exists())

    def test_large_source_id_gets_float_exact_alias_for_up(self):
        audios = self.read('AudioCfg'); audios['16777217'] = {'id': 16777217, 'type': 2, 'url': 'sound/high', 'volumn': .6}
        self.write('AudioCfg', audios)
        self.save(audioCues={'sfx': {'2': [{'audioId': 16777217}]}, 'bgm': [self.group()]})
        alias = self.read()['2']['effect'][0][2]
        self.assertNotEqual(alias, 16777217)
        self.assertLess(alias, 16777216)
        entry = b.read_json(self.project.path / 'BetterAudio/BetterAudio.json')['audios'][0]
        self.assertEqual(entry['volume'], .6)

    def test_alias_referenced_by_author_is_kept_until_reference_removed(self):
        self.save(audioCues={'sfx': {'2': [{'audioId': 9, 'volume': .35}]}, 'bgm': [self.group()]})
        alias = self.read()['2']['effect'][0][2]
        self.write('FutureCfg', {'1': {'id': 1, 'audio': alias}})
        self.save(audioCues={'sfx': {}, 'bgm': [self.group()]})
        self.assertIn(str(alias), self.read('AudioCfg'))
        self.assertEqual(self.read()['2']['effect'], [])
        self.write('FutureCfg', {})
        self.save(audioCues={'sfx': {}, 'bgm': [self.group()]})
        self.assertNotIn(str(alias), self.read('AudioCfg'))

    def test_manual_float_effect_reference_keeps_audio_alias(self):
        self.save(audioCues={'sfx': {'2': [{'audioId': 9, 'volume': .35}]}, 'bgm': [self.group()]})
        alias = self.read()['2']['effect'][0][2]
        rows = self.read(); rows['5']['effect'] = [[1163, 3, float(alias), 1]]
        self.write('TalkCfg', rows)
        self.save(audioCues={'sfx': {}, 'bgm': [self.group()]})
        self.assertIn(str(alias), self.read('AudioCfg'))
        better = b.read_json(self.project.path / 'BetterAudio/BetterAudio.json')
        self.assertTrue(any(entry['id'] == alias for entry in better['audios']))
        self.assertEqual(self.read()['5']['effect'], [[1163, 3, float(alias), 1]])
        rows = self.read(); rows['5']['effect'] = []; self.write('TalkCfg', rows)
        self.save(audioCues={'sfx': {}, 'bgm': [self.group()]})
        self.assertNotIn(str(alias), self.read('AudioCfg'))

    def test_alias_and_companion_transaction_roll_back_together(self):
        config = self.project.path / 'BetterAudio/BetterAudio.json'; config.parent.mkdir()
        manual = {'audios': [], 'future': 'keep'}; config.write_bytes(b.json_bytes(manual))
        before = {path: path.read_bytes() for path in (config, self.cfg / 'AudioCfg.json', self.cfg / 'TalkCfg.json')}
        replace = b.os.replace
        def failing(source, destination):
            if Path(destination) == self.cfg / 'TalkCfg.json' and str(source).endswith('.tmp'):
                raise OSError('fixture failed final dialogue replacement')
            return replace(source, destination)
        with patch.object(b.os, 'replace', side_effect=failing), self.assertRaises(OSError):
            self.save(audioCues={'sfx': {'2': [{'audioId': 9, 'volume': .35}]}, 'bgm': [self.group()]})
        for path, data in before.items(): self.assertEqual(path.read_bytes(), data)
        self.assertFalse((self.project.path / 'StudentAgeStudio/audio-cues.json').exists())


if __name__ == '__main__':
    unittest.main()
