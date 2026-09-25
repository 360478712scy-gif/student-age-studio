"""Browse folders give cached assets readable names without touching anything outside the editor's folder."""
import os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import asset_browser


class AssetBrowserTests(unittest.TestCase):
    def test_build_names_deduplicates_and_rebuilds_only_its_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);cache=root/'cache';source=root/'src';source.mkdir()
            a=source/'0a1b.png';a.write_bytes(b'a');b=source/'ffee.PNG';b.write_bytes(b'b')
            keep=root/'cache'/'unrelated.txt';keep.parent.mkdir();keep.write_text('keep')
            with patch.object(asset_browser,'cache_root',return_value=cache):
                target,written,skipped=asset_browser.build('物品/图片',[('卡欧西:手表',a),('卡欧西:手表',b),('缺失',source/'none.png'),('',None)])
                self.assertEqual((written,skipped),(2,2))
                names=sorted(p.name for p in target.iterdir())
                self.assertEqual(names,['卡欧西_手表 (2).png','卡欧西_手表.png',asset_browser.README])
                self.assertEqual((target/'卡欧西_手表.png').read_bytes(),b'a')
                self.assertEqual(target.parent,cache/asset_browser.ROOT_NAME)
                # Rebuilding replaces the folder's previous contents and nothing else.
                target2,written2,_=asset_browser.build('物品/图片',[('只剩一个',a)])
                self.assertEqual(target2,target);self.assertEqual(written2,1)
                self.assertEqual(sorted(p.name for p in target.iterdir()),['只剩一个.png',asset_browser.README])
                self.assertEqual(keep.read_text(),'keep')
                self.assertTrue(a.is_file() and b.is_file())


if __name__=='__main__':
    unittest.main()
