"""Ending parts follow the game's playing order: stages, type-1 chaining, consecutive ids and direct jumps."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ending_rules
import server
import studio_agent

# Shaped like the original table: NPC endings (type 1) in stages 2, 3 and 5, job stories (type 0) in stages 4 and 6.
ORIGINAL = {
    '800301001': {'id': 800301001, 'step': 2, 'type': 1}, '800301002': {'id': 800301002, 'step': 0, 'type': 1},
    '804901001': {'id': 804901001, 'step': 3, 'type': 1},
    '810103001': {'id': 810103001, 'step': 5, 'type': 1},
    '30101009': {'id': 30101009, 'step': 4, 'job': 1}, '30101013': {'id': 30101013, 'step': 6, 'job': 1},
    '20001001': {'id': 20001001, 'step': 45, 'type': 0},
}


def notes(mod, targets=(), originals=ORIGINAL):
    places = {}
    found = ending_rules.problems(mod, {**ORIGINAL, **mod}, targets, originals, places)
    return {note['id']: note for note in found}, places


class EndingRulesTests(unittest.TestCase):
    def test_a_story_made_like_the_games_own_editor_plays(self):
        mod = {'1400000': {'step': 3, 'type': 1}, '1400001': {'step': 0, 'type': 1}, '1400002': {'step': 0, 'type': 1}}
        found, places = notes(mod)
        self.assertEqual(found, {})
        self.assertIn('阶段 3', places[1400000])
        self.assertIn('其他人物结局依次出现', places[1400000])
        self.assertIn('接在段落 1400001 后面', places[1400002])

    def test_parts_the_game_never_reaches(self):
        mod = {'1490563': {'step': 0, 'type': 0}, '1490564': {'step': 0, 'type': 1},
               '1500000': {'step': 1, 'type': 1}, '1600000': {'step': 9, 'type': 1}}
        found, places = notes(mod)
        self.assertIn('没有编号为 1490562 的上一段', found[1490563]['problem'])
        self.assertIn('接在段落 1490563 后面', found[1490564]['problem'])
        self.assertIn('阶段 1', found[1500000]['problem'])
        self.assertIn('阶段 9', found[1600000]['problem'])
        self.assertTrue(all('fix' not in note for note in found.values()), '这些问题需要作者选择阶段或编号')
        self.assertEqual(places, {})

    def test_type_zero_in_an_npc_stage_is_fixed_to_type_one(self):
        mod = {'1400000': {'step': 2, 'type': 0}, '1400001': {'step': 0, 'type': 0}}
        found, _ = notes(mod)
        self.assertEqual(found[1400000]['fix'], {'type': 1})
        self.assertIn('通常不会出现', found[1400000]['problem'])
        self.assertIn('类型不是 1', found[1400001]['problem'])
        found, _ = notes({'1400000': {'step': 2, 'type': 1}, '1400001': {'step': 0, 'type': 0}})
        self.assertEqual(found[1400001]['fix'], {'type': 1}, '最后一段为 0 时同阶段其他人物结局不再出现')
        found, _ = notes({'1400000': {'step': 2, 'type': 1}, '1400001': {'step': 0, 'type': 0}, '1400002': {'step': 0, 'type': 1}})
        self.assertNotIn(1400001, found, '中间段落的类型不影响后续播放')

    def test_first_match_stages_explain_that_original_parts_come_first(self):
        found, _ = notes({'1400000': {'step': 4, 'type': 1}, '1500000': {'step': 45, 'type': 0}, '1600000': {'step': 7, 'type': 0}})
        self.assertIn('游戏原有段落排在前面', found[1400000]['problem'])
        self.assertIn('游戏原有段落排在前面', found[1500000]['problem'])
        self.assertNotIn(1600000, found, '原版没有阶段 7 的段落')
        found, _ = notes({'30101009': {'step': 4, 'job': 1, 'desc': '改写'}})
        self.assertEqual(found, {}, '覆盖原版段落不需要提示')

    def test_jumps_open_parts_directly(self):
        targets = ending_rules.jump_targets({'1': {'part': 1400010}}, {'2': {'jump': 1400020}}, {'3': {'result': [[0, 1400030, 1]]}})
        self.assertEqual(targets, {1400010, 1400020, 1400030})
        mod = {'1400010': {'step': 0, 'type': 0}, '1400011': {'step': 0, 'type': 0},
               '1400020': {'step': 0, 'type': 1}, '1400030': {'step': 1, 'type': 0}}
        found, places = notes(mod, targets)
        self.assertEqual(found, {})
        self.assertIn('直接跳到这一段', places[1400010])
        self.assertIn('接在段落 1400010 后面', places[1400011])

    def test_a_new_stage_after_consecutive_ids_starts_its_own_story(self):
        found, places = notes({'1400000': {'step': 3, 'type': 1}, '1400001': {'step': 5, 'type': 1}})
        self.assertEqual(found, {})
        self.assertIn('阶段 5', places[1400001])


class EndingCheckTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='studio-ending-test-')
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        env = {k: str(root / v) for k, v in [('STUDIO_USER_DATA_ROOT', 'User'), ('STUDIO_CACHE_ROOT', 'Cache'), ('STUDIO_BACKUP_ROOT', 'Backups'),
                                             ('STUDIO_DISPLAY_SETTINGS', 'display.json'), ('STUDIO_ERROR_LOG_ROOT', 'Logs')]}
        patcher = patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.store = server.StudioStore(root / 'Mods', root / 'Workshop', root / 'Game', asset_settings_path=root / 'assets.json', migrate_cache=False)
        self.mod = self.store.create('结局测试')['id']
        self.cfgs = Path(self.store.project(self.mod).path) / 'Cfgs' / 'zh-cn'
        self.cfgs.mkdir(parents=True, exist_ok=True)

    def write(self, name, rows):
        (self.cfgs / (name + '.json')).write_text(json.dumps(rows, ensure_ascii=False), encoding='utf-8')

    def test_check_reads_saved_parts_options_and_unsaved_rows(self):
        self.write('EndingPartCfg', {'1490563': {'id': 1490563, 'step': 0, 'type': 0}, '1500000': {'id': 1500000, 'step': 0, 'type': 0}})
        self.write('EndingOptionCfg', {'1500001': {'id': 1500001, 'part': 1500000}})
        with patch.object(self.store, 'catalog_rows', lambda name, catalog=None: ORIGINAL if name == 'EndingPartCfg' else {}):
            result = ending_rules.check(self.store, {'projectId': self.mod}, server)
            self.assertEqual([note['id'] for note in result['notes']], [1490563])
            self.assertIn('1500000', result['places'])
            unsaved = ending_rules.check(self.store, {'projectId': self.mod, 'rows': {'1490563': {'id': 1490563, 'step': 3, 'type': 1}}}, server)
            self.assertEqual(unsaved['notes'], [])
            studio = studio_agent.Studio.__new__(studio_agent.Studio)
            studio.store = self.store
            issues = [issue for issue in studio.check_mod(self.mod)['issues'] if 'ending' in issue]
            self.assertEqual([issue['ending'] for issue in issues], [1490563])


if __name__ == '__main__':
    unittest.main()
