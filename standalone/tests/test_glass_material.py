import json,sys,tempfile,threading,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server
class MaterialTests(unittest.TestCase):
 def test_material_persists_independently_and_invalid_write_preserves_file(self):
  with tempfile.TemporaryDirectory() as d:
   file=Path(d)/'preferences.json';file.write_text(json.dumps({'theme':'glass-dusk','future':{'keep':3},'autoSave':False}))
   def app():
    a=object.__new__(server.StudioServer);a.display_lock=threading.RLock();a.display_path=file;return a
   self.assertEqual(app().display_settings()['glassMaterial'],'liquid')
   result=app().display_settings({'glassMaterial':'frosted'});self.assertEqual(result['theme'],'glass-dusk')
   app().display_settings({'theme':'glass-moon'});self.assertEqual(app().display_settings()['glassMaterial'],'frosted')
   self.assertEqual(json.loads(file.read_text())['future'],{'keep':3});before=file.read_bytes()
   for value in ['unknown',None,{},[],1]:
    with self.assertRaises(server.ApiError):app().display_settings({'glassMaterial':value})
   self.assertEqual(file.read_bytes(),before)
if __name__=='__main__':unittest.main()
