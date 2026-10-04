import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server

class DialogueShortcutSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'display-settings.json'
    def app(self):
        app = object.__new__(server.StudioServer)
        app.display_lock = threading.RLock(); app.display_path = self.path
        return app
    def test_defaults_persistence_disable_and_unrelated_preferences(self):
        self.assertEqual(self.app().display_settings()['dialogueShortcuts'], {'previous':'Alt+ArrowUp','next':'Alt+ArrowDown'})
        self.assertFalse(self.path.exists())
        self.path.write_text(json.dumps({'future':{'keep':[7]},'theme':'glass-noir'}))
        keys = {'previous':'Mod+Shift+ArrowUp','next':''}
        self.app().display_settings({'dialogueShortcuts':keys})
        self.app().display_settings({'showRecordIds':False})
        value = self.app().display_settings()
        self.assertEqual(value['dialogueShortcuts'],keys)
        self.assertEqual(value['theme'],'glass-noir')
        self.assertEqual(json.loads(self.path.read_text())['future'],{'keep':[7]})
    def test_conflicts_invalid_payloads_never_write(self):
        self.app().display_settings({'autoSave':True}); before=self.path.read_bytes()
        for keys in [None,[],{}, {'previous':'Alt+ArrowUp'}, {'previous':'Alt+ArrowUp','next':'Alt+ArrowUp'}, {'previous':None,'next':''}] + [{'previous':k,'next':''} for k in ['ArrowUp','Ctrl+KeyK','Mod+KeyS','Mod+Shift+KeyF','Alt+ArrowLeft','Alt+ArrowRight','Alt+F4','Shift+F5','Alt+F11','Mod+Mod+KeyE','Alt+Space','Alt+Shift+KeyE<script>']]:
            with self.subTest(keys=keys), self.assertRaises(server.ApiError):
                self.app().display_settings({'dialogueShortcuts':keys})
            self.assertEqual(self.path.read_bytes(), before)
    def test_failed_write_preserves_previous_keys(self):
        keys={'previous':'Alt+KeyU','next':'Alt+KeyD'}
        self.app().display_settings({'dialogueShortcuts':keys})
        with patch.object(server, 'replace_file', side_effect=PermissionError('locked')):
            with self.assertRaises(PermissionError):
                self.app().display_settings({'dialogueShortcuts':{'previous':'','next':''}})
        self.assertEqual(self.app().display_settings()['dialogueShortcuts'],keys)

if __name__=='__main__': unittest.main()
