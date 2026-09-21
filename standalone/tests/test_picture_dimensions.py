"""Runtime texture/Sprite size selection and cache migration, without decoding game textures."""
import importlib.util,json,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

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
   with patch.dict(sys.modules,{'UnityPy':SimpleNamespace(), 'UnityPy.helpers':SimpleNamespace(CompressionHelper=SimpleNamespace())}):
    spec=importlib.util.spec_from_file_location('picture_dimension_fixture',Path(__file__).resolve().parents[1]/'extract_game_assets.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
   with patch.object(module,'game_cache',return_value=cache),patch.object(module.UnityPy,'load',return_value=env,create=True) as load:
    unrelated=root/'textures_assets_role_unrelated.bundle';unrelated.write_bytes(b'other portraits')
    catalog={'assetMap':{**mapping,**{'Textures/'+k:v for k,v in mapping.items()}},'bundles':{bundle.name:'fixture',unrelated.name:'fixture'},'bundleOutputs':{bundle.name:list(mapping.values()),unrelated.name:['assets/unrelated.png']}}
    for _ in range(2):self.assertEqual(module.portrait_dimensions(root,catalog,list(mapping)),{k:[500,2000] for k in mapping})
    load.assert_called_once()
    self.assertEqual(module.portrait_dimensions(root,catalog,['Mods/a.png']),{})
    # DLC portraits live in a mixed texture bundle, without "role" in its name.
    dlc=root/'dlc_textures_assets__fixture.bundle';dlc.write_bytes(b'DLC')
    dlc_catalog={'assetMap':catalog['assetMap'],'bundles':{dlc.name:'fixture'},'bundleOutputs':{dlc.name:list(mapping.values())}}
    self.assertEqual(module.portrait_dimensions(root,dlc_catalog,list(mapping)),{k:[500,2000] for k in mapping})
   self.assertEqual(old.read_bytes(),before)

 def test_known_measurements_require_exact_bundle_bytes(self):
  import hashlib
  with patch.dict(sys.modules,{'UnityPy':SimpleNamespace(), 'UnityPy.helpers':SimpleNamespace(CompressionHelper=SimpleNamespace())}):
   spec=importlib.util.spec_from_file_location('dimension_seed_fixture',Path(__file__).resolve().parents[1]/'extract_game_assets.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  with tempfile.TemporaryDirectory() as tmp:
   bundle=Path(tmp)/'role.bundle';bundle.write_bytes(b'exact-original')
   entry={'size':14,'sha256':hashlib.sha256(b'exact-original').hexdigest(),'sizes':{'role_full/person':[1081,2704]}}
   seed=SimpleNamespace(read_text=lambda **kwargs:json.dumps({'version':2,'bundles':{'role.bundle':entry}}))
   with patch.object(module.Path,'with_name',return_value=seed):
    self.assertEqual(module._known_portrait_dimensions(bundle,'role.bundle'),entry['sizes'])
    bundle.write_bytes(b'edited-original')
    self.assertIsNone(module._known_portrait_dimensions(bundle,'role.bundle'))
    bundle.write_bytes(b'EXACT-original')
    self.assertIsNone(module._known_portrait_dimensions(bundle,'role.bundle'))
    self.assertIsNone(module._known_portrait_dimensions(bundle,'other.bundle'))
   with patch.object(module.Path,'with_name',return_value=SimpleNamespace(read_text=lambda **kwargs:json.dumps({'version':1,'bundles':{'role.bundle':entry}}))):
    bundle.write_bytes(b'exact-original')
    self.assertIsNone(module._known_portrait_dimensions(bundle,'role.bundle'))

 def test_atlas_only_sprites_keep_native_units(self):
  with patch.dict(sys.modules,{'UnityPy':SimpleNamespace(), 'UnityPy.helpers':SimpleNamespace(CompressionHelper=SimpleNamespace())}):
   spec=importlib.util.spec_from_file_location('atlas_dimension_fixture',Path(__file__).resolve().parents[1]/'extract_game_assets.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  sprite=SimpleNamespace(type=SimpleNamespace(name='Sprite'),parse_as_object=lambda:SimpleNamespace(m_Rect=SimpleNamespace(width=114,height=137),m_PixelsToUnits=50))
  env=SimpleNamespace(container={'assets/res/textures/role_comic/person.png':SimpleNamespace(deref=lambda:sprite)})
  self.assertEqual(module._portrait_resource_dimensions(env),{'role_comic/person':[228,274]})
