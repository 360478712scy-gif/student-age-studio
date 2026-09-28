"""夜幕 · 剧场 sits next to 纸本 · 工作室: both can be chosen, and the theatre's files only act in its own theme."""
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

    def test_paper_and_theatre_are_both_kept(self):
        # 纸本 · 工作室 stays next to 夜幕 · 剧场: a saved choice of either is kept, and either can be chosen.
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / 'display.json'
            for theme in ('glass-atelier', 'glass-noir'):
                file.write_text(json.dumps({'theme': theme}))
                self.assertEqual(self.app(file).display_settings()['theme'], theme)
                self.assertEqual(self.app(file).display_settings({'theme': theme})['theme'], theme)
        script = (ROOT / 'theme.js').read_text(encoding='utf-8')
        self.assertIn("'glass-atelier','glass-noir'", script)
        self.assertIn('value="glass-atelier"', (ROOT / 'locations.js').read_text(encoding='utf-8'))

    def test_noir_stylesheets_exist_are_scoped_and_linked(self):
        index = (ROOT / 'index.html').read_text(encoding='utf-8')
        for name in ('atelier-tones.css', 'atelier.css'):
            self.assertIn(f'href="/{name}"', index)
        for name in ('noir-tones.css', 'noir.css'):
            self.assertIn(f'href="/{name}"', index)
            css = (ROOT / name).read_text(encoding='utf-8')
            css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
            css = re.sub(r'@keyframes[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}', '', css)   # animation steps are not selectors
            rules = [sel.strip() for sel in re.findall(r'(?:^|[{};])\s*([^{};@\s][^{};]*)\{', css) if sel.strip()]
            unscoped = [part for sel in rules for part in self.selectors(sel) if not part.startswith('html[data-theme="glass-noir"]')]
            self.assertEqual(unscoped, [], f'{name} must only style the noir theme')

    @staticmethod
    def selectors(rule):
        parts, depth, start = [], 0, 0
        for at, char in enumerate(rule):
            depth += char in '([' and 1 or char in ')]' and -1 or 0
            if char == ',' and depth == 0:
                parts.append(rule[start:at].strip()); start = at + 1
        return parts + [rule[start:].strip()]

    def test_noir_keeps_the_editor_in_charge_of_the_tool_dock(self):
        # The dock sits in the top layer above every window: the theme must not force it open, and hides it
        # while the editor boots, during onboarding and while a window is open.
        css = (ROOT / 'noir.css').read_text(encoding='utf-8')
        self.assertNotRegex(css, r'#studio-corner-items\{[^}]*visibility:visible')
        self.assertNotRegex(css, r'#studio-corner-toggle\{[^}]*display:none')
        for state in ('[data-booting] body #studio-corner-tools', '#studio-onboarding:not([hidden])', 'dialog[data-studio-layered][open]:not(.uc-popup)) #studio-corner-tools'):
            self.assertIn(state, css)

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
