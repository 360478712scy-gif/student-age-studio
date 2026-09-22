"""Event membership stays on the entry chain. Linked outside lines are display-only."""
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from event_ownership import display_ownership, ownership


class OwnershipTests(unittest.TestCase):
    def setUp(self):
        self.events = {'2551': {'id': 2551, 'talkId': [2551001]}}
        self.talks = {
            '2551001': {'id': 2551001, 'nextTalk': [2551002]},
            '2551002': {'id': 2551002, 'nextTalk': [8001]},
            '8001': {'id': 8001, 'nextTalk': [8002]},
            '8002': {'id': 8002, 'nextTalk': []},
            '7001': {'id': 7001, 'nextTalk': [2551001, 7002]},
            '7002': {'id': 7002, 'nextTalk': []},
            '2551801': {'id': 2551801, 'nextTalk': [2551802]},
            '2551802': {'id': 2551802, 'nextTalk': []},
            '6001': {'id': 6001, 'nextTalk': []},
            '9999': {'id': 9999, 'nextTalk': []},
        }
        self.options = {'255101': {'id': 255101, 'talkId': [6001]}, '12': {'id': 12, 'talkId': [9999]}}

    def test_outside_lines_are_shown_with_the_event_without_joining_it(self):
        shown = display_ownership(self.events, self.talks, self.options, {})
        owners = ownership(self.events, self.talks, self.options, {})
        for ident in ('2551001', '2551002', '8001', '8002', '7001', '7002', '2551801', '2551802', '6001'):
            self.assertEqual(shown[ident], [2551], ident)
        self.assertNotIn('9999', shown)
        for ident in ('2551001', '2551002', '8001', '8002'):
            self.assertEqual(owners[ident], [2551], ident)
        for ident in ('7001', '7002', '2551801', '2551802', '6001', '9999'):
            self.assertNotIn(ident, owners)

    def test_a_saved_display_owner_does_not_keep_the_line_out_of_external_dialogues(self):
        previous = {ident: [2551] for ident in ('7001', '2551801', '6001', '42')}
        self.talks['42'] = {'id': 42, 'nextTalk': []}
        owners = ownership(self.events, self.talks, self.options, {}, previous)
        self.assertNotIn('7001', owners)
        self.assertNotIn('2551801', owners)
        self.assertNotIn('6001', owners)
        self.assertEqual(owners['42'], [2551])

    def test_id_block_does_not_absorb_another_events_entry(self):
        events = {'10': {'id': 10, 'talkId': [10001]}, '20': {'id': 20, 'talkId': [20001]}}
        talks = {'10001': {'id': 10001, 'nextTalk': [20001]}, '20001': {'id': 20001, 'nextTalk': []}}
        owners = ownership(events, talks, {}, {})
        self.assertEqual(owners['10001'], [10])
        self.assertCountEqual(owners['20001'], [10, 20])


if __name__ == '__main__':
    unittest.main()
