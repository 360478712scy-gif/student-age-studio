import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import base64
import unittest
import editor_music as music
import server as api
import test_plugin_mode

class MusicTests(unittest.TestCase):
 setUp=test_plugin_mode.PluginModeTests.setUp
 def test_custom_library_order_dedup_and_restart(self):
  def put(title,track='local',extra=b''):
   return music.access(self.store,api,dict(trackId=track,fileName=title,data=base64.b64encode(b'RIFF'+b'\0'*4+b'WAVEfmt '+extra).decode()))
  put('其他音乐.wav',extra=b'a');put('odoriko.wav','odoriko');put('tooi.wav','tooi-sora')
  data=music.access(self.store,api);self.assertEqual([t['id'] for t in data['tracks'][:2]],['tooi-sora','odoriko'])
  custom=data['tracks'][2];self.assertEqual(custom['name'],'其他音乐');self.assertTrue(music.media(api,custom['id']).is_file())
  put('重复导入.wav',extra=b'a');self.assertEqual(len(music.access(self.store,api)['tracks']),3)
  put('其他音乐.wav',extra=b'b');self.assertEqual(len(music.access(self.store,api)['tracks']),4)
  music.access(self.store,api,dict(mode='shuffle',volume=.2));self.assertEqual(len(music.access(self.store,api)['tracks']),4)
  self.assertEqual(self.protected.read_bytes(),self.before)
  with self.assertRaises(api.ApiError):music.media(api,'../../not-music')

if __name__=='__main__':unittest.main()
