"""Wearing places are game map locations, not dialogue backgrounds."""
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
        outfits = cw.migrate_outfits(old, MAPS)
        self.assertEqual(outfits['1000001']['0'], {'name': '默认服装', 'places': [1]})
        self.assertEqual(outfits['1000001']['1'], {'name': '校服', 'places': [2]})  # an unrelated dialogue background is dropped


if __name__ == '__main__':
    unittest.main()
