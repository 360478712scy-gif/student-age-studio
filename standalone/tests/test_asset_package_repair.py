"""Synthetic regression tests for stale native asset package references."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import asset_package_repair as m
import config_doctor as doctor
import server as api


class AssetPackageBytesTests(unittest.TestCase):
    def test_preserves_bom_whitespace_numbers_and_unowned_strings(self):
        raw = b'\xef\xbb\xbf' + b'{\r\n "1": {"id":1,"url":"Mods/old/Textures/a.png", "content":"Mods/old/Textures/a.png", "future":{"url":"Mods/old/Textures/a.png","n":1e+003}}\r\n}\n'
        result, count = m.rewrite(raw, 'BgCfg.json', 'new', lambda _: True)
        self.assertEqual(count, 1)
        self.assertEqual(result, raw.replace(b'"url":"Mods/old/Textures/a.png"', b'"url":"Mods/new/Textures/a.png"', 1))
        self.assertEqual(m.rewrite(result, 'BgCfg.json', 'new', lambda _: True), (None, 0))

    def test_all_known_fields_and_slash_styles(self):
        expected = {'BgCfg.json': {'url'}, 'CGCfg.json': {'urls'}, 'ModFaceCfg.json': {'icon', 'icon_xx'},
                    'PersonCfg.json': {'url', 'url2'}, 'KZoneContentCfg.json': {'imgs'},
                    'KZoneAvatarCfg.json': {'icon'}, 'ItemCfg.json': {'icon'}, 'AudioCfg.json': {'url'}}
        self.assertEqual(m.FIELDS, expected)
        for filename, fields in expected.items():
            for separator in ('/', '\\'):
                with self.subTest(filename=filename, separator=separator):
                    old = separator.join(('Mods', 'old', 'Audios' if filename == 'AudioCfg.json' else 'Textures', 'a.png'))
                    row = {'id': 1, **{f: [old, old] if f in {'urls', 'imgs'} else old for f in fields}}
                    result, count = m.rewrite(json.dumps({'1': row}).encode(), filename, '新包', lambda _: True)
                    parsed = json.loads(result)['1']
                    for field in fields:
                        new = old.replace('old', '新包')
                        self.assertEqual(parsed[field], [new, new] if isinstance(row[field], list) else new)
                    self.assertEqual(count, sum(2 if isinstance(row[f], list) else 1 for f in fields))

    def test_dependency_references_untouched_except_explicit_local_rename(self):
        raw = b'{"1":{"id":1,"urls":["Mods/old/Textures/a.png","Mods/foreign/Textures/a.png"]}}'
        self.assertEqual(m.rewrite(raw, 'CGCfg.json', 'new', lambda _: True, dependencies=True), (None, 0))
        result, count = m.rewrite(raw, 'CGCfg.json', 'new', lambda _: True, dependencies=True, old_package='old')
        self.assertEqual(count, 1)
        self.assertEqual(result, raw.replace(b'Mods/old/', b'Mods/new/'))

    def test_missing_traversal_unknown_root_and_current_package_untouched(self):
        for value in ('Mods/old/Textures/missing.png', 'Mods/old/Textures/../a.png',
                      'Mods/old//Textures/a.png', 'Mods/old/Cfgs/a.png', 'Mods/NEW/Textures/a.png', 'Textures/a.png'):
            with self.subTest(value=value):
                raw = json.dumps({'1': {'id': 1, 'url': value}}).encode()
                self.assertEqual(m.rewrite(raw, 'BgCfg.json', 'new', lambda p: 'missing' not in p), (None, 0))

    def test_nested_or_mixed_asset_shapes_are_untouched(self):
        raw = b'{"1":{"id":1,"urls":["Mods/old/Textures/a.png"]},"2":{"id":2,"urls":[{"url":"Mods/old/Textures/a.png"},"Mods/old/Textures/a.png"]}}'
        result, count = m.rewrite(raw, 'CGCfg.json', 'new', lambda _: True)
        self.assertEqual(count, 1)
        self.assertEqual(result, raw.replace(b'Mods/old/', b'Mods/new/', 1))

    def test_invalid_duplicate_and_unknown_tables_never_partially_repair(self):
        for raw in (b'{"1":{"url":"Mods/old/Textures/a.png",}}',
                    b'{"1":{"url":"Mods/old/Textures/a.png","url":"other"}}',
                    b'{"1":{"url":"Mods/old/Textures/a.png"},"1":{}}', b'{} trailing', b'\xff'):
            with self.subTest(raw=raw), self.assertRaises((ValueError, UnicodeError)):
                m.rewrite(raw, 'BgCfg.json', 'new', lambda _: True)
        raw = b'{"1":{"url":"Mods/old/Textures/a.png"}}'
        self.assertEqual(m.rewrite(raw, 'UnknownCfg.json', 'new', lambda _: True), (None, 0))


class AssetPackageDiskTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        env = patch.dict(os.environ, {'STUDIO_CACHE_ROOT': str(self.root/'Cache'),
                        'STUDIO_USER_DATA_ROOT': str(self.root/'User'), 'STUDIO_BACKUP_ROOT': str(self.root/'Backups')})
        env.start(); self.addCleanup(env.stop)
        self.store = api.StudioStore(self.root/'Mods', self.root/'Workshop', self.root/'Game',
                                    asset_settings_path=self.root/'assets.json', migrate_cache=False)
        self.addCleanup(self.store.close)
        self.project = self.store.project(self.store.create('asset-repair-test')['id'])
        asset = self.project.path/'Textures/Bg/a.png'; asset.parent.mkdir(parents=True, exist_ok=True)
        asset.write_bytes(b'synthetic image placeholder')
        self.path = self.project.path/'Cfgs/zh-cn/BgCfg.json'
        self.raw = b'\xef\xbb\xbf{"1":{"id":1,"url":"Mods/old/Textures/Bg/a.png","future":1e+003}}\n'
        self.path.write_bytes(self.raw)

    def check(self):
        return doctor.check(self.store, {'projectId': self.project.id}, api)

    def repair(self, state):
        return doctor.repair(self.store, {'projectId': self.project.id, 'revision': state['revision'], 'scanToken': state['scanToken']}, api)

    def test_readonly_check_backed_up_repair_and_idempotence(self):
        before = self.store.revision(self.project)
        state = self.check()
        self.assertEqual(self.path.read_bytes(), self.raw)
        self.assertEqual(self.store.revision(self.project), before)
        self.assertEqual(state['repairable'], 1)
        result = self.repair(state)
        self.assertEqual(result['fixed'], ['Cfgs/zh-cn/BgCfg.json'])
        self.assertEqual((Path(result['backup'])/'Cfgs/zh-cn/BgCfg.json').read_bytes(), self.raw)
        self.assertEqual(json.loads(self.path.read_bytes().decode('utf-8-sig'))['1']['url'], 'Mods/'+self.project.package+'/Textures/Bg/a.png')
        self.assertNotEqual(result['revision'], before)
        with patch.object(self.store, 'commit', side_effect=AssertionError('idempotent repair must not commit')):
            again = self.repair(self.check())
        self.assertEqual(again['fixed'], []); self.assertIsNone(again['backup'])

    def test_revision_and_token_conflicts_do_not_write(self):
        for key in ('revision', 'scanToken'):
            with self.subTest(key=key):
                state = self.check(); state[key] = 'stale'
                with self.assertRaises(api.ApiError) as caught:
                    self.repair(state)
                self.assertEqual(caught.exception.status, 409)
                self.assertEqual(self.path.read_bytes(), self.raw)

    def test_external_change_after_check_is_preserved(self):
        state = self.check()
        external = self.raw.replace(b'1e+003', b'2e+003'); self.path.write_bytes(external)
        with self.assertRaises(api.ApiError) as caught:
            self.repair(state)
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(self.path.read_bytes(), external)

    def test_manifest_rename_updates_local_paths_and_backups_atomically(self):
        import save_review
        current = self.project.package
        source = self.raw.replace(b'Mods/old/', ('Mods/'+current+'/').encode())
        self.path.write_bytes(source)
        cg = self.path.with_name('CGCfg.json')
        foreign = b'{"2":{"id":2,"urls":["Mods/foreign/Textures/Bg/a.png"]}}'
        cg.write_bytes(foreign)
        manifest = self.project.path/'manifest.json'
        original_manifest = manifest.read_bytes()
        payload = {'projectId': self.project.id, 'revision': self.store.revision(self.project),
                   'manifest': {'metadata': {'packageId': 'renamed'}, 'dependencies': ['foreign']}}
        result = save_review.perform(self.store.manifest_save, payload, api.ApiError)
        self.assertEqual(result['assetPathsRepaired'], 1)
        self.assertEqual(self.path.read_bytes(), source.replace(('Mods/'+current+'/').encode(), b'Mods/renamed/'))
        self.assertEqual(cg.read_bytes(), foreign)
        self.assertEqual(json.loads(manifest.read_bytes())['metadata']['packageId'], 'renamed')
        self.assertEqual((Path(result['backup'])/'manifest.json').read_bytes(), original_manifest)
        self.assertEqual((Path(result['backup'])/'Cfgs/zh-cn/BgCfg.json').read_bytes(), source)

    def test_manifest_rename_with_invalid_asset_table_aborts_without_changes(self):
        import save_review
        manifest = self.project.path/'manifest.json'
        before = manifest.read_bytes()
        broken = b'{"1":{"id":1,"url":"Mods/old/Textures/Bg/a.png",}}'
        self.path.write_bytes(broken)
        payload = {'projectId': self.project.id, 'revision': self.store.revision(self.project),
                   'manifest': {'metadata': {'packageId': 'renamed'}}}
        with self.assertRaises(api.ApiError):
            save_review.perform(self.store.manifest_save, payload, api.ApiError)
        self.assertEqual(manifest.read_bytes(), before)
        self.assertEqual(self.path.read_bytes(), broken)

    def test_bad_manifest_does_not_disable_json_doctor(self):
        manifest = self.project.path/'manifest.json'
        missing_comma = b'{"title":"synthetic"\n "metadata":{"packageId":"new"}}'
        manifest.write_bytes(missing_comma)
        state = self.check()
        self.assertTrue(any(issue['path'] == 'manifest.json' and issue['fixable'] for issue in state['issues']))
        self.assertFalse(any(issue['path'] == 'Cfgs/zh-cn/BgCfg.json' and issue['fixable'] for issue in state['issues']))
        result = self.repair(state)
        self.assertEqual(result['fixed'], ['manifest.json'])
        self.assertEqual(json.loads(manifest.read_bytes())['title'], 'synthetic')
        self.assertEqual((Path(result['backup'])/'manifest.json').read_bytes(), missing_comma)
        self.assertEqual(self.path.read_bytes(), self.raw)

    def test_array_manifest_keeps_json_doctor_available_and_assets_untouched(self):
        manifest = self.project.path/'manifest.json'
        manifest.write_bytes(b'[]')
        broken_table = self.path.with_name('CustomKeyMap.json')
        broken_table.write_bytes(b'{"first":1\n "second":2}')
        state = self.check()
        self.assertTrue(any(issue['path'].endswith('CustomKeyMap.json') and issue['fixable'] for issue in state['issues']))
        result = self.repair(state)
        self.assertEqual(result['fixed'], ['Cfgs/zh-cn/CustomKeyMap.json'])
        self.assertEqual(json.loads(broken_table.read_bytes()), {'first': 1, 'second': 2})
        self.assertEqual(manifest.read_bytes(), b'[]')
        self.assertEqual(self.path.read_bytes(), self.raw)

    def test_manifest_rename_rejects_invalid_package_ids_without_writes(self):
        import save_review
        manifest = self.project.path/'manifest.json'
        before = manifest.read_bytes()
        for package in ('/', chr(92), '.', '..', 'nested/name', 'nested'+chr(92)+'name',
                        'bad'+chr(0)+'name', 'bad'+chr(10)+'name', 'bad'+chr(31)+'name'):
            with self.subTest(package=repr(package)):
                payload = {'projectId': self.project.id, 'revision': self.store.revision(self.project),
                           'manifest': {'metadata': {'packageId': package}}}
                with self.assertRaises(api.ApiError):
                    save_review.perform(self.store.manifest_save, payload, api.ApiError)
                self.assertEqual(manifest.read_bytes(), before)
                self.assertEqual(self.path.read_bytes(), self.raw)

    def test_dependency_manifest_keeps_foreign_reference(self):
        manifest = self.project.path/'manifest.json'
        data = json.loads(manifest.read_text(encoding='utf-8')); data['dependencies'] = ['old']
        manifest.write_text(json.dumps(data), encoding='utf-8')
        self.assertEqual(self.check()['repairable'], 0)
        self.assertEqual(self.path.read_bytes(), self.raw)

    def test_missing_and_escaping_symlink_are_not_repaired(self):
        asset = self.project.path/'Textures/Bg/a.png'; asset.unlink()
        self.assertEqual(self.check()['repairable'], 0)
        outside = self.root/'outside.png'; outside.write_bytes(b'outside')
        try: asset.symlink_to(outside)
        except OSError: self.skipTest('symlinks unavailable')
        self.assertEqual(self.check()['repairable'], 0)
        self.assertEqual(self.path.read_bytes(), self.raw)


if __name__ == '__main__':
    unittest.main()
