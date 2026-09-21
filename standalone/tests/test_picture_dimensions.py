"""Runtime texture/Sprite size selection and cache migration, without decoding game textures."""
import importlib.util,json,sys,tempfile,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


class Done:
 """Stands in for the measuring process the production code spawns."""
 def __init__(self,thread):self.thread=thread
 def wait(self,timeout=None):self.thread.join(timeout);return 0


def inline_runner(module):
 """Measure in another thread so a test can stub UnityPy and the game folder.

 Production spawns a separate process for exactly the reason these tests check: the
 request must come back before the bundle has been read.
 """
 def runner(game,catalog,paths):
  def run():
   try:
    with module._portrait_dimensions_lock:
     module._portrait_dimensions(game,catalog,paths,time.monotonic()+module.PORTRAIT_UNPACK_BUDGET,unpack=True)
   except Exception:
    pass
  thread=threading.Thread(target=run,daemon=True,name='portrait-measure-test');thread.start()
  return Done(thread)
 return runner


class Clock:
 """A monotonic clock the test moves by hand."""
 def __init__(self,start=1000.0):self.value=start
 def __call__(self):return self.value
 def advance(self,seconds):self.value+=seconds


def load_module(name):
 with patch.dict(sys.modules,{'UnityPy':SimpleNamespace(), 'UnityPy.helpers':SimpleNamespace(CompressionHelper=SimpleNamespace())}):
  spec=importlib.util.spec_from_file_location(name,Path(__file__).resolve().parents[1]/'extract_game_assets.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 module._portrait_seed=None;module._portrait_retry.clear();module._portrait_unpacking.clear()
 module._portrait_unpack_runner=inline_runner(module)
 return module


def finish_unpack(module,timeout=10):
 thread=getattr(module,'_portrait_unpack_thread',None)
 if thread is not None:thread.join(timeout)
 return thread


class PictureDimensionTests(unittest.TestCase):
 def test_all_character_picture_sizes_use_runtime_textures_and_invalidate_old_cache(self):
  kinds=('role_full','role_half','role_head','role_comic','role_comic_head','role_photo')
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);bundle=root/'textures_assets_role.bundle';bundle.write_bytes(b'unchanged game bundle');cache=root/'cache';cache.mkdir()
   old=cache/'portrait-dimensions-v4.json';old.write_text('{"old":"imported sprite units"}');before=old.read_bytes()
   objects=[];mapping={}
   for index,kind in enumerate(kinds):
    mapping[kind+'/person']='assets/'+kind+'.png'
    texture=SimpleNamespace(type=SimpleNamespace(name='Texture2D'),parse_as_object=lambda:SimpleNamespace(m_Width=500,m_Height=2000))
    sprite=SimpleNamespace(type=SimpleNamespace(name='Sprite'),parse_as_object=lambda:SimpleNamespace(m_Rect=SimpleNamespace(width=500,height=2000),m_PixelsToUnits=80))
    for obj in ((sprite,texture) if index%2 else (texture,sprite)):objects.append(('assets/res/textures/'+kind+'/person.png',SimpleNamespace(deref=lambda obj=obj:obj)))
   env=SimpleNamespace(container=SimpleNamespace(items=lambda:objects))
   module=load_module('picture_dimension_fixture')
   loaders=[]
   def load(path):loaders.append(threading.current_thread());return env
   with patch.object(module,'game_cache',return_value=cache),patch.object(module.UnityPy,'load',side_effect=load,create=True) as load:
    unrelated=root/'textures_assets_role_unrelated.bundle';unrelated.write_bytes(b'other portraits')
    catalog={'assetMap':{**mapping,**{'Textures/'+k:v for k,v in mapping.items()}},'bundles':{bundle.name:'fixture',unrelated.name:'fixture'},'bundleOutputs':{bundle.name:list(mapping.values()),unrelated.name:['assets/unrelated.png']}}
    # A request never unpacks a bundle: it answers from what earlier passes measured and
    # hands the measuring to one background pass instead of blocking the editor. The
    # empty answer already proves the request did not measure; unpacking may legitimately
    # start on the background thread before this line runs.
    self.assertEqual(module.portrait_dimensions(root,catalog,list(mapping)),{})
    finish_unpack(module)
    self.assertTrue(loaders and all(t is not threading.main_thread() for t in loaders),'解包必须发生在后台线程')
    self.assertEqual(module.portrait_dimensions(root,catalog,list(mapping)),{k:[500,2000] for k in mapping})
    load.assert_called_once()
    self.assertEqual(module.portrait_dimensions(root,catalog,['Mods/a.png']),{})
    # DLC portraits live in a mixed texture bundle, without "role" in its name.
    dlc=root/'dlc_textures_assets__fixture.bundle';dlc.write_bytes(b'DLC')
    dlc_catalog={'assetMap':catalog['assetMap'],'bundles':{dlc.name:'fixture'},'bundleOutputs':{dlc.name:list(mapping.values())}}
    self.assertEqual(module.portrait_dimensions(root,dlc_catalog,list(mapping)),{})
    finish_unpack(module)
    self.assertEqual(module.portrait_dimensions(root,dlc_catalog,list(mapping)),{k:[500,2000] for k in mapping})
   self.assertEqual(old.read_bytes(),before)

 def test_a_stalled_bundle_never_blocks_a_request(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);bundle=root/'textures_assets_role.bundle';bundle.write_bytes(b'huge role bundle');cache=root/'cache';cache.mkdir()
   module=load_module('stalled_dimension_fixture')
   mapping={'role_full/person':'assets/role_full.png'}
   catalog={'assetMap':{**mapping,**{'Textures/'+k:v for k,v in mapping.items()}},'bundles':{bundle.name:'fixture'},'bundleOutputs':{bundle.name:list(mapping.values())}}
   release=threading.Event();entered=threading.Event()
   def stalled(path):
    entered.set();release.wait(20);return SimpleNamespace(container=SimpleNamespace(items=list))
   with patch.object(module,'game_cache',return_value=cache),patch.object(module.UnityPy,'load',side_effect=stalled,create=True):
    try:
     started=time.monotonic()
     self.assertEqual(module.portrait_dimensions(root,catalog,list(mapping)),{})
     self.assertLess(time.monotonic()-started,module.PORTRAIT_DIMENSION_BUDGET+1)
     self.assertTrue(entered.wait(5))
     # While the pass is stuck inside the bundle, requests keep answering immediately.
     first=module._portrait_unpack_thread
     running=time.monotonic()
     self.assertEqual(module.portrait_dimensions(root,catalog,list(mapping)),{})
     self.assertLess(time.monotonic()-running,1)
     # A repeated request must not start a second pass for the same bundle.
     self.assertIs(module._portrait_unpack_thread,first)
    finally:release.set()
    finish_unpack(module)

 def test_measured_bundles_are_not_unpacked_again_for_the_same_resources(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);bundle=root/'textures_assets_role.bundle';bundle.write_bytes(b'role bytes');cache=root/'cache';cache.mkdir()
   module=load_module('incremental_dimension_fixture')
   mapping={'role_full/person':'assets/role_full.png'}
   catalog={'assetMap':{**mapping,**{'Textures/'+k:v for k,v in mapping.items()}},'bundles':{bundle.name:'fixture'},'bundleOutputs':{bundle.name:list(mapping.values())}}
   objects=[('assets/res/textures/role_full/person.png',SimpleNamespace(deref=lambda:SimpleNamespace(type=SimpleNamespace(name='Texture2D'),parse_as_object=lambda:SimpleNamespace(m_Width=423,m_Height=2048))))]
   env=SimpleNamespace(container=SimpleNamespace(items=lambda:objects))
   with patch.object(module,'game_cache',return_value=cache),patch.object(module.UnityPy,'load',return_value=env,create=True) as load:
    self.assertEqual(module.portrait_dimensions(root,catalog,list(mapping)),{})
    finish_unpack(module)
    for _ in range(3):self.assertEqual(module.portrait_dimensions(root,catalog,list(mapping)),{'role_full/person':[423,2048]})
    load.assert_called_once()
    # A resource this bundle does not contain is not searched for over and over: a
    # fully measured bundle is never reopened for a portrait it does not hold.
    missing={'role_full/absent':'assets/absent.png'}
    absent={'assetMap':{**missing,**{'Textures/'+k:v for k,v in missing.items()}},'bundles':{bundle.name:'fixture'},'bundleOutputs':{bundle.name:list(missing.values())}}
    for _ in range(2):
     self.assertEqual(module.portrait_dimensions(root,absent,list(missing)),{})
     finish_unpack(module)
    self.assertEqual(load.call_count,1)

 def test_known_measurements_require_exact_bundle_bytes(self):
  import hashlib
  module=load_module('dimension_seed_fixture')
  with tempfile.TemporaryDirectory() as tmp:
   bundle=Path(tmp)/'role.bundle';bundle.write_bytes(b'exact-original')
   entry={'size':14,'sha256':hashlib.sha256(b'exact-original').hexdigest(),'sizes':{'role_full/person':[1081,2704]}}
   seed=SimpleNamespace(read_text=lambda **kwargs:json.dumps({'version':2,'bundles':{'role.bundle':entry}}))
   with patch.object(module.Path,'with_name',return_value=seed):
    module._portrait_seed=None
    self.assertEqual(module._known_portrait_dimensions(bundle,'role.bundle'),entry['sizes'])
    bundle.write_bytes(b'edited-original')
    self.assertIsNone(module._known_portrait_dimensions(bundle,'role.bundle'))
    bundle.write_bytes(b'EXACT-original')
    self.assertIsNone(module._known_portrait_dimensions(bundle,'role.bundle'))
    self.assertIsNone(module._known_portrait_dimensions(bundle,'other.bundle'))
   with patch.object(module.Path,'with_name',return_value=SimpleNamespace(read_text=lambda **kwargs:json.dumps({'version':1,'bundles':{'role.bundle':entry}}))):
    module._portrait_seed=None
    bundle.write_bytes(b'exact-original')
    self.assertIsNone(module._known_portrait_dimensions(bundle,'role.bundle'))

 def test_seed_verification_stops_at_the_request_deadline(self):
  """The only request-path read of game bytes must respect the same budget."""
  import hashlib,itertools
  module=load_module('seed_deadline_fixture')
  with tempfile.TemporaryDirectory() as tmp:
   payload=b'x'*(4<<20)
   bundle=Path(tmp)/'role.bundle';bundle.write_bytes(payload)
   entry={'size':len(payload),'sha256':hashlib.sha256(payload).hexdigest(),'sizes':{'role_full/person':[500,2000]}}
   seed=SimpleNamespace(read_text=lambda **kwargs:json.dumps({'version':2,'bundles':{'role.bundle':entry}}))
   clock=itertools.count(0.0,1.0)
   with patch.object(module.Path,'with_name',return_value=seed),patch.object(module.time,'monotonic',side_effect=lambda:next(clock)):
    module._portrait_seed=None
    # A clock that moves past the deadline stops the hash instead of finishing it.
    self.assertIsNone(module._known_portrait_dimensions(bundle,'role.bundle',deadline=0.5))
    # Without a deadline the same bundle is still verified exactly.
    self.assertEqual(module._known_portrait_dimensions(bundle,'role.bundle'),entry['sizes'])

 def test_a_transient_read_failure_recovers_after_the_delay(self):
  """Two quick failures must not disable measurement for the session."""
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);bundle=root/'textures_assets_role.bundle';bundle.write_bytes(b'role bytes');cache=root/'cache';cache.mkdir()
   module=load_module('retry_recovery_fixture')
   module.PORTRAIT_RETRY_BASE=30.0
   mapping={'role_full/person':'assets/role_full.png'}
   catalog={'assetMap':{**mapping,**{'Textures/'+k:v for k,v in mapping.items()}},'bundles':{bundle.name:'fixture'},'bundleOutputs':{bundle.name:list(mapping.values())}}
   objects=[('assets/res/textures/role_full/person.png',SimpleNamespace(deref=lambda:SimpleNamespace(type=SimpleNamespace(name='Texture2D'),parse_as_object=lambda:SimpleNamespace(m_Width=423,m_Height=2048))))]
   env=SimpleNamespace(container=SimpleNamespace(items=lambda:objects))
   clock=Clock();calls=[]
   def load(path):
    calls.append(1)
    if len(calls)<=3:raise OSError(13,'antivirus holds the file')
    return env
   with patch.object(module,'game_cache',return_value=cache),patch.object(module.UnityPy,'load',side_effect=load,create=True),patch.object(module.time,'monotonic',clock):
    for _ in range(4):
     module.portrait_dimensions(root,catalog,list(mapping));finish_unpack(module)
    self.assertEqual(len(calls),3,'two failures retry immediately')
    # Backed off now: the same bundle is not reopened while the delay has not elapsed.
    module.portrait_dimensions(root,catalog,list(mapping));finish_unpack(module)
    self.assertEqual(len(calls),3)
    self.assertEqual(module.portrait_dimensions(root,catalog,list(mapping)),{})
    # Once the delay elapses the bundle is measured again and the size arrives.
    clock.advance(module.PORTRAIT_RETRY_BASE+1)
    module.portrait_dimensions(root,catalog,list(mapping));finish_unpack(module)
    self.assertEqual(len(calls),4)
    self.assertEqual(module.portrait_dimensions(root,catalog,list(mapping)),{'role_full/person':[423,2048]})

 def test_the_worker_reads_the_three_maps_it_needs(self):
  module=load_module('measure_catalog_fixture')
  with tempfile.TemporaryDirectory() as tmp:
   cache=Path(tmp)/'cache';cache.mkdir()
   (cache/'asset-map.json').write_text(json.dumps({'assetMap':{'a':1},'bundles':{'b':2},'bundleOutputs':{'c':3},'failures':[]}),encoding='utf-8')
   with patch.object(module,'game_cache',return_value=cache):
    self.assertEqual(module.measure_catalog(tmp),{'assetMap':{'a':1},'bundles':{'b':2},'bundleOutputs':{'c':3}})
   (cache/'asset-map.json').write_text('{broken',encoding='utf-8')
   with patch.object(module,'game_cache',return_value=cache):
    self.assertEqual(module.measure_catalog(tmp),{})

 def test_atlas_only_sprites_keep_native_units(self):
  module=load_module('atlas_dimension_fixture')
  sprite=SimpleNamespace(type=SimpleNamespace(name='Sprite'),parse_as_object=lambda:SimpleNamespace(m_Rect=SimpleNamespace(width=114,height=137),m_PixelsToUnits=50))
  env=SimpleNamespace(container={'assets/res/textures/role_comic/person.png':SimpleNamespace(deref=lambda:sprite)})
  self.assertEqual(module._portrait_resource_dimensions(env),{'role_comic/person':[228,274]})
