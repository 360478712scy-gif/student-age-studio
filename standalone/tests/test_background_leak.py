"""Background tab stays fast and bounded over long sessions.

Covers the 2-3 minute background-tab stall: repeated opens must reuse
directory/file fingerprints, skip redundant de-duplication passes, and every
growth ledger (hash index, attempts, preview cache) must stay capped.
"""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server as b
from PIL import Image


class BackgroundBenchHarness(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        env = patch.dict(os.environ, {'STUDIO_CACHE_ROOT': str(self.root / 'Cache'),
                                       'STUDIO_USER_DATA_ROOT': str(self.root / 'User'),
                                       'STUDIO_DISPLAY_SETTINGS': str(self.root / 'display.json')})
        env.start()
        self.addCleanup(env.stop)
        self.store = b.StudioStore(self.root / 'Mods', self.root / 'Workshop', self.root / 'Game')
        self.ident = self.store.create('背景压测')['id']
        self.project = self.store.project(self.ident)
        self.catalog = self.store.asset_catalog
        self.lib = self.root / 'lib'
        (self.lib / 'sub').mkdir(parents=True)

    def make_images(self, count, prefix='bg'):
        for index in range(count):
            Image.new('RGB', (64, 40), ((index * 37) % 256, 100, 150)).save(
                self.lib / 'sub' / f'{prefix}{index:04d}.png')

    def use_folder(self):
        folders = self.catalog.folders()
        self.catalog.set_folder({'kind': 'background', 'path': str(self.lib),
                                 'settingsRevision': folders['revision']})

    def query(self):
        return {'projectId': self.ident, 'revision': self.store.revision(self.project),
                'source': 'custom', 'kind': 'background', 'grade': 1, 'cloth': 0}

    def drain_hashes(self, timeout=120):
        deadline = time.time() + timeout
        while self.catalog.hash_progress()['running'] and time.time() < deadline:
            time.sleep(0.2)
        self.assertFalse(self.catalog.hash_progress()['running'])

    def test_folder_watch_reuses_names_but_detects_content_edits(self):
        import asset_catalog as module
        self.make_images(8)
        folder = {'path': str(self.lib)}
        first = self.catalog._folder_watch(folder)
        self.assertEqual(len([row for row in first if row[0].endswith('.png')]), 8)
        # Unchanged directory: names reused without rescanning.
        with patch('asset_catalog.os.scandir', side_effect=AssertionError('rescan')):
            self.assertEqual(self.catalog._folder_watch(folder), first)
        # Same names, rewritten bytes: per-file fingerprints must catch it
        # (rewriting contents does not bump the directory stamp on NTFS).
        target = self.lib / 'sub' / 'bg0000.png'
        target.write_bytes(target.read_bytes() + b'\x00')
        self.assertNotEqual(self.catalog._folder_watch(folder), first)

    def test_folder_watch_detects_new_file(self):
        self.make_images(2)
        folder = {'path': str(self.lib)}
        before = self.catalog._folder_watch(folder)
        (self.lib / 'sub' / 'bg-new.png').write_bytes(b'new')
        after = self.catalog._folder_watch(folder)
        self.assertNotEqual(before, after)
        self.assertTrue(any(row[0].endswith('bg-new.png') for row in after))

    def test_unfiltered_list_skips_second_dedup_pass(self):
        import asset_catalog as module
        self.make_images(20)
        self.use_folder()
        self.catalog.list(self.query())
        self.drain_hashes()
        warmed = self.catalog.list(self.query())
        with patch.object(self.catalog, '_deduplicate_backgrounds',
                           wraps=self.catalog._deduplicate_backgrounds) as spy:
            result = self.catalog.list(self.query())
        self.assertEqual(spy.call_count, 0)
        self.assertEqual([item['assetId'] for item in result['items']],
                         [item['assetId'] for item in warmed['items']])

    def test_dedup_with_versions_matches_without(self):
        self.make_images(6)
        image_hashes = {}
        import asset_catalog as module
        paths = sorted((self.lib / 'sub').glob('*.png'))
        for path in paths:
            version = module.file_fingerprint(path)
            image_hashes[(str(path), version)] = 'shared-pixels'
        items = [{'assetId': path.name, 'name': path.name, '_path': path} for path in paths]
        with self.catalog._hash_guard:
            self.catalog.image_hashes.update(image_hashes)
            plain = self.catalog._deduplicate_backgrounds([dict(item) for item in items])
            versions = {path: module.file_fingerprint(path) for path in paths}
            keyed = self.catalog._deduplicate_backgrounds([dict(item) for item in items], versions)
        self.assertEqual(plain, keyed)
        self.assertEqual(len(plain), 1)
        self.assertEqual(plain[0]['duplicateCount'], 5)

    def test_prune_hash_memory_drops_dead_and_stale(self):
        import asset_catalog as module
        live = self.root / 'live.png'
        Image.new('RGB', (8, 8), (1, 2, 3)).save(live)
        version = module.file_fingerprint(live)
        dead = str(self.root / 'gone.png')
        catalog = module.AssetCatalog(store=None, backend=b, settings_path=self.root / 'folders.json')
        catalog.hash_index = {
            str(live): {'stamp': list(version), 'hash': 'h-live'},
            dead: {'stamp': [1, 2, 3], 'hash': 'h-dead'},
        }
        catalog.image_hashes = {
            (str(live), version): 'h-live',
            (str(live), (0, 0, 0, 0, 0, 0, 0)): 'h-stale',
            (dead, (1, 2, 3, 0, 0, 0, 0)): 'h-dead',
            ('/nowhere/x.png', (1, 2, 3, 0, 0, 0, 0)): 'h-orphan',
        }
        with patch.object(module, '_HASH_INDEX_PRUNE_AT', 1):
            catalog._prune_hash_memory()
        self.assertEqual(set(catalog.hash_index), {str(live)})
        self.assertEqual(catalog.image_hashes, {(str(live), version): 'h-live'})

    def test_attempts_ledger_capped_giveups_kept(self):
        from types import SimpleNamespace
        from media_warmup import MediaWarmup
        job = MediaWarmup(SimpleNamespace(store=SimpleNamespace(game=self.root / 'Game')))
        attempts = {}
        for index in range(10001):
            attempts[f'file:/f{index}.png'] = {'signature': 's', 'count': 1,
                                               **({'gaveUp': True, 'at': 1.0} if index % 2 else {})}
        job.attempts = attempts
        store = SimpleNamespace(asset_catalog=SimpleNamespace(api=b))
        job.save_attempts(store)
        self.assertEqual(len(job.attempts), 10000)
        kept_giveups = sum(1 for record in job.attempts.values()
                           if isinstance(record, dict) and record.get('gaveUp'))
        self.assertEqual(kept_giveups, 5000)

    def test_preview_cache_pruned_to_newest(self):
        from media_warmup import MediaWarmup
        cache = self.root / 'PreviewCache'
        cache.mkdir()
        now = time.time()
        for index in range(10):
            path = cache / f'p{index}.webp'
            path.write_bytes(b'x')
            os.utime(path, (now - (10 - index) * 100, now - (10 - index) * 100))
        MediaWarmup._prune_preview_cache(cache, keep=5)
        remaining = sorted(p.name for p in cache.iterdir())
        self.assertEqual(remaining, [f'p{i}.webp' for i in range(5, 10)])


if __name__ == '__main__':
    unittest.main()
