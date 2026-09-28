"""夜幕 · 剧场 replaced 纸本 · 工作室: an old saved choice opens the new theme, and its files are served."""
import json
import re
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server

ROOT = Path(__file__).resolve().parents[1]


class NoirThemeTests(unittest.TestCase):
    def app(self, file):
        app = object.__new__(server.StudioServer)
        app.display_lock = threading.RLock()
        app.display_path = file
        return app

    def test_saved_atelier_opens_noir_and_noir_can_be_chosen(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / 'display.json'
            file.write_text(json.dumps({'theme': 'glass-atelier'}))
            self.assertEqual(self.app(file).display_settings()['theme'], 'glass-noir')
            self.assertEqual(self.app(file).display_settings({'theme': 'glass-noir'})['theme'], 'glass-noir')
            with self.assertRaises(server.ApiError):
                self.app(file).display_settings({'theme': 'glass-atelier'})

    def test_noir_stylesheets_exist_are_scoped_and_linked(self):
        index = (ROOT / 'index.html').read_text(encoding='utf-8')
        for name in ('noir-tones.css', 'noir.css'):
            self.assertIn(f'href="/{name}"', index)
            css = (ROOT / name).read_text(encoding='utf-8')
            css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
            css = re.sub(r'@keyframes[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}', '', css)   # animation steps are not selectors
            rules = [sel.strip() for sel in re.findall(r'(?:^|[{};])\s*([^{};@\s][^{};]*)\{', css) if sel.strip()]
            unscoped = [sel for sel in rules if 'html[data-theme="glass-noir"]' not in sel]
            self.assertEqual(unscoped, [], f'{name} must only style the noir theme')
        self.assertNotIn('atelier', index)


if __name__ == '__main__':
    unittest.main()
