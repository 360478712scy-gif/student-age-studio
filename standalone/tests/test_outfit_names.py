"""Outfits keep only names: the game chooses the outfit worn on the map by its own rule for every character."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import character_workbench as cw


class OutfitTests(unittest.TestCase):
    def test_places_and_backgrounds_are_dropped(self):
        old = {'1000001': {'0': {'name': '默认服装', 'backgrounds': [201011]}, '1': {'name': '校服', 'places': [2]}}, 'junk': 1}
        self.assertEqual(cw.migrate_outfits(old), {'1000001': {'0': {'name': '默认服装'}, '1': {'name': '校服'}}})
        self.assertEqual(old['1000001']['1']['places'], [2], 'the input is not modified')


if __name__ == '__main__':
    unittest.main()
