"""Ignored subscriptions never enter data paths; defaults and cache cleanup persist."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server as b
from media_warmup import MediaWarmup
from project_preferences import RequestGate, update
from storage_paths import auxiliary_cache, cache_root


class ProjectPreferenceTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        env=patch.dict(os.environ,{'STUDIO_USER_DATA_ROOT':str(self.root/'User'),'STUDIO_CACHE_ROOT':str(self.root/'Cache')});env.start();self.addCleanup(env.stop)
        self.store=self.make_store()
        self.local=self.store.create('本地草稿')['id']
        for n in range(3):
            root=self.store.workshop/str(n);cfg=root/'Cfgs/zh-cn';cfg.mkdir(parents=True)
            (root/'manifest.json').write_text(json.dumps({'title':'订阅 '+str(n)}))
            (cfg/'TalkCfg.json').write_text(json.dumps({str(8000+n):{'id':8000+n,'content':'文本','check':[[1,2,n]]}}))
            (root/'picture.png').write_bytes(b'unchanged-source')
        self.mods=[p for p in self.store.projects() if p.readonly]
        self.server=SimpleNamespace(store=self.store)
        self.server.media_warmup=MediaWarmup(self.server)
        self.addCleanup(lambda:self.server.media_warmup.close())
    def make_store(self):
        return b.StudioStore(self.root/'Mods',self.root/'Workshop',self.root/'Game',asset_settings_path=self.root/'User/assets.json')
    def change(self,**payload): return update(self.server,payload)
    def test_ignored_sources_never_read_and_can_restore(self):
        mod=self.mods[0];files={p:p.read_bytes() for p in mod.path.rglob('*') if p.is_file()}
        self.change(ignoredProjectIds=[mod.id],defaultProjectId=self.local)
        original=b.file_fingerprint
        def checked(path):
            self.assertFalse(Path(path).is_relative_to(mod.path),'ignored file accessed')
            return original(path)
        with patch.object(b,'file_fingerprint',side_effect=checked):
            self.assertNotIn(mod.id,[p.id for p in self.store.projects()])
            self.assertNotIn(8000,self.store.record_ids.occupied(include_catalog=False).get('TalkCfg',set()))
            with self.assertRaises(b.ApiError):self.store.project(mod.id)
            self.assertEqual(self.store.asset_catalog._folder_watch({'path':str(mod.path)}),[])
            self.assertEqual(self.store.asset_catalog._scan(self.store.project(self.local),'cg',{'path':str(mod.path)},[]),[])
        for path,raw in files.items():self.assertEqual(path.read_bytes(),raw)
        reloaded=self.make_store();self.assertIn(mod.id,reloaded.project_preferences.ignored)
        self.assertEqual(reloaded.project_preferences.public()['defaultProjectId'],self.local)
        self.change(ignoredProjectIds=[])
        self.assertEqual(self.store.project(mod.id).name,mod.name)
    def test_cleanup_disk_memory_and_old_tokens(self):
        mod=self.mods[0];asset=self.store.asset_catalog;path=str(mod.path/'picture.png')
        preview=auxiliary_cache(asset.settings_path.parent,'PreviewCache')/('f'*64+'.webp');preview.parent.mkdir(parents=True);preview.write_bytes(b'derived')
        manifest=auxiliary_cache(asset.settings_path.parent,'AssetCache/media-warmup-v1.json')
        keep=preview.with_name('e'*64+'.webp');keep.write_bytes(b'other-mod-preview')
        b.atomic_write(manifest,b.json_bytes({path:{'outputs':[str(preview)],'stamp':[]},str(self.mods[1].path/'picture.png'):{'outputs':[str(keep)],'stamp':[]}}))
        b.atomic_write(asset.hash_index_path,b.json_bytes({path:{'hash':'old'}}));asset.hash_index={path:{'hash':'old'}}
        asset.validation[(path,(),'image')]={'width':10};asset.cache['old']={'projectId':mod.id}
        segment=cache_root()/'TalkSegments/v1'/('a'*32);segment.mkdir(parents=True);(segment/'index.json').write_text(json.dumps({'identity':{'path':str(mod.path)}}))
        self.change(ignoredProjectIds=[mod.id])
        self.assertFalse(preview.exists());self.assertFalse(segment.exists())
        self.assertEqual(len(b.read_json(manifest)),1);self.assertTrue(keep.exists());self.assertEqual(asset.hash_index,{})
        self.assertFalse(asset.validation);self.assertFalse(asset.cache)
        self.assertNotIn(str(mod.path),str(b.read_json(self.store._project_index_path)))
    def test_only_subscriptions_and_valid_defaults(self):
        with self.assertRaises(b.ApiError):self.change(ignoredProjectIds=[self.local])
        with self.assertRaises(b.ApiError):self.change(defaultProjectId='local:missing')
        self.change(defaultProjectId=self.mods[0].id)
        state=self.change(ignoredProjectIds=[self.mods[0].id]);self.assertEqual(state['defaultProjectId'],'')
        state=self.change(ignoredProjectIds=[],defaultProjectId=self.mods[0].id);self.assertEqual(state['defaultProjectId'],self.mods[0].id)
    def test_warmup_only_active_mod_even_with_many_subscriptions(self):
        self.store.active_project_id=self.local;seen=[];warm=self.server.media_warmup
        with patch.object(self.store,'projects',side_effect=AssertionError('must not enumerate subscriptions')),patch.object(warm,'run_stage'),patch.object(warm,'scan_media',side_effect=lambda store,projects,*a:seen.append([p.id for p in projects]) or 0):
            warm.scan()
        self.assertEqual(seen,[[self.local],[self.local]])
        self.change(ignoredProjectIds=[self.mods[0].id]);self.store.active_project_id=self.mods[0].id;seen=[];warm=self.server.media_warmup
        with patch.object(warm,'run_stage'),patch.object(warm,'scan_media',side_effect=lambda store,projects,*a:seen.append(projects) or 0):warm.scan()
        self.assertEqual(seen,[[],[]])
    def test_ignored_nested_custom_folder_skipped(self):
        self.change(ignoredProjectIds=[self.mods[0].id])
        warm=self.server.media_warmup
        found=warm.files([self.store.workshop],{self.mods[0].path})
        self.assertFalse(any(str(self.mods[0].path) in p for p in found))
        self.assertTrue(any(str(self.mods[1].path) in p for p in found))
    def test_default_setting_does_not_clear_live_cache(self):
        self.store.asset_catalog.cache['keep']={'ok':True}
        self.change(defaultProjectId=self.local)
        self.assertIn('keep',self.store.asset_catalog.cache)
    def test_interrupted_cleanup_is_retried_on_next_store(self):
        policy=self.store.project_preferences;mod=self.mods[0]
        with patch.object(policy,'purge',side_effect=OSError('locked cache')):
            with self.assertRaises(OSError):self.change(ignoredProjectIds=[mod.id])
        self.assertTrue(b.read_json(policy.path)['cleanupPending'])
        # Corrupt disposable indexes must not prevent reopening the editor.
        manifest=auxiliary_cache(self.store.asset_catalog.settings_path.parent,'AssetCache/media-warmup-v1.json')
        manifest.write_bytes(b'broken-cache')
        reloaded=self.make_store()
        self.assertIn(mod.id,reloaded.project_preferences.ignored)
        self.assertNotIn('cleanupPending',b.read_json(policy.path))
        self.assertTrue((mod.path/'picture.png').exists())

    def test_gate_drains_readers_and_keeps_normal_requests_parallel(self):
        gate=RequestGate();entered=threading.Event();finish=threading.Event();write=threading.Event()
        def reader():
            with gate.access():entered.set();finish.wait(2)
        def writer():
            with gate.access(exclusive=True):write.set()
        t=threading.Thread(target=reader);t.start();self.assertTrue(entered.wait(1))
        with gate.access():self.assertEqual(gate.readers,2)
        w=threading.Thread(target=writer);w.start();self.assertFalse(write.wait(.05))
        finish.set();t.join(2);w.join(2);self.assertTrue(write.is_set())

if __name__=='__main__':unittest.main()
