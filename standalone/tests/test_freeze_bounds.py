"""No editor request may wait without a bound: a stalled peer must surface as an error.

Windows users reported the editor freezing permanently. Every unbounded wait on a
request path is covered here: the project save lock and the portrait-size measurement.
"""
import json,os,sys,tempfile,threading,time,unittest,urllib.error,urllib.request
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import platform_support
import server as b


class UnboundedWaitTests(unittest.TestCase):
 def test_lock_file_gives_up_instead_of_spinning_forever(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'busy.lock'
   with path.open('a+b') as holder:
    platform_support.lock_file(holder)
    with path.open('a+b') as second:
     started=time.monotonic()
     with patch.object(platform_support,'LOCK_TIMEOUT',0.3):
      with self.assertRaises(BlockingIOError):platform_support.lock_file(second)
     self.assertLess(time.monotonic()-started,5,'a held lock must not block without a deadline')
    platform_support.unlock_file(holder)
    # The lock is usable again once its owner released it.
    with path.open('a+b') as third:
     platform_support.lock_file(third,timeout=2);platform_support.unlock_file(third)

 def test_non_blocking_callers_still_fail_immediately(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'busy.lock'
   with path.open('a+b') as holder:
    platform_support.lock_file(holder)
    with path.open('a+b') as second:
     started=time.monotonic()
     with self.assertRaises(BlockingIOError):platform_support.lock_file(second,blocking=False)
     self.assertLess(time.monotonic()-started,1)
    platform_support.unlock_file(holder)

 def test_windows_lock_branch_gives_up_instead_of_spinning_forever(self):
  # The freeze was reported on Windows and cannot be reproduced here, so the Windows
  # branch itself is exercised against a stubbed msvcrt.
  import errno
  from types import SimpleNamespace
  def deny(*args,**kwargs):raise OSError(errno.EACCES,'locked by another process')
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'windows.lock'
   with path.open('a+b') as stream,patch.object(platform_support.os,'name','nt'),patch.object(platform_support,'msvcrt',SimpleNamespace(LK_NBLCK=2,LK_UNLCK=0,locking=deny),create=True):
    started=time.monotonic()
    with self.assertRaises(BlockingIOError):platform_support.lock_file(stream,timeout=0.3)
    self.assertLess(time.monotonic()-started,5)
    # An empty lock file gains the single byte msvcrt locks.
    self.assertGreater(path.stat().st_size,0)

 def test_windows_lock_branch_returns_while_the_lock_is_free(self):
  from types import SimpleNamespace
  calls=[]
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'windows.lock'
   with path.open('a+b') as stream,patch.object(platform_support.os,'name','nt'),patch.object(platform_support,'msvcrt',SimpleNamespace(LK_NBLCK=2,LK_UNLCK=0,locking=lambda *args:calls.append(args)),create=True):
    started=time.monotonic();platform_support.lock_file(stream,timeout=0.3)
    self.assertLess(time.monotonic()-started,1);self.assertEqual(len(calls),1)

 def test_save_reports_busy_while_another_window_holds_the_project_lock(self):
  with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{k:tmp+'/'+v for k,v in [('STUDIO_USER_DATA_ROOT','User'),('STUDIO_CACHE_ROOT','Cache'),('STUDIO_BACKUP_ROOT','Backups'),('STUDIO_DISPLAY_SETTINGS','display.json'),('STUDIO_ERROR_LOG_ROOT','Logs')]}):
   root=Path(tmp);store=b.StudioStore(root/'Mods',root/'Workshop',root/'Game',asset_settings_path=root/'assets.json',migrate_cache=False)
   project=store.project(store.create('测试')['id']);revision=store.revision(project)
   host=b.StudioServer(('127.0.0.1',0),store);thread=threading.Thread(target=host.serve_forever,daemon=True);thread.start()
   def post(route,payload):
    request=urllib.request.Request(host.origin+route,json.dumps(payload).encode(),headers={'X-Studio-Token':host.token,'Content-Type':'application/json'})
    try:
     with urllib.request.urlopen(request,timeout=20) as response:return response.status,json.load(response)
    except urllib.error.HTTPError as error:return error.status,json.load(error)
   payload={'projectId':project.id,'revision':revision,'talkPatch':{'version':1,'upsert':{'900001001':{'id':900001001,'content':'锁被占用'}},'deleted':[]}}
   lock_path=project.path/'StudentAgeStudio/.save.lock';lock_path.parent.mkdir(parents=True,exist_ok=True)
   try:
    # Another editor window is saving: the request answers with a retryable message
    # instead of hanging on the lock for as long as that window lives.
    with lock_path.open('a+b') as holder:
     platform_support.lock_file(holder)
     with patch.object(platform_support,'LOCK_TIMEOUT',0.4):
      started=time.monotonic();status,body=post('/api/save',payload);elapsed=time.monotonic()-started
     self.assertEqual(status,409);self.assertEqual(body.get('code'),'save_busy');self.assertLess(elapsed,10)
     platform_support.unlock_file(holder)
    # Saving works again as soon as the lock is free.
    status,body=post('/api/save',payload)
    self.assertEqual(status,200);self.assertTrue(body.get('ok'))
   finally:
    host.shutdown();host.server_close();host.media_warmup.close();thread.join();store.close()

 def test_portrait_measurement_answers_while_the_background_pass_is_stuck(self):
  import importlib.util
  from types import SimpleNamespace
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);bundle=root/'textures_assets_role.bundle';bundle.write_bytes(b'role bytes');cache=root/'cache';cache.mkdir()
   with patch.dict(sys.modules,{'UnityPy':SimpleNamespace(),'UnityPy.helpers':SimpleNamespace(CompressionHelper=SimpleNamespace())}):
    spec=importlib.util.spec_from_file_location('freeze_bound_fixture',Path(__file__).resolve().parents[1]/'extract_game_assets.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
   module._portrait_seed=None;module._portrait_retry.clear();module._portrait_unpacking.clear()
   class _Done:
    def __init__(self,thread):self.thread=thread
    def wait(self,timeout=None):self.thread.join(timeout);return 0
   def _inline(game,catalog,paths):
    # Another thread stands in for the worker process production spawns.
    def run():
     try:
      with module._portrait_dimensions_lock:
       module._portrait_dimensions(game,catalog,paths,time.monotonic()+module.PORTRAIT_UNPACK_BUDGET,unpack=True)
     except Exception:pass
    thread=threading.Thread(target=run,daemon=True);thread.start();return _Done(thread)
   module._portrait_unpack_runner=_inline
   mapping={'role_full/person':'assets/role_full.png'}
   catalog={'assetMap':{**mapping,**{'Textures/'+k:v for k,v in mapping.items()}},'bundles':{bundle.name:'fixture'},'bundleOutputs':{bundle.name:list(mapping.values())}}
   release=threading.Event();entered=threading.Event()
   def stuck(path):
    entered.set();release.wait(30);raise RuntimeError('bundle read never finishes')
   with patch.object(module,'game_cache',return_value=cache),patch.object(module.UnityPy,'load',side_effect=stuck,create=True):
    try:
     started=time.monotonic();self.assertEqual(module.portrait_dimensions(root,catalog,list(mapping)),{})
     self.assertLess(time.monotonic()-started,module.PORTRAIT_DIMENSION_BUDGET+1)
     self.assertTrue(entered.wait(5))
     for _ in range(3):
      started=time.monotonic();self.assertEqual(module.portrait_dimensions(root,catalog,list(mapping)),{})
      self.assertLess(time.monotonic()-started,1)
    finally:
     release.set();module._portrait_unpack_thread.join(10)


class ColdCacheResponseTests(unittest.TestCase):
 def server(self,tmp):
  root=Path(tmp)
  store=b.StudioStore(root/'Mods',root/'Workshop',root/'Game',asset_settings_path=root/'assets.json',migrate_cache=False)
  host=b.StudioServer(('127.0.0.1',0),store);thread=threading.Thread(target=host.serve_forever,daemon=True);thread.start()
  return store,host,thread

 def test_native_portrait_keeps_asking_instead_of_using_exported_pixels(self):
  import importlib.util
  from PIL import Image
  from types import SimpleNamespace
  with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{k:tmp+'/'+v for k,v in [('STUDIO_USER_DATA_ROOT','User'),('STUDIO_CACHE_ROOT','Cache'),('STUDIO_BACKUP_ROOT','Backups'),('STUDIO_DISPLAY_SETTINGS','display.json'),('STUDIO_ERROR_LOG_ROOT','Logs')]}):
   # The route imports the real asset module, which needs UnityPy only to unpack a
   # bundle; a stub keeps this a cold-cache test rather than an unpack test.
   with patch.dict(sys.modules,{'UnityPy':SimpleNamespace(),'UnityPy.helpers':SimpleNamespace(CompressionHelper=SimpleNamespace())}):
    spec=importlib.util.spec_from_file_location('cold_cache_assets',Path(__file__).resolve().parents[1]/'extract_game_assets.py');assets=importlib.util.module_from_spec(spec);spec.loader.exec_module(assets)
   store,host,thread=self.server(tmp)
   project=store.project(store.create('测试')['id'])
   def post(payload):
    request=urllib.request.Request(host.origin+'/api/portrait-dimensions',json.dumps(payload).encode(),headers={'X-Studio-Token':host.token,'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=20) as response:return response.status,json.load(response)
   exported=Path(tmp)/'exported.png'
   Image.new('RGBA',(262,1200)).save(exported)
   native,custom='Textures/role_full/role_afang','Mods/custom.png'
   catalog={'assetMap':{native:'assets/role_full.png'},'bundles':{},'bundleOutputs':{}}
   try:
    # Cold cache: the game texture has not been measured yet. The exported preview is
    # scaled to a shared height, so answering with its pixels would freeze a wrong
    # portrait size in the editor for the whole session.
    with patch.dict(sys.modules,{'extract_game_assets':assets}),patch.object(assets,'portrait_dimensions',return_value={}),patch.object(store,'asset',return_value=exported),patch.object(store,'catalog',return_value=catalog):
     status,body=post({'projectId':project.id,'paths':[native,custom]})
    self.assertEqual(status,200)
    self.assertNotIn(native,body,'a native portrait must stay unanswered until it is measured')
    # Images that are not game textures keep their own pixels as before.
    self.assertEqual(body.get(custom),[262,1200])
   finally:
    host.shutdown();host.server_close();host.media_warmup.close();thread.join();store.close()

 def test_a_dropped_diagnostic_never_happens_when_another_window_writes_logs(self):
  import error_logs
  with tempfile.TemporaryDirectory() as tmp:
   logs=error_logs.ErrorLogs(root=Path(tmp))
   guard_path=Path(tmp)/'.writer.lock'
   with guard_path.open('a+b') as guard:
    platform_support.lock_file(guard)
    with patch.object(platform_support,'LOCK_TIMEOUT',0.3):
     name=logs.write(RuntimeError('诊断不能丢'),operation='测试')
     self.assertIsNotNone(name,'losing a diagnostic is worse than writing beside another window')
     self.assertTrue((Path(tmp)/name).is_file())
     with self.assertRaises(Exception) as caught:logs.configure({'autoCleanup':True})
     self.assertIn('错误日志',str(caught.exception))
    platform_support.unlock_file(guard)


class MeasurementProcessTests(unittest.TestCase):
 def assets(self):
  import importlib.util
  from types import SimpleNamespace
  with patch.dict(sys.modules,{'UnityPy':SimpleNamespace(),'UnityPy.helpers':SimpleNamespace(CompressionHelper=SimpleNamespace())}):
   spec=importlib.util.spec_from_file_location('measure_process_fixture',Path(__file__).resolve().parents[1]/'extract_game_assets.py')
   module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  module._portrait_unpacking.clear();module._portrait_unpack_runner=None
  return module

 def test_the_default_pass_delegates_to_a_worker_process(self):
  # Reading a role bundle is seconds of work; it must not run in the request process.
  assets=self.assets()
  release=threading.Event()
  class Process:
   pid=4242
   def wait(self,timeout=None):release.wait(timeout);return 0
  with patch.object(assets,'_spawn_portrait_measure',return_value=Process()) as spawn:
   assets._unpack_portraits_in_background(Path('/games/x'),{},['role_full/a'])
   spawn.assert_called_once()
   self.assertTrue(assets._portrait_unpacking.is_set(),'a pass must be marked running until it exits')
   release.set()
  assets._portrait_unpack_thread.join(5)
  self.assertFalse(assets._portrait_unpacking.is_set())

 def test_the_worker_command_carries_the_paths_to_measure(self):
  assets=self.assets()
  class Process:
   pid=1
   def wait(self,timeout=None):return 0
   def kill(self):pass
  with patch('subprocess.Popen',return_value=Process()) as popen:
   assets._spawn_portrait_measure(Path('/games/x'),None,['role_full/a','role_full/b'])
  command=popen.call_args.args[0]
  self.assertIn('--portrait-measure',command)
  self.assertIn('--paths',command)
  self.assertEqual(json.loads(command[command.index('--paths')+1]),['role_full/a','role_full/b'])

 def test_a_listing_render_reuses_recent_fingerprints(self):
  import asset_catalog
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'a.png';path.write_bytes(b'x')
   asset_catalog._fingerprint_cache.clear()
   with patch.object(asset_catalog,'file_fingerprint',wraps=platform_support.file_fingerprint) as reader:
    first=asset_catalog.cached_fingerprint(path);second=asset_catalog.cached_fingerprint(path)
   self.assertEqual(first,second)
   self.assertEqual(reader.call_count,1,'one render must open each file once')
   path.write_bytes(b'changed-size')
   with patch.object(asset_catalog,'file_fingerprint',wraps=platform_support.file_fingerprint) as reader:
    third=asset_catalog.cached_fingerprint(path)
   self.assertEqual(reader.call_count,1,'a changed file is fingerprinted again')
   self.assertNotEqual(third,first)


 def test_a_pass_that_measures_nothing_is_rate_limited(self):
  # The parent cannot see the child's per-bundle backoff, and `needs_unpack` only says a
  # candidate bundle has no entry yet - not that it can be read. Without a limit here,
  # one bundle that never measures would start one more process per request.
  import itertools
  assets=self.assets()
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);game=root/'Game'
   rel='StudentAge_Data/StreamingAssets/aa/StandaloneWindows64/textures_assets_role_fixture.bundle'
   bundle=game/rel;bundle.parent.mkdir(parents=True);bundle.write_bytes(b'x'*1024)
   home=root/'cache';home.mkdir()
   mapping={'role_full/person':'assets/role_full.png'}
   catalog={'assetMap':{**mapping,**{'Textures/'+k:v for k,v in mapping.items()}},'bundles':{rel:'fixture'},'bundleOutputs':{rel:list(mapping.values())}}
   spawned=[]
   class Process:
    pid=1
    def wait(self,timeout=None):return 0
   assets._portrait_unpack_runner=lambda g,c,p:(spawned.append(1),Process())[1]
   clock=itertools.count(1000.0,0.0)
   with patch.object(assets,'game_cache',return_value=home),patch.object(assets.time,'monotonic',side_effect=lambda:next(clock)):
    for _ in range(3):
     assets.portrait_dimensions(game,catalog,['role_full/person'])
     assets._portrait_unpack_thread.join(5)
    self.assertEqual(len(spawned),3,'two passes run immediately, then the curve takes over')
    self.assertEqual(assets._portrait_pass_failures,3)
    assets.portrait_dimensions(game,catalog,['role_full/person'])
    assets._portrait_unpack_thread.join(5)
    self.assertEqual(len(spawned),3,'a request inside the delay must not start another process')

 def test_the_worker_entry_point_runs_in_a_real_process(self):
  # Only "delegated" and "command line" were covered; this runs the worker for real, so a
  # broken entry point or a renamed flag cannot slip into a packaged client.
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);stub=root/'stub'
   (stub/'UnityPy').mkdir(parents=True)
   (stub/'UnityPy'/'__init__.py').write_text(
    "import os\ndef load(path):\n"
    "    marker=os.environ.get('STUB_MARKER')\n"
    "    if marker:\n"
    "        open(marker,'a',encoding='utf-8').write(str(path)+'\\n')\n"
    "    raise OSError('stub: no real bundle')\n",encoding='utf-8')
   (stub/'UnityPy'/'helpers.py').write_text("class CompressionHelper:\n    pass\n",encoding='utf-8')
   marker=root/'loaded.txt';game=root/'Game'
   relative='StudentAge_Data/StreamingAssets/aa/StandaloneWindows64/textures_assets_role_fixture.bundle'
   bundle=game/relative;bundle.parent.mkdir(parents=True);bundle.write_bytes(b'x'*1024)
   standalone=Path(__file__).resolve().parents[1]
   environment={**os.environ,'STUDIO_CACHE_ROOT':str(root/'Cache'),'STUDIO_USER_DATA_ROOT':str(root/'User'),
                'STUB_MARKER':str(marker),'PYTHONPATH':str(stub),'PYTHONDONTWRITEBYTECODE':'1'}
   with patch.dict(os.environ,environment):
    import storage_paths
    home=Path(storage_paths.game_cache(game));home.mkdir(parents=True,exist_ok=True)
    (home/'asset-map.json').write_text(json.dumps({
     'assetMap':{'role_full/person':'assets/role_full.png','Textures/role_full/person':'assets/role_full.png'},
     'bundles':{relative:'fixture'},'bundleOutputs':{relative:['assets/role_full.png']}}),encoding='utf-8')
    command=[sys.executable,'-B',str(standalone/'extract_game_assets.py'),'--game',str(game),
             '--portrait-measure','--paths',json.dumps(['role_full/person'])]
    result=__import__('subprocess').run(command,capture_output=True,text=True,timeout=180,env=environment)
    loaded=marker.read_text(encoding='utf-8') if marker.is_file() else ''
   self.assertEqual(result.returncode,0,result.stderr[-800:])
   self.assertIn('measured',result.stdout,'worker 没有走到测量入口')
   # A tree that vendors its own reader (tools/asset-reader) puts it ahead of this stub,
   # so the marker only exists where the stub is the UnityPy the child imports. The
   # entry point itself is checked either way.
   if not ((standalone/'vendor').exists() or (standalone.parent/'tools'/'asset-reader').exists()):
    self.assertIn('textures_assets_role_fixture.bundle',loaded,'子进程没有真正打开包')


if __name__=='__main__':unittest.main()
