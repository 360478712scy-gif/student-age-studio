"""Sprite unit conversion and cache migration, without decoding game textures."""
import importlib.util,json,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

class PictureDimensionTests(unittest.TestCase):
 def test_all_character_picture_sizes_use_sprite_units_and_invalidate_old_cache(self):
  kinds=('role_full','role_half','role_head','role_comic','role_comic_head','role_photo')
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);bundle=root/'textures_assets_role.bundle';bundle.write_bytes(b'unchanged game bundle');cache=root/'cache';cache.mkdir()
   old=cache/'portrait-dimensions-v3.json';old.write_text('{"old":"texture pixels"}');before=old.read_bytes()
   objects=[];mapping={}
   for kind in kinds:
    mapping[kind+'/person']='assets/'+kind+'.png'
    texture=SimpleNamespace(type=SimpleNamespace(name='Texture2D'),parse_as_object=lambda:SimpleNamespace(m_Width=500,m_Height=2000))
    sprite=SimpleNamespace(type=SimpleNamespace(name='Sprite'),parse_as_object=lambda:SimpleNamespace(m_Rect=SimpleNamespace(width=500,height=2000),m_PixelsToUnits=80))
    for obj in (sprite,texture):objects.append(('assets/res/textures/'+kind+'/person.png',SimpleNamespace(deref=lambda obj=obj:obj)))
   env=SimpleNamespace(container=SimpleNamespace(items=lambda:objects))
   with patch.dict(sys.modules,{'UnityPy':SimpleNamespace(), 'UnityPy.helpers':SimpleNamespace(CompressionHelper=SimpleNamespace())}):
    spec=importlib.util.spec_from_file_location('picture_dimension_fixture',Path(__file__).resolve().parents[1]/'extract_game_assets.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
   with patch.object(module,'game_cache',return_value=cache),patch.object(module.UnityPy,'load',return_value=env,create=True) as load:
    unrelated=root/'textures_assets_role_unrelated.bundle';unrelated.write_bytes(b'other portraits')
    catalog={'assetMap':{**mapping,**{'Textures/'+k:v for k,v in mapping.items()}},'bundles':{bundle.name:'fixture',unrelated.name:'fixture'},'bundleOutputs':{bundle.name:list(mapping.values()),unrelated.name:['assets/unrelated.png']}}
    for _ in range(2):self.assertEqual(module.portrait_dimensions(root,catalog,list(mapping)),{k:[625,2500] for k in mapping})
    load.assert_called_once()
    self.assertEqual(module.portrait_dimensions(root,catalog,['Mods/a.png']),{})
   self.assertEqual(old.read_bytes(),before)
