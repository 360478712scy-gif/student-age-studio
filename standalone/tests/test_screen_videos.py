"""Video libraries preserve real source files and fail closed before imports."""
import copy
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import test_plugin_mode as fixture
import server as b
import screen_videos as videos
import video_transcode


class ScreenVideoTests(unittest.TestCase):
    def setUp(self):
        fixture.PluginModeTests.setUp(self)
        self.addCleanup(self.store.close)
        self.root = Path(self.tmp.name)

    def row(self, ident=1, name='片段', video='movie.mp4', **fields):
        return dict(id=ident, name=name, video=video, volume=.7, loop=False,
                    skippable=True, roleOnTop=False, scale='fit', **fields)

    def document(self, project=None, rows=None, relative='ScreenVideo/CustomVideo.json', **fields):
        project = project or self.project
        path = project.path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        b.atomic_write(path, b.json_bytes(dict(videos=rows or [], **fields)))
        return path

    def media(self, project=None, name='movie.mp4', raw=b'original-video'):
        path = (project or self.project).path / 'ScreenVideo' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return path

    def listing(self, source='mod', project=None, **query):
        return videos.access(self.store, b, dict(projectId=self.id, source=source,
                            sourceProjectId=(project or self.project).id, **query))

    def payload(self, item, source='mod', **fields):
        return dict(projectId=self.id, revision=self.store.revision(self.project),
                    source=source, sourceProjectId=item.get('sourceProjectId'),
                    assetId=item['assetId'], assetRevision=item['assetRevision'],
                    sourceRevision=item.get('sourceRevision'), **fields)

    def snapshot(self, root=None):
        root = root or self.project.path
        return {str(path.relative_to(root)): path.read_bytes()
                for path in root.rglob('*') if path.is_file()
                and path.suffix.lower() in {'.json', *video_transcode.EXTENSIONS}}

    def custom(self):
        root = self.root / '视频来源'
        root.mkdir()
        state = videos.folder_get(self.store, b)
        videos.folder_set(self.store, b, dict(path=str(root), revision=state['revision']))
        return root

    def preview_query(self, item):
        return {key: value[0] for key, value in
                parse_qs(urlparse(item['previewUrl']).query).items()}

    def assert_conflict(self, action):
        with self.assertRaises(b.ApiError) as caught:
            action()
        self.assertEqual(caught.exception.code, 'conflict')

    def test_current_other_and_workshop_sources_can_be_read_and_copied(self):
        other = self.store.project(self.store.create('另一个来源')['id'])
        workshop_root = self.store.workshop / 'subscribed'
        workshop_root.mkdir(parents=True)
        b.atomic_write(workshop_root / 'manifest.json', b.json_bytes({'title': '订阅来源'}))
        workshop = next(p for p in self.store.projects() if p.readonly)
        sources = [(self.project, 'ScreenVideo/CustomVideo.json'),
                   (other, 'EC2BUnofficialPatch/ScreenVideo/CustomVideo.json'),
                   (workshop, 'ScreenVideo/CustomVideo.json')]
        for index, (project, relative) in enumerate(sources, 1):
            row = self.row(index, '来源' + str(index))
            config = self.document(project, [row], relative)
            media = config.parent / row['video']
            media.write_bytes(('source-' + str(index)).encode())
            listing = self.listing(project=project)
            self.assertEqual((listing['total'], listing['page'], listing['pageSize']), (1, 0, 36))
            self.assertTrue(any(p['id'] == project.id for p in listing['projects']))
            item = listing['items'][0]
            self.assertEqual((item['videoId'], item['sourceProjectId'], item['row']),
                             (index, project.id, row))
            self.assertTrue(item['available'])
            self.assertTrue(item['sourceRevision'] and item['assetRevision'])
            resolved, source_row = videos.resolve_import(self.store, b, self.payload(item))
            self.assertEqual((resolved.resolve(), source_row), (media.resolve(), row))
            self.assertEqual(videos.file_path(self.store, b, self.preview_query(item)).resolve(), media.resolve())
        before = self.snapshot(workshop.path)
        item = self.listing(project=workshop)['items'][0]
        result = videos.commit_import(self.store, b, self.project,
                    self.store.revision(self.project), b'converted-mp4', {'duration': 1},
                    self.payload(item, row=item['row'], fileName='movie.mp4'))
        self.assertTrue(result['imported'])
        self.assertEqual((self.project.path / result['assetPath']).read_bytes(), b'converted-mp4')
        self.assertEqual(self.snapshot(workshop.path), before)

    def test_custom_folder_recurses_filters_extensions_searches_and_pages(self):
        root = self.custom()
        nested = root / 'nested'
        nested.mkdir()
        for index in range(40):
            extension = sorted(video_transcode.EXTENSIONS)[index % len(video_transcode.EXTENSIONS)]
            (nested / ('movie%02d' % index + extension.upper())).write_bytes(b'video')
        (root / 'not-a-video.txt').write_bytes(b'ignore')
        outside = self.root / 'outside.mp4'
        outside.write_bytes(b'outside')
        (root / 'escape.mp4').symlink_to(outside)
        first = self.listing('custom', q='movie', page=0)
        second = self.listing('custom', q='movie', page=1)
        self.assertEqual((first['total'], first['pageSize'], len(first['items'])), (40, 36, 36))
        self.assertEqual((second['total'], second['page'], len(second['items'])), (40, 1, 4))
        self.assertEqual(len({item['assetId'] for item in first['items'] + second['items']}), 40)
        one = self.listing('custom', q='movie00')['items']
        self.assertEqual(len(one), 1)
        path, row = videos.resolve_import(self.store, b, self.payload(one[0], 'custom'))
        self.assertEqual(path.parent.resolve(), nested.resolve())
        self.assertIsInstance(row, dict)
        self.assertTrue(all(item['available'] for item in first['items']))
        self.assertEqual(self.listing('custom', q='escape')['total'], 0)

    def test_folder_setting_persists_and_rejects_conflicts_and_invalid_directories(self):
        initial = videos.folder_get(self.store, b)
        root = self.custom()
        saved = videos.folder_get(self.store, b)
        self.assertEqual(Path(saved['path']).resolve(), root.resolve())
        self.assertNotEqual(saved['revision'], initial['revision'])
        reopened = b.StudioStore(self.store.mods, self.store.workshop, self.store.game,
                    asset_settings_path=self.root / 'assets.json')
        self.addCleanup(reopened.close)
        self.assertEqual(videos.folder_get(reopened, b), saved)
        self.assert_conflict(lambda: videos.folder_set(self.store, b,
                    dict(path=str(root), revision=initial['revision'])))
        invalid = self.root / 'ordinary-file.mp4'
        invalid.write_bytes(b'file')
        for path in [invalid, self.root / 'does-not-exist']:
            with self.subTest(path=path), self.assertRaises(b.ApiError):
                videos.folder_set(self.store, b, dict(path=str(path), revision=saved['revision']))
            self.assertEqual(videos.folder_get(self.store, b), saved)

    def test_malformed_configurations_never_get_repaired_or_overwritten(self):
        path = self.document(rows=[self.row()])
        self.media()
        invalid = [b'{broken', b.json_bytes(None), b.json_bytes([]), b.json_bytes({}),
                   b.json_bytes({'videos': {}}), b.json_bytes({'videos': [None]}),
                   b.json_bytes({'videos': [self.row(0)]}),
                   b.json_bytes({'videos': [self.row(True)]}),
                   b.json_bytes({'videos': [self.row(), self.row()]})]
        for raw in invalid:
            with self.subTest(raw=raw):
                path.write_bytes(raw)
                before = self.snapshot()
                with self.assertRaises(b.ApiError):
                    self.listing()
                with self.assertRaises(b.ApiError):
                    videos.settings_save(self.store, b, dict(projectId=self.id,
                        revision=self.store.revision(self.project), id=1, name='覆盖'))
                with self.assertRaises(b.ApiError):
                    videos.commit_import(self.store, b, self.project,
                        self.store.revision(self.project), b'converted', {'duration': 1},
                        dict(fileName='new.webm', name='新视频'))
                self.assertEqual(self.snapshot(), before)

    def test_absolute_parent_and_symlink_media_paths_are_rejected(self):
        outside = self.root / 'secret.mp4'
        outside.write_bytes(b'private')
        media = self.media(name='escape.mp4')
        media.unlink()
        media.symlink_to(outside)
        for name in [str(outside), '../../secret.mp4', 'escape.mp4']:
            with self.subTest(video=name):
                self.document(rows=[self.row(video=name)])
                before = self.snapshot()
                item = self.listing()['items'][0]
                self.assertFalse(item['available'])
                with self.assertRaises(b.ApiError):
                    videos.resolve_import(self.store, b, self.payload(item))
                query = self.preview_query(item) if item.get('previewUrl') else self.payload(item)
                with self.assertRaises(b.ApiError):
                    videos.file_path(self.store, b, query)
                self.assertEqual(self.snapshot(), before)
                self.assertEqual(outside.read_bytes(), b'private')

    def test_missing_media_is_unavailable_and_cannot_preview_or_import(self):
        self.document(rows=[self.row(video='missing.mp4')])
        item = self.listing()['items'][0]
        self.assertFalse(item['available'])
        before = self.snapshot()
        with self.assertRaises(b.ApiError):
            videos.resolve_import(self.store, b, self.payload(item))
        query = self.preview_query(item) if item.get('previewUrl') else self.payload(item)
        with self.assertRaises(b.ApiError):
            videos.file_path(self.store, b, query)
        self.assertEqual(self.snapshot(), before)

    def test_changed_media_rejects_old_import_and_preview_even_with_restored_mtime(self):
        self.document(rows=[self.row()])
        media = self.media(raw=b'first-clip')
        item = self.listing()['items'][0]
        payload = self.payload(item, row=item['row'], fileName='movie.mp4')
        stamp = media.stat()
        media.write_bytes(b'other-clip')
        os.utime(media, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        before = self.snapshot()
        self.assert_conflict(lambda: videos.resolve_import(self.store, b, payload))
        self.assert_conflict(lambda: videos.file_path(self.store, b, self.preview_query(item)))
        self.assert_conflict(lambda: videos.commit_import(self.store, b, self.project,
                payload['revision'], b'converted', {'duration': 1}, payload))
        self.assertEqual(self.snapshot(), before)

    def test_changed_source_document_rejects_old_token_without_writes(self):
        other = self.store.project(self.store.create('外部来源')['id'])
        path = self.document(other, [self.row(name='AAA')])
        self.media(other)
        item = self.listing(project=other)['items'][0]
        payload = self.payload(item, row=item['row'], fileName='movie.mp4')
        stamp = path.stat()
        path.write_bytes(path.read_bytes().replace(b'AAA', b'BBB'))
        os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        before = self.snapshot()
        source_before = self.snapshot(other.path)
        self.assert_conflict(lambda: videos.resolve_import(self.store, b, payload))
        self.assert_conflict(lambda: videos.commit_import(self.store, b, self.project,
                payload['revision'], b'converted', {'duration': 1}, payload))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.snapshot(other.path), source_before)

    def test_destination_revision_conflict_keeps_all_existing_files(self):
        root = self.custom()
        (root / 'clip.webm').write_bytes(b'source')
        item = self.listing('custom')['items'][0]
        payload = self.payload(item, 'custom', fileName='clip.webm')
        self.protected.write_text('{"4":{"id":4,"future":"external"}}')
        before = self.snapshot()
        self.assert_conflict(lambda: videos.commit_import(self.store, b, self.project,
                payload['revision'], b'converted', {'duration': 1}, payload))
        self.assertEqual(self.snapshot(), before)

    def test_import_preserves_unknown_fields_and_commits_media_and_json_once(self):
        path = self.document(rows=[self.row(2), self.row(9, '已有', 'other.mp4')],
                             future={'document': 'keep'})
        self.media()
        self.media(name='other.mp4')
        other = self.store.project(self.store.create('另一个编号')['id'])
        self.document(other, [self.row(20)])
        root = self.custom()
        (root / 'clip.webm').write_bytes(b'source')
        item = self.listing('custom')['items'][0]
        source_row = self.row(5, '来源参数', 'clip.webm', future={'row': 'keep'})
        payload = self.payload(item, 'custom', row=source_row, fileName='clip.webm',
                               name='导入参数', volume=.45, loop=True, skippable=False,
                               roleOnTop=True, scale='fill')
        expected = payload['revision']
        before = copy.deepcopy(b.read_json(path))
        with patch.object(self.store, 'commit', wraps=self.store.commit) as commit:
            result = videos.commit_import(self.store, b, self.project, expected,
                        b'converted-mp4', {'duration': 1, 'width': 320, 'height': 180}, payload)
        self.assertEqual(commit.call_count, 1)
        args = commit.call_args.args
        changes = args[1]
        self.assertEqual(set(changes), {'ScreenVideo/CustomVideo.json', result['assetPath']})
        self.assertEqual(changes[result['assetPath']], b'converted-mp4')
        self.assertEqual(args[2] if len(args) > 2 else commit.call_args.kwargs['expected_revision'], expected)
        after = b.read_json(path)
        self.assertEqual(after['future'], before['future'])
        self.assertEqual(after['videos'][:2], before['videos'])
        row = next(row for row in after['videos'] if row['id'] == result['id'])
        self.assertNotIn(row['id'], {2, 9, 20})
        self.assertEqual(row['future'], source_row['future'])
        for key in ['name', 'volume', 'loop', 'skippable', 'roleOnTop', 'scale']:
            self.assertEqual(row[key], payload[key])
        self.assertEqual((path.parent / row['video']).read_bytes(), b'converted-mp4')
        self.assertEqual((root / 'clip.webm').read_bytes(), b'source')
        self.assertNotEqual(self.store.revision(self.project), expected)

    def test_settings_update_all_parameters_preserving_fields_and_refuse_bad_values(self):
        row = self.row(future={'animation': 'keep'})
        path = self.document(rows=[row], future={'document': 'keep'})
        self.media()
        payload = dict(projectId=self.id, revision=self.store.revision(self.project),
                       id=1, name='新标题', volume=.25, loop=True, skippable=False,
                       roleOnTop=True, scale='stretch')
        result = videos.settings_save(self.store, b, payload)
        self.assertEqual(result['projectId'], self.id)
        self.assertTrue(result['imported'])
        self.assertEqual(result['importDelta'], {})
        document = b.read_json(path)
        saved = document['videos'][0]
        for key in ['name', 'volume', 'loop', 'skippable', 'roleOnTop', 'scale']:
            self.assertEqual(saved[key], payload[key])
        self.assertEqual(saved['video'], row['video'])
        self.assertEqual(saved['future'], row['future'])
        self.assertEqual(document['future'], {'document': 'keep'})
        before = self.snapshot()
        self.assert_conflict(lambda: videos.settings_save(self.store, b, payload))
        for update in [dict(volume=-.1), dict(volume=1.1), dict(volume=float('nan')),
                       dict(loop='true'), dict(skippable=1), dict(roleOnTop=None),
                       dict(scale=0), dict(scale=float('inf')), dict(name=None)]:
            with self.subTest(update=update), self.assertRaises(b.ApiError):
                videos.settings_save(self.store, b, dict(payload,
                    revision=self.store.revision(self.project), **update))
            self.assertEqual(self.snapshot(), before)

    def test_changed_custom_folder_invalidates_old_import_and_readonly_target_refuses(self):
        root = self.custom()
        (root / 'clip.webm').write_bytes(b'source')
        item = self.listing('custom')['items'][0]
        payload = self.payload(item, 'custom', fileName='clip.webm')
        replacement = self.root / '另一来源'
        replacement.mkdir()
        state = videos.folder_get(self.store, b)
        videos.folder_set(self.store, b, dict(path=str(replacement), revision=state['revision']))
        before = self.snapshot()
        self.assert_conflict(lambda: videos.resolve_import(self.store, b, payload))
        self.assert_conflict(lambda: videos.commit_import(self.store, b, self.project,
                payload['revision'], b'converted', {'duration': 1}, payload))
        self.assertEqual(self.snapshot(), before)
        workshop_root = self.store.workshop / 'readonly'
        workshop_root.mkdir(parents=True)
        b.atomic_write(workshop_root / 'manifest.json', b.json_bytes({'title': '只读目标'}))
        workshop = next(project for project in self.store.projects() if project.readonly)
        source_before = self.snapshot(workshop.path)
        with self.assertRaises(b.ApiError):
            videos.commit_import(self.store, b, workshop, self.store.revision(workshop),
                                 b'converted', {'duration': 1}, dict(fileName='new.mp4'))
        self.assertEqual(self.snapshot(workshop.path), source_before)

    def test_unrelated_corrupt_mod_is_warned_and_kept_without_blocking_current_import(self):
        self.document(rows=[self.row()])
        self.media()
        other = self.store.project(self.store.create('损坏的无关模组')['id'])
        damaged = self.document(other)
        damaged.write_bytes(b'{"videos": broken-data\n')
        raw = damaged.read_bytes()
        item = self.listing()['items'][0]
        self.assertTrue(item['available'])
        combined = videos.access(self.store, b, dict(projectId=self.id, source='mod',
                                 sourceProjectId='all'))
        self.assertTrue(combined.get('warnings'))
        self.assertTrue(any(entry['sourceProjectId'] == self.id for entry in combined['items']))
        payload = self.payload(item, row=item['row'], fileName='movie.mp4')
        result = videos.commit_import(self.store, b, self.project, payload['revision'],
                                     b'converted', {'duration': 1}, payload)
        self.assertTrue(result['imported'])
        self.assertNotEqual(result['id'], item['videoId'])
        self.assertEqual((self.project.path / result['assetPath']).read_bytes(), b'converted')
        self.assertEqual(damaged.read_bytes(), raw)


if __name__ == '__main__':
    unittest.main()
