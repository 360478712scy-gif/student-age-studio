import importlib.util
import tempfile
import unittest
from pathlib import Path

SOURCE=Path(__file__).resolve().parents[1]/'search_text.py'

class SearchStartupTests(unittest.TestCase):
    def test_missing_or_corrupt_dictionary_keeps_literal_search(self):
        for content in (None, 'truncated', '/* PINYIN_START */{"荀":[]}/* PINYIN_END */', '/* PINYIN_START */[]/* PINYIN_END */'):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as directory:
                root=Path(directory)
                (root/'search_text.py').write_bytes(SOURCE.read_bytes())
                if content is not None: (root/'search-pinyin.js').write_text(content,encoding='utf-8')
                spec=importlib.util.spec_from_file_location('isolated_search',root/'search_text.py')
                module=importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                self.assertEqual(module.dictionary,{})
                self.assertTrue(module.matches('荀彧','荀彧的事件'))
                self.assertTrue(module.matches('hello','HELLO world'))
                self.assertFalse(module.matches('不存在','荀彧'))

    def test_valid_dictionary_keeps_pinyin_search(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'search_text.py').write_bytes(SOURCE.read_bytes())
            (root/'search-pinyin.js').write_text('/* PINYIN_START */{"荀":["xun"],"彧":["yu"]}/* PINYIN_END */',encoding='utf-8')
            spec=importlib.util.spec_from_file_location('isolated_search',root/'search_text.py')
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            self.assertTrue(module.matches('xunyu','荀彧'))
            self.assertTrue(module.matches('xy','荀彧'))

if __name__=='__main__': unittest.main()
