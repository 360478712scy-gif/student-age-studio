"""The native table validators accept real 500k maps without skipping row checks."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server as b


class LargeRowMapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = {str(ident): {'id': ident} for ident in range(1, 500001)}
        for key in ('1', '250000', '500000'):
            cls.rows[key]['futureField'] = {'keep': [1, '未知字段', 3]}

    @classmethod
    def tearDownClass(cls):
        cls.rows = None

    def test_validate_all_500000_rows_and_keep_unknown_fields(self):
        self.assertIs(b.validate_map(self.rows, 'TalkCfg'), self.rows)
        self.assertEqual(len(self.rows), 500000)
        for key in ('1', '250000', '500000'):
            self.assertEqual(self.rows[key]['futureField'], {'keep': [1, '未知字段', 3]})

    def test_repair_checks_the_last_row_of_a_500000_row_table(self):
        rows = {**self.rows, '500000': {**self.rows['500000'], 'id': False}}
        notes = []
        repaired = b.repair_map(rows, 'TalkCfg', warnings=notes)
        self.assertEqual(len(repaired), 500000)
        self.assertEqual(repaired['500000']['id'], 500000)
        self.assertEqual(repaired['500000']['futureField'], {'keep': [1, '未知字段', 3]})
        self.assertTrue(any('500000' in note for note in notes))
        self.assertIs(rows['500000']['id'], False)

    def test_actual_structure_and_ids_are_still_checked(self):
        for rows in ([], {'1': []}, {'1': {'id': True}}, {'1': {'id': 2}},
                     {'2147483648': {'id': 2147483648}}):
            with self.subTest(rows=rows), self.assertRaises(b.ApiError):
                b.validate_map(rows, 'TalkCfg')
        with self.assertRaises(b.ApiError):
            b.repair_map([], 'TalkCfg')


if __name__ == '__main__':
    unittest.main()
