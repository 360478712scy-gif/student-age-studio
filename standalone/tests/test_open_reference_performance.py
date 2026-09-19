"""Warm opens and reference menus must not bypass segmented reads."""
import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server as b
import playback_repair
from condition_library import ConditionLibrary

class WarmReferences(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);root=Path(temp.name)
        env=patch.dict(os.environ,{'STUDIO_USER_DATA_ROOT':str(root/'User'),'STUDIO_CACHE_ROOT':str(root/'Cache')});env.start();self.addCleanup(env.stop)
        self.store=b.StudioStore(root/'Mods',root/'Workshop',root/'Game',asset_settings_path=root/'assets.json')
        self.id=self.store.create('Warm references')['id'];self.project=self.store.project(self.id)
        self.cfg=self.project.path/'Cfgs/zh-cn'
        self.write('TalkCfg',{'1':{'id':1,'content':'before','nextTalk':[],'check':[[1,3]]}})
        self.write('EvtCfg',{'1':{'id':1,'title':'event','talkId':[1],'condition':[[1,1]]}})
    def write(self,name,rows):
        (self.cfg/(name+'.json')).write_bytes(b.json_bytes(rows))
    def test_warm_open_runs_real_repair_without_full_load(self):
        import threading,urllib.request,urllib.parse
        host=b.StudioServer(('127.0.0.1',0),self.store)
        thread=threading.Thread(target=host.serve_forever,daemon=True);thread.start()
        try:
            request=urllib.request.Request(host.origin+'/api/project?'+urllib.parse.urlencode({'id':self.id,'talkStorage':'segmented'}),headers={'X-Studio-Token':host.token})
            with urllib.request.urlopen(request) as response:first=json.load(response)
            with patch.object(self.store,'load',side_effect=AssertionError('warm full load')):
                with urllib.request.urlopen(request) as response:second=json.load(response)
            self.assertEqual(first['segmentedTalks']['generation'],second['segmentedTalks']['generation'])
            self.assertEqual(first.get('warnings'),second.get('warnings'))
        finally:
            host.shutdown();host.server_close();host.media_warmup.close();thread.join(5)
    def test_managed_music_repair_invalidates_on_external_edit(self):
        path=self.project.path/'StudentAgeStudio/audio-cues.json';path.parent.mkdir(exist_ok=True)
        path.write_bytes(b.json_bytes({'bgm':[{'audioId':3,'talkIds':[1]}],'sfx':{}}))
        doc={'talks':{'1':{'id':1}},'localIds':{'talks':['1']},'audioCues':{'bgm':[{'audioId':3,'talkIds':[1]}],'sfx':{}},'events':{},'options':{}}
        def load(_):return {**copy.deepcopy(doc),'revision':self.store.revision(self.project)}
        with patch.object(self.store,'load',side_effect=load) as loads,patch.object(self.store,'table',return_value={'rows':{}}),patch('native_audio.export') as export:
            self.assertFalse(playback_repair.repair(self.store,self.id));self.assertFalse(playback_repair.repair(self.store,self.id));self.assertEqual(loads.call_count,1)
            self.write('EvtCfg',{'1':{'id':1,'title':'changed','talkId':[1]}})
            playback_repair.repair(self.store,self.id);self.assertEqual(loads.call_count,2)
            def repair(cues,previous,talks,*args):talks['1']['audio']=3
            self.write('EvtCfg',{'1':{'id':1,'title':'changed again','talkId':[1]}})
            export.side_effect=repair
            with patch.object(self.store,'save') as save:self.assertTrue(playback_repair.repair(self.store,self.id));self.assertEqual(save.call_args.args[0]['talks']['1']['audio'],3)
    def test_reference_cache_and_external_same_size_restored_mtime(self):
        self.write('ItemCfg',{'1':{'id':1,'name':'aaaa'}})
        first=self.store.command_references(self.id,['ItemCfg'])
        with patch.object(self.store,'table',side_effect=AssertionError('warm table reread')):
            self.assertEqual(self.store.command_references(self.id,['ItemCfg']),first)
        path=self.cfg/'ItemCfg.json';stat=path.stat();path.write_bytes(path.read_bytes().replace(b'aaaa',b'bbbb'));os.utime(path,ns=(stat.st_atime_ns,stat.st_mtime_ns))
        second=self.store.command_references(self.id,['ItemCfg']);self.assertEqual(second['tables']['ItemCfg']['rows']['1']['name'],'bbbb');self.assertNotEqual(first['revision'],second['revision'])
    def test_loaded_references_preserve_originals_and_skip_local_bodies(self):
        catalog={'tables':{'TalkCfg':{'99':{'id':99,'content':'original'}},'EvtCfg':{'9':{'id':9,'title':'original event'}}}}
        with patch.object(self.store,'catalog',return_value=catalog),patch.object(self.store,'table',side_effect=AssertionError('loaded local table')):
            result=self.store.command_references(self.id,['TalkCfg','EvtCfg'],['TalkCfg','EvtCfg'])
        self.assertEqual(result['tables']['TalkCfg']['rows'],catalog['tables']['TalkCfg']);self.assertIn('9',result['tables']['EvtCfg']['rows'])
    def test_reference_conflict_and_partial_failure_retry(self):
        original=self.store.table
        def race(*args,**kwargs):
            result=original(*args,**kwargs);self.write('EvtCfg',{'1':{'id':1,'title':'external edit'}});return result
        with patch.object(self.store,'table',side_effect=race):
            with self.assertRaises(b.ApiError) as caught:self.store.command_references(self.id,['ItemCfg'])
        self.assertEqual(caught.exception.status,409)
        (self.cfg/'ItemCfg.json').write_text('{broken')
        result=self.store.command_references(self.id,['ItemCfg','EvtCfg']);self.assertIn('ItemCfg',result['errors']);self.assertIn('EvtCfg',result['tables'])
        self.write('ItemCfg',{'2':{'id':2,'name':'fixed'}});self.assertEqual(self.store.command_references(self.id,['ItemCfg','EvtCfg'])['errors'],{})
    def test_condition_index_only_rereads_changed_json(self):
        library=ConditionLibrary(self.store,b)
        first=library.get(self.id)
        reads=self.store.readable_maps
        def guarded(project,selected=None):
            self.assertEqual(selected,{'EvtCfg.json'});return reads(project,selected)
        self.write('EvtCfg',{'1':{'id':1,'title':'new event','condition':[[1,2]],'talkId':[1]}})
        with patch.object(self.store,'readable_maps',side_effect=guarded):second=library.get(self.id)
        self.assertTrue(any(e['table']=='EvtCfg' and e['title']=='new event' for e in second['entries']))
        self.assertEqual([e for e in first['entries'] if e['table']=='TalkCfg'],[e for e in second['entries'] if e['table']=='TalkCfg'])
        path=self.cfg/'TalkCfg.json';stat=path.stat();path.write_bytes(path.read_bytes().replace(b'before',b'after!'));os.utime(path,ns=(stat.st_atime_ns,stat.st_mtime_ns))
        self.assertTrue(any(e['table']=='TalkCfg' and e['title']=='after!' for e in library.get(self.id)['entries']))

if __name__=='__main__':unittest.main()
