import json,os,sys,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ui_resources


class UIResourcesTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name).resolve()
        self.bundle=self.root/'bundle';self.game=self.root/'game'
        self.env=patch.dict(os.environ,{'STUDIO_CACHE_ROOT':str(self.root/'Cache'),'STUDIO_USER_DATA_ROOT':str(self.root/'User')});self.env.start();self.addCleanup(self.env.stop)
        self.patch=patch.object(ui_resources,'ROOT',self.bundle);self.patch.start();self.addCleanup(self.patch.stop)
        ui_resources.resource_manifest.cache_clear();self.addCleanup(ui_resources.resource_manifest.cache_clear)
    def write(self,folder):
        folder.mkdir(parents=True,exist_ok=True);(folder/'image.png').write_bytes(b'fixture')
        (folder/'manifest.json').write_text(json.dumps({'files':['image.png']}),encoding='utf8')
    def test_existing_bundled_assets_are_preserved(self):
        self.write(self.bundle/'phone')
        with patch.object(ui_resources,'_prepare') as prepare:
            self.assertEqual(ui_resources.resource_path('phone','image.png'),self.bundle/'phone/image.png');prepare.assert_not_called()
    def test_source_assets_are_cached_outside_game(self):
        with patch.object(ui_resources,'_prepare',side_effect=lambda kind,game,folder:self.write(folder)) as prepare:
            path=ui_resources.resource_path('phone','image.png',self.game)
            self.assertTrue(path.is_relative_to(self.root/'Cache'));self.assertFalse(self.game.exists())
            ui_resources.resource_manifest('phone',self.game);self.assertEqual(prepare.call_count,1)
    def test_cache_is_reused_after_process_cache_clear(self):
        with patch.object(ui_resources,'_prepare',side_effect=lambda kind,game,folder:self.write(folder)) as prepare:
            ui_resources.resource_manifest('goal',self.game);ui_resources.resource_manifest.cache_clear()
            ui_resources.resource_manifest('goal',self.game);self.assertEqual(prepare.call_count,1)
    def test_unknown_or_traversing_resources_are_rejected(self):
        self.write(self.bundle/'phone')
        with self.assertRaises(FileNotFoundError):ui_resources.resource_path('phone','../image.png')
        with self.assertRaises(FileNotFoundError):ui_resources.resource_manifest('../phone')
    def test_unconfigured_game_does_not_extract(self):
        with patch.object(ui_resources,'_prepare') as prepare:
            with self.assertRaises(FileNotFoundError):ui_resources.resource_manifest('goal')
            prepare.assert_not_called()


if __name__=='__main__':unittest.main()
