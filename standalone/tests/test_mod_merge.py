"""Merging mods: sources untouched, conflicts reported and resolved by choice, paths remapped."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server as b
import mod_merge


class ModMergeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        env = patch.dict(os.environ, {'STUDIO_CACHE_ROOT': str(self.root / 'Cache'), 'STUDIO_USER_DATA_ROOT': str(self.root / 'User')}); env.start(); self.addCleanup(env.stop)
        (self.root / 'Game').mkdir()
        self.store = b.StudioStore(self.root / 'Mods', self.root / 'Workshop', self.root / 'Game', asset_settings_path=self.root / 'assets.json')
        self.a = self.store.project(self.store.create('甲')['id']); self.b = self.store.project(self.store.create('乙')['id'])
        self.write(self.a, 'PersonCfg', {'3': {'id': 3, 'name': '小红', 'url': ['Mods/' + self.a.package + '/Textures/Role/hong.png']}, '4': {'id': 4, 'name': '甲独有'}})
        self.write(self.b, 'PersonCfg', {'3': {'id': 3, 'name': '小红（乙版）', 'url': ['Mods/' + self.b.package + '/Textures/Role/hong.png']}, '5': {'id': 5, 'name': '乙独有'}})
        self.write(self.a, 'EvtCfg', {'1500000': {'id': 1500000, 'title': '甲事件', 'talkId': [1500000001]}})
        self.write(self.b, 'EvtCfg', {'1500000': {'id': 1500000, 'title': '甲事件', 'talkId': [1500000001]}, '1600000': {'id': 1600000, 'title': '乙事件', 'talkId': []}})
        (self.a.path / 'Textures/Role/hong.png').write_bytes(b'AAA'); (self.b.path / 'Textures/Role/hong.png').write_bytes(b'BBBB')
        (self.a.path / 'Textures/Bg/only-a.png').write_bytes(b'bg')
        (self.a.path / 'StudentAgeStudio').mkdir(exist_ok=True); (self.b.path / 'StudentAgeStudio').mkdir(exist_ok=True)
        (self.a.path / 'StudentAgeStudio/editor-state.json').write_bytes(b.json_bytes({'order': [1500000001], 'premises': {'1': {'id': 1, 'name': '甲前提', 'talkId': 1500000001}}}))
        (self.b.path / 'StudentAgeStudio/editor-state.json').write_bytes(b.json_bytes({'order': [1600000001], 'premises': {'1': {'id': 1, 'name': '乙前提', 'talkId': 1600000001}}}))
        self.snapshot = {p: p.read_bytes() for proj in (self.a, self.b) for p in proj.path.rglob('*') if p.is_file()}

    def write(self, project, name, rows):
        (project.path / 'Cfgs/zh-cn' / (name + '.json')).write_bytes(b.json_bytes(rows))

    def test_preview_reports_person_record_and_file_conflicts_only_where_content_differs(self):
        report = mod_merge.preview(self.store, [self.a.id, self.b.id])
        kinds = {(c['kind'], c['table'], c['id']) for c in report['conflicts']}
        self.assertEqual(kinds, {('person', 'PersonCfg', '3'), ('file', '', 'Textures/Role/hong.png')})  # identical event 1500000 is not a conflict
        person = next(c for c in report['conflicts'] if c['kind'] == 'person')
        self.assertEqual([o['name'] for o in person['options']], ['小红', '小红（乙版）'])
        with self.assertRaises(b.ApiError): mod_merge.preview(self.store, [self.a.id])

    def test_merge_creates_a_new_mod_with_the_union_and_chosen_versions(self):
        result = mod_merge.merge(self.store, [self.a.id, self.b.id], {'person:PersonCfg:3': self.b.id, 'file::Textures/Role/hong.png': self.b.id}, '合并测试')
        merged = self.store.project(result['id'])
        persons = json.loads((merged.path / 'Cfgs/zh-cn/PersonCfg.json').read_text(encoding='utf-8'))
        self.assertEqual({k: v['name'] for k, v in persons.items()}, {'3': '小红（乙版）', '4': '甲独有', '5': '乙独有'})
        self.assertEqual(persons['3']['url'], ['Mods/' + merged.package + '/Textures/Role/hong.png'])  # path points at the merged mod
        events = json.loads((merged.path / 'Cfgs/zh-cn/EvtCfg.json').read_text(encoding='utf-8'))
        self.assertEqual(set(events), {'1500000', '1600000'})
        self.assertEqual((merged.path / 'Textures/Role/hong.png').read_bytes(), b'BBBB')
        self.assertTrue((merged.path / 'Textures/Bg/only-a.png').is_file())
        state = json.loads((merged.path / 'StudentAgeStudio/editor-state.json').read_text(encoding='utf-8'))
        self.assertEqual(state['order'], [1500000001, 1600000001])
        self.assertEqual(sorted(p['name'] for p in state['premises'].values()), ['乙前提', '甲前提'])
        self.assertEqual(result['name'], '合并测试')
        # Sources are byte-for-byte unchanged.
        self.assertEqual(self.snapshot, {p: p.read_bytes() for proj in (self.a, self.b) for p in proj.path.rglob('*') if p.is_file()})


if __name__ == '__main__':
    unittest.main()
