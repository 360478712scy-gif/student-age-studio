"""While the game cache is written the disk is slow: listings must not hold the locks every other request needs."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


class CacheResponsivenessTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='studio-responsive-test-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        env = {k: str(self.root / v) for k, v in [('STUDIO_USER_DATA_ROOT', 'User'), ('STUDIO_CACHE_ROOT', 'Cache'), ('STUDIO_BACKUP_ROOT', 'Backups'),
                                                  ('STUDIO_DISPLAY_SETTINGS', 'display.json'), ('STUDIO_ERROR_LOG_ROOT', 'Logs')]}
        patcher = patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.store = server.StudioStore(self.root / 'Mods', self.root / 'Workshop', self.root / 'Game', asset_settings_path=self.root / 'assets.json', migrate_cache=False)
        self.mod = self.store.create('响应测试')['id']
        self.cfgs = Path(self.store.project(self.mod).path) / 'Cfgs' / 'zh-cn'
        self.cfgs.mkdir(parents=True, exist_ok=True)
        (self.cfgs / 'ItemCfg.json').write_text('{"1700001": {"id": 1700001}}', encoding='utf-8')

    def test_config_links_are_still_refused(self):
        outside = self.root / 'outside.json'
        outside.write_text('{}', encoding='utf-8')
        try:
            (self.cfgs / 'Linked.json').symlink_to(outside)
        except OSError:
            self.skipTest('这台机器不能创建符号链接')
        with self.assertRaises(server.ApiError) as raised:
            self.store.cfg_files(self.store.project(self.mod))
        self.assertEqual(raised.exception.status, 403)
        (self.cfgs / 'Linked.json').unlink()
        self.assertIn('ItemCfg.json', self.store.cfg_files(self.store.project(self.mod)))

    def test_id_scan_runs_outside_the_store_lock(self):
        held = []
        original = self.store.record_ids.occupied

        def occupied(*args, **kwargs):
            held.append(self.store.lock._is_owned())
            return original(*args, **kwargs)
        with patch.object(self.store.record_ids, 'occupied', occupied):
            result = self.store.record_ids.public(self.mod)
        self.assertEqual(held, [False])
        self.assertIn(1700001, result['tables']['ItemCfg'])

    def test_a_save_during_the_scan_scans_again(self):
        calls = []
        revisions = iter(['a', 'b', 'b', 'b'])
        original = self.store.record_ids.occupied

        def occupied(*args, **kwargs):
            calls.append(1)
            return original(*args, **kwargs)
        with patch.object(self.store.record_ids, 'occupied', occupied), patch.object(self.store, 'revision', lambda project: next(revisions)):
            result = self.store.record_ids.public(self.mod)
        self.assertEqual(len(calls), 2)
        self.assertEqual(result['revision'], 'b')

    def test_disk_listings_do_not_wait_for_the_location_lock(self):
        source = (Path(server.__file__)).read_text(encoding='utf-8')
        self.assertIn("'/api/ids', '/api/audio'})", source)


if __name__ == '__main__':
    unittest.main()
