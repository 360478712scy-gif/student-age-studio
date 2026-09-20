"""Large multi-event TXT exports retain Unicode and do not touch source files."""
import codecs,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server import StudioStore,ApiError

class StoryExportTests(unittest.TestCase):
 def test_large_utf8_export_and_safe_filename(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);source=root/'source.json';source.write_text('{"draft":"keep"}',encoding='utf-8')
   store=SimpleNamespace(project=lambda ident:None,export_root=root/'Exports')
   content='小雅 剧情正文\n'*(17*1024*1024//len('小雅 剧情正文\n'.encode('utf-8'))+1)
   result=StudioStore.export_text(store,{'projectId':'fixture','format':'txt','filename':'../全部剧情.txt','content':content})
   target=Path(result['path']);self.assertEqual(target.parent,store.export_root)
   self.assertTrue(target.read_bytes().startswith(codecs.BOM_UTF8));self.assertEqual(target.read_text(encoding='utf-8-sig'),content)
   self.assertEqual(source.read_text(encoding='utf-8'),'{"draft":"keep"}')
 def test_oversized_export_does_not_create_partial_file(self):
  with tempfile.TemporaryDirectory() as tmp:
   store=SimpleNamespace(project=lambda ident:None,export_root=Path(tmp)/'Exports')
   with self.assertRaises(ApiError):StudioStore.export_text(store,{'projectId':'fixture','content':'x'*(64*1024*1024+1)})
   self.assertFalse(store.export_root.exists())
