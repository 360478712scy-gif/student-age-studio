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
            unscoped = [part for sel in rules for part in self.selectors(sel) if not part.startswith('html[data-theme="glass-noir"]')]
            self.assertEqual(unscoped, [], f'{name} must only style the noir theme')
        self.assertNotIn('atelier', index)

    @staticmethod
    def selectors(rule):
        parts, depth, start = [], 0, 0
        for at, char in enumerate(rule):
            depth += char in '([' and 1 or char in ')]' and -1 or 0
            if char == ',' and depth == 0:
                parts.append(rule[start:at].strip()); start = at + 1
        return parts + [rule[start:].strip()]

    def test_noir_script_is_served_and_only_acts_in_its_theme(self):
        index = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertIn('<script src="/noir.js" defer></script>', index)
        self.assertIn('"/noir.js"', (ROOT / 'server.py').read_text(encoding='utf-8'))
        script = (ROOT / 'noir.js').read_text(encoding='utf-8')
        self.assertIn("const THEME='glass-noir'", script)
        self.assertIn("addEventListener('studio-theme-change',sync)", script)
        self.assertIn('function teardown()', script)


if __name__ == '__main__':
    unittest.main()
