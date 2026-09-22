import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import base64,copy,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import server as b
import plugin_mode as p
import project_removal as removal
import editor_music as music

class PluginModeTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);r=Path(self.tmp.name)
  env=patch.dict(os.environ,{'STUDIO_CACHE_ROOT':str(r/'Cache'),'STUDIO_USER_DATA_ROOT':str(r/'User')});env.start();self.addCleanup(env.stop)
  self.store=b.StudioStore(r/'Mods',r/'Workshop',r/'Game',asset_settings_path=r/'assets.json');self.id=self.store.create('插件验证')['id'];self.project=self.store.project(self.id)
  self.cfg=self.project.path/'Cfgs/zh-cn';self.protected=self.cfg/'KZoneProfileCfg.json';self.protected.write_text('{"3": {"id":3,"font":123,"fontColor":456}}\n');self.before=self.protected.read_bytes()
 def request(self):
  template=p.catalog(b)['stages']['910201'];return {'projectId':self.id,'revision':self.store.revision(self.project),'enabled':[p.UP,p.CAMPUS],'groups':[{'id':123456,'template':9102,'name':'五子棋·人物关卡','levels':[{**template,'id':12345601}],'tuning':{'Gomoku.Win1':.6}}]}
 def test_prerequisites_only_no_game_writes(self):
  result=p.save(self.store,dict(projectId=self.id,revision=self.store.revision(self.project),enabled=[p.UP,p.CAMPUS]),b)
  self.assertEqual(len(result['catalog']['games']),12);self.assertFalse((self.cfg/'MinigameCfg.json').exists());self.assertEqual(self.protected.read_bytes(),self.before)
 def test_group_native_cfg_and_registration_reload_preserve_other_files(self):
  result=p.save(self.store,self.request(),b);g=result['groups'][0]
  self.assertEqual(g['tuning'],{'Gomoku.Win1':.6});self.assertEqual(g['levels'][0]['id'],12345601)
  reg=b.read_json(self.project.path/p.REG)['minigames'][0];self.assertEqual((reg['type'],reg['targetId']),('template',9102));self.assertNotIn('dll',reg)
  self.assertEqual(self.protected.read_bytes(),self.before)
  import character_rules
  p.save(self.store,dict(projectId=self.id,editing=True),b)
  refs=character_rules.references(self.store,self.project);self.assertIn('9102',refs['MinigameCfg']);self.assertIn('123456',refs['pluginGameIds']);self.assertEqual(refs['MinigameCfg']['123456']['name'],g['name'])
 def test_external_change_rejects_even_same_size(self):
  req=self.request();p.save(self.store,req,b);req['revision']=self.store.revision(self.project)
  path=self.project.path/p.REG;stat=path.stat();path.write_bytes(path.read_bytes().replace(b'0.6',b'0.7'));os.utime(path,ns=(stat.st_atime_ns,stat.st_mtime_ns));before=path.read_bytes()
  with self.assertRaises(b.ApiError) as ctx:p.save(self.store,req,b)
  self.assertEqual(ctx.exception.code,'conflict');self.assertEqual(path.read_bytes(),before)
 def test_bounds_prereq_missing_and_unbound_talk_rejected(self):
  for mutate in (lambda r:r.update(enabled=[p.CAMPUS]),lambda r:r['groups'][0]['tuning'].update({'Gomoku.Win1':2}),lambda r:r['groups'][0]['levels'][0].update(startTalk=404),lambda r:r['groups'][0].update(id=2147483647)):
   req=self.request();mutate(req)
   with self.assertRaises(b.ApiError):p.save(self.store,req,b)
  self.assertFalse((self.project.path/p.REG).exists())
 def test_external_cfg_fields_and_registrations_preserved(self):
  p.save(self.store,self.request(),b);path=self.cfg/'MinigameActionCfg.json';rows=b.read_json(path);rows['12345601']['future']={'stay':1};rows['12345601']['effect']=[[5,2]];b.atomic_write(path,b.json_bytes(rows))
  regpath=self.project.path/p.REG;reg=b.read_json(regpath);reg['future']='keep';reg['minigames'].append({'id':88888,'type':'dialogue'});b.atomic_write(regpath,b.json_bytes(reg))
  data=p.load(self.store,self.id,b);data['groups'][0]['name']='改名';p.save(self.store,dict(data,projectId=self.id),b)
  self.assertEqual(b.read_json(path)['12345601']['effect'],[[5,2]]);self.assertEqual(b.read_json(path)['12345601']['future'],{'stay':1});self.assertIn({'id':88888,'type':'dialogue'},b.read_json(regpath)['minigames']);self.assertEqual(b.read_json(regpath)['future'],'keep')
 def test_bound_group_cannot_remove(self):
  p.save(self.store,self.request(),b);b.atomic_write(self.cfg/'PersonGrowCfg.json',b.json_bytes({'3':{'id':3,'minigame':123456}}))
  req=self.request();req['groups']=[]
  with self.assertRaises(b.ApiError):p.save(self.store,req,b)
 def test_all_twelve_templates_roundtrip_without_changing_native_stage_contract(self):
  data=p.catalog(b);req=self.request();req['groups']=[]
  for template in range(9101,9113):
   ident=120000+template;levels=[]
   for row in data['stages'].values():
    if row['id']//100==template and row['id']%100<=5:levels.append({**row,'id':ident*100+row['id']%100})
   req['groups'].append(dict(id=ident,template=template,name='测试'+str(template),levels=levels,tuning={}))
  result=p.save(self.store,req,b);self.assertEqual(len(result['groups']),12)
  for g in result['groups']:
   for i,row in enumerate(g['levels'],1):
    self.assertEqual({**row,'id':g['template']*100+i},data['stages'][str(g['template']*100+i)])
  self.assertEqual(self.protected.read_bytes(),self.before)
 def test_external_template_is_authoritative_and_prerequisite_save_retains_levels(self):
  p.save(self.store,self.request(),b);path=self.project.path/p.REG;reg=b.read_json(path)
  reg['minigames'][0].update(targetId=9103,parameters={'tuning':{'Bubble.Range':3},'future':'kept'})
  b.atomic_write(path,b.json_bytes(reg));data=p.load(self.store,self.id,b)
  self.assertEqual(data['groups'][0]['template'],9103)
  result=p.save(self.store,dict(projectId=self.id,revision=data['revision'],enabled=data['enabled']),b)
  self.assertEqual(result['groups'][0]['levels'],data['groups'][0]['levels'])
  self.assertEqual(b.read_json(path)['minigames'][0]['targetId'],9103)
  self.assertEqual(b.read_json(path)['minigames'][0]['parameters']['future'],'kept')
 def test_malformed_requests_and_external_registration_never_write(self):
  for g in (None,dict(id=123456,template=[],name='a'),dict(id=123456,template=9102,name=1),dict(id=123456,template=9102,name='a',levels=[None])):
   req=self.request();req['groups']=[g]
   with self.assertRaises(b.ApiError):p.save(self.store,req,b)
  p.save(self.store,self.request(),b);path=self.project.path/p.REG
  for reg in (None,{'minigames':[None]},{'minigames':[{'id':123456,'type':'dialogue'}]}, {'minigames':[]}):
   b.atomic_write(path,b.json_bytes(reg));before=path.read_bytes()
   with self.assertRaises(b.ApiError):p.load(self.store,self.id,b)
   with self.assertRaises(b.ApiError):p.save(self.store,self.request(),b)
   self.assertEqual(path.read_bytes(),before)
 def test_mid_read_external_change_is_conflict(self):
  p.save(self.store,self.request(),b);original=self.store.editing_rows
  def changed(project,name):
   rows=original(project,name)
   if name=='MinigameCfg':self.protected.write_text('{"4":{"id":4}}')
   return rows
  with patch.object(self.store,'editing_rows',side_effect=changed):
   with self.assertRaises(b.ApiError) as ctx:p.load(self.store,self.id,b)
  self.assertEqual(ctx.exception.code,'conflict')
 def test_mode_is_session_only_and_never_removes_bindings(self):
  p.save(self.store,self.request(),b);before={f:f.read_bytes() for f in self.project.path.rglob('*.json')}
  import character_rules
  self.assertNotIn('123456',character_rules.references(self.store,self.project)['MinigameCfg'])
  self.assertNotIn('123456',self.store.table(self.id,'MinigameCfg')['rows'])
  self.assertIn('123456',self.store.table(self.id,'MinigameCfg')['localRows'])
  p.save(self.store,dict(projectId=self.id,editing=True),b)
  self.assertIn('123456',character_rules.references(self.store,self.project)['MinigameCfg'])
  other=self.store.project(self.store.create('另一个模组')['id']);self.assertFalse(p.editing(other))
  p.save(self.store,dict(projectId=self.id,editing=False),b)
  import external_usages
  self.assertIn('123456',external_usages.rows_for(self.store,self.project,'MinigameCfg'))
  self.assertNotIn('123456',external_usages.catalog(self.store,self.id,b)['refs']['MinigameCfg'])
  for f,content in before.items():self.assertEqual(f.read_bytes(),content)
 def test_builtin_overlay_preserves_native_fields_and_registration(self):
  p.save(self.store,self.request(),b)
  regpath=self.project.path/p.REG;reg=b.read_json(regpath);reg['future']='keep';b.atomic_write(regpath,b.json_bytes(reg))
  rows={'910201':{**p.catalog(b)['stages']['910201'],'future':'keep','effect':[[5,2]]}}
  b.atomic_write(self.cfg/'MinigameActionCfg.json',b.json_bytes({**b.read_json(self.cfg/'MinigameActionCfg.json'),**rows}))
  data=p.load(self.store,self.id,b);g=next(g for g in data['builtin'] if g['id']==9102);g['tuning']={'Gomoku.Win1':.5};g['levels'][0]['cost']=3
  result=p.save(self.store,dict(projectId=self.id,revision=data['revision'],builtin=g),b)
  after=b.read_json(regpath);self.assertEqual(after['minigames'],reg['minigames']);self.assertEqual(after['future'],'keep');self.assertEqual(after['overrides']['9102']['tuning'],g['tuning'])
  row=b.read_json(self.cfg/'MinigameActionCfg.json')['910201'];self.assertEqual(row['future'],'keep');self.assertEqual(row['effect'],[[5,2]]);self.assertEqual(row['cost'],3);self.assertEqual(self.protected.read_bytes(),self.before)
 def test_builtin_invalid_values_and_conflict_write_nothing(self):
  p.save(self.store,self.request(),b);data=p.load(self.store,self.id,b);baseline=next(g for g in data['builtin'] if g['id']==9102)
  before={f:f.read_bytes() for f in self.project.path.rglob('*.json')}
  for mutate in (lambda g:g.update(tuning={'Gomoku.Win1':2}),lambda g:g.update(tuning={'invented':1}),lambda g:g['levels'][0].update(startTalk=404),lambda g:g['levels'].pop()):
   g=copy.deepcopy(baseline);mutate(g)
   with self.assertRaises(b.ApiError):p.save(self.store,dict(projectId=self.id,revision=data['revision'],builtin=g),b)
   for f,content in before.items():self.assertEqual(f.read_bytes(),content)
  with self.assertRaises(b.ApiError):p.save(self.store,dict(projectId=self.id,revision='stale',builtin=baseline),b)
 def test_original_view_keeps_hidden_plugin_groups(self):
  p.save(self.store,self.request(),b)
  before=b.read_json(self.cfg/'MinigameCfg.json')['123456'];stage=b.read_json(self.cfg/'MinigameActionCfg.json')['12345601']
  import original_mode
  with original_mode.scope(self.id):
   data=p.load(self.store,self.id,b);g=next(g for g in data['builtin'] if g['id']==9102);g['levels'][0]['cost']=3
   p.save(self.store,dict(projectId=self.id,revision=data['revision'],builtin=g),b)
  self.assertEqual(b.read_json(self.cfg/'MinigameCfg.json')['123456'],before)
  self.assertEqual(b.read_json(self.cfg/'MinigameActionCfg.json')['12345601'],stage)
 def test_bundled_settings_are_actual_plugin_schema(self):
  data=p.catalog(b);self.assertEqual(len(data['games']),12);self.assertEqual(len(data['settings']),140)
  self.assertEqual({x['id'] for x in data['bundled']['plugins']},{p.UP,p.CAMPUS})
  self.assertEqual({str(r['id']) for r in data['upRegistration']['minigames']},set(data['games']))
 def test_delete_two_clicks_recovery_and_expired_revision(self):
  req={'projectId':self.id};first=removal.remove(self.store,req,b);self.assertTrue(self.project.path.exists())
  result=removal.remove(self.store,dict(req,confirmation=first['confirmation']),b)
  self.assertFalse(self.project.path.exists());self.assertEqual((Path(result['recoveryPath'])/'Cfgs/zh-cn/KZoneProfileCfg.json').read_bytes(),self.before)
  with self.assertRaises(b.ApiError):removal.remove(self.store,dict(req,confirmation=first['confirmation']),b)
 def test_delete_conflict_and_readonly(self):
  first=removal.remove(self.store,{'projectId':self.id},b);self.protected.write_text('{}')
  with self.assertRaises(b.ApiError):removal.remove(self.store,dict(projectId=self.id,confirmation=first['confirmation']),b)
  self.assertTrue(self.project.path.exists())
  dest=self.store.workshop/'sub';dest.mkdir(parents=True);b.atomic_write(dest/'manifest.json',b.json_bytes({'title':'订阅'}));ident=next(p.id for p in self.store.projects() if p.readonly)
  token=removal.remove(self.store,{'projectId':ident},b)['confirmation']
  hidden=removal.remove(self.store,{'projectId':ident,'confirmation':token},b)
  self.assertTrue(hidden['hidden']);self.assertTrue(dest.is_dir());self.assertNotIn(ident,[p.id for p in self.store.projects()])
 def test_player_prefs_and_import_do_not_touch_mod(self):
  out=music.access(self.store,b);self.assertEqual(out['tracks'][0]['id'],'tifa-theme');self.assertTrue(out['tracks'][0]['bundled']);self.assertEqual(len([r for r in out['tracks'] if r.get('bundled')]),4)
  raw=b'RIFF'+b'\x00'*4+b'WAVEfmt '+b'\x00'*32
  music.access(self.store,b,dict(mode='shuffle',collapsed=True,volume=.4,fileName='music.wav',data=base64.b64encode(raw).decode()))
  self.assertEqual(music.media(b).read_bytes(),raw);self.assertTrue(music.access(self.store,b)['preferences']['collapsed']);self.assertEqual(self.protected.read_bytes(),self.before)
  with self.assertRaises(b.ApiError):music.access(self.store,b,dict(fileName='fake.mp3',data=base64.b64encode(b'<html>notmusic').decode()))

if __name__=='__main__':unittest.main()
