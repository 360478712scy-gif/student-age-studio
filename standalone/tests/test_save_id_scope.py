import sys,tempfile,unittest,os
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server as b
class SaveIdScopeTests(unittest.TestCase):
 def test_new_dialogue_checks_only_matching_tables_and_detects_external_edit(self):
  with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'STUDIO_USER_DATA_ROOT':tmp+'/User','STUDIO_CACHE_ROOT':tmp+'/Cache','STUDIO_BACKUP_ROOT':tmp+'/Backups'}):
   root=Path(tmp);store=b.StudioStore(root/'Mods',root/'Workshop',root/'Game',asset_settings_path=root/'assets.json',migrate_cache=False)
   me=store.project(store.create('目标')['id']);other=store.project(store.create('其他')['id'])
   cfg=other.path/'Cfgs/zh-cn';(cfg/'TalkCfg.json').write_bytes(b.json_bytes({'900001001':{'id':900001001}}));(cfg/'ItemCfg.json').write_bytes(b.json_bytes({'7':{'id':7}}))
   changes={'Cfgs/zh-cn/TalkCfg.json':b.json_bytes({'900001001':{'id':900001001}})}
   original=store.record_ids.keys
   with patch.object(store.record_ids,'keys',wraps=original) as keys:
    notes=store.record_ids.validate_created(me,changes)
   self.assertTrue(any('900001001' in n for n in notes));self.assertFalse(any(c.args[0].name=='ItemCfg.json' for c in keys.call_args_list))
   (cfg/'TalkCfg.json').write_bytes(b.json_bytes({'900001002':{'id':900001002}}))
   self.assertEqual(store.record_ids.validate_created(me,changes),[])
   changes={'Cfgs/zh-cn/TalkCfg.json':b.json_bytes({'900001002':{'id':900001002}})}
   self.assertTrue(store.record_ids.validate_created(me,changes))
if __name__=='__main__':unittest.main()
