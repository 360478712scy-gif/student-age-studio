"""Wearing places are game map locations; the file format keeps older in-game plugins from switching dialogue outfits."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import character_workbench as cw

MAPS = {'1': {'id': 1, 'name': '家', 'type': 0, 'bg': 201011, 'bg2': 0},
        '2': {'id': 2, 'name': '学校教学楼', 'type': 0, 'bg': 202051, 'bg2': 202011},
        '7002': {'id': 7002, 'name': '2楼服装区', 'type': 2, 'bg': 205083, 'bg2': 0}}


class OutfitPlacesTests(unittest.TestCase):
    def test_version_one_backgrounds_become_places(self):
        old = {'1000001': {'0': {'name': '默认服装', 'backgrounds': [201011]}, '1': {'name': '校服', 'backgrounds': [202011, 999999]}}}
        outfits = cw.migrate_outfits(cw.unwrap_outfits(old), MAPS)
        self.assertEqual(outfits['1000001']['0'], {'name': '默认服装', 'places': [1]})
        self.assertEqual(outfits['1000001']['1'], {'name': '校服', 'places': [2]})  # an unrelated dialogue background is dropped

    def test_file_nests_characters_so_old_plugins_find_none(self):
        wrapped = cw.wrap_outfits({'1000001': {'1': {'name': '校服', 'places': [2]}}})
        self.assertEqual(wrapped['version'], 2)
        # Older in-game workbench builds read top-level person ids; none remain.
        self.assertFalse([k for k in wrapped if k.isdigit()])
        self.assertEqual(cw.unwrap_outfits(wrapped), {'1000001': {'1': {'name': '校服', 'places': [2]}}})
        self.assertEqual(cw.wrap_outfits({}), {})


if __name__ == '__main__':
    unittest.main()
