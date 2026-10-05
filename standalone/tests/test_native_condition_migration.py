"""Former Studio comparisons keep their truth set when converted to native."""
import copy
import math
from pathlib import Path
import random
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import native_condition_migration as m


def previous(value):
    if value == 0:
        return -struct.unpack('!f', struct.pack('!I', 1))[0]
    bits = struct.unpack('!I', struct.pack('!f', value))[0]
    return struct.unpack('!f', struct.pack('!I', bits + (-1 if value > 0 else 1)))[0]


def extended(command, actual):
    target = m.float32(command[3])
    if not math.isfinite(actual) or not math.isfinite(target):
        return False
    return {9001: lambda: actual >= target, 9002: lambda: actual < target,
            9003: lambda: actual > target, 9004: lambda: actual <= target,
            9005: lambda: actual == target, 9006: lambda: actual != target}[command[1]]()


def native(commands, actual):
    for family, subtype, ident, target in commands:
        target = m.float32(target)
        if subtype == 1:
            result = actual >= target if family == 7 else m.native_attribute_ge(actual, target)
        else:
            result = actual < target
        if not result:
            return False
    return True


class NativeConditionConversionTests(unittest.TestCase):
    def assertEquivalent(self, command):
        commands, reason = m.convert_command(command)
        self.assertIsNone(reason, command)
        target = m.float32(command[3])
        around = {0.0, -0.0, m._MAX, -m._MAX}
        if math.isfinite(target):
            around.add(target)
            below, above = target, target
            for _ in range(64):
                below = previous(below)
                above = m.successor(above) if above != m._MAX else above
                if math.isfinite(below): around.add(below)
                if above is not None: around.add(above)
        rng = random.Random(2047)
        for _ in range(1000):
            value = struct.unpack('!f', struct.pack('!I', rng.getrandbits(32)))[0]
            if math.isfinite(value): around.add(value)
        for actual in around:
            self.assertEqual(extended(command, actual), native(commands, actual),
                             (command, commands, actual))
        return commands

    def test_favor_common_decimal_and_negative_boundaries(self):
        for target in (-999, -1.25, -0.001, 0, 0.1, 30, 30.0000001, 100.75):
            for subtype in range(9001, 9006):
                with self.subTest(target=target, subtype=subtype):
                    commands = self.assertEquivalent([7, subtype, 221201, target])
                    self.assertTrue(all(row[1] in (1, -1) for row in commands))

    def test_attribute_cutoffs_respect_native_float_tolerance(self):
        for target in (-999, -1.25, -0.001, 0.1, 30, 100.75, 200000):
            for subtype in range(9001, 9006):
                with self.subTest(target=target, subtype=subtype):
                    self.assertEquivalent([4, subtype, 101, target])
        # A same-threshold >= would accept values slightly below 30.
        converted, reason = m.convert_command([4, 9001, 101, 30])
        self.assertIsNone(reason)
        self.assertGreater(converted[0][3], 30)
        self.assertFalse(native(converted, previous(30)))

    def test_unrepresentable_zero_cutoff_and_not_equal_are_retained(self):
        for command in ([4, 9001, 101, 0], [4, 9003, 101, 0],
                        [4, 9005, 101, 0], [4, 9001, 101, 1], [4, 9005, 101, 1],
                        [7, 9006, 3, 30], [4, 9006, 101, 30]):
            converted, reason = m.convert_command(command)
            self.assertIsNotNone(reason)
            self.assertIs(converted[0], command)
        for subtype in (9002, 9004):
            self.assertEquivalent([4, subtype, 101, 0])

    def test_finite_extremes_and_float_cast_overflow(self):
        for family in (4, 7):
            for target in (-m._MAX, m._MAX, 1e39, -1e39):
                for subtype in range(9001, 9007):
                    with self.subTest(family=family, target=target, subtype=subtype):
                        self.assertEquivalent([family, subtype, 101, target])

    def test_owned_shape_checks_preserve_foreign_and_malformed_commands(self):
        commands = [[1163, 9001, 3, 30], [4, 1, 101, 30], [7, -1, 3, 30],
                    [9113, 1, 9001, 30], [4, 9007, 101, 30], [4, 9001, 101],
                    [7, 9001, 3.5, 30], [4, 9001, 101, True], [7, 9001, 3, math.nan],
                    [7, 9001, 3, 10 ** 400]]
        for command in commands:
            rows, reason = m.convert_command(command)
            self.assertIs(rows[0], command)
            self.assertEqual(bool(reason), m.is_owned(command))

    def test_mixed_list_is_not_mutated_and_keeps_plugin_instructions(self):
        commands = [[7, 9005, 3, 30], [1163, 2, 9, 0.5], [4, 2, 101, 40],
                    [7, 9006, 3, 30], [4, 9001, 101, 60]]
        before = copy.deepcopy(commands)
        converted, count, issues = m.migrate_conditions(commands)
        self.assertEqual(commands, before)
        self.assertEqual(count, 2)
        self.assertEqual(len(converted), len(commands) + 1)
        self.assertIs(converted[2], commands[1])
        self.assertIs(converted[3], commands[2])
        self.assertIs(converted[4], commands[3])
        self.assertEqual(issues[0]['index'], 3)
        unchanged = [[1163, 2, 9, 0.5], [7, 9006, 3, 30]]
        self.assertIs(m.migrate_conditions(unchanged)[0], unchanged)

    def test_single_condition_field_keeps_its_native_dimension(self):
        converted, count, issues = m.migrate_conditions([7, 9005, 3, 30])
        self.assertEqual(count, 0)
        self.assertEqual(issues[0]['reason'], 'native_single_condition_cannot_express_conjunction')
        self.assertEqual(converted, [7, 9005, 3, 30])

    def test_submitted_event_row_syncs_only_explicit_social_mirrors(self):
        row = {'id': 7, 'condition': [[7,9001,3,30]],
               'studioSocial': {'conditions': [[7,9001,3,30]], 'entryConditions': [[7,9002,3,40]],
                                'effects': [[7,9001,3,30]], 'future': {'conditions': [[7,9001,3,60]]}},
               'future': {'condition': [[7,9001,3,30]]}}
        before = copy.deepcopy(row)
        ordinary, count, issues = m.migrate_row(row)
        self.assertEqual(count, 1); self.assertFalse(issues)
        self.assertIs(ordinary['studioSocial'], row['studioSocial'])
        revised, count, issues = m.migrate_row(row, include_social=True)
        self.assertEqual(count, 3); self.assertFalse(issues)
        self.assertEqual(revised['condition'], revised['studioSocial']['conditions'])
        self.assertEqual(revised['studioSocial']['entryConditions'], [[7,-1,3,40]])
        self.assertIs(revised['studioSocial']['effects'], row['studioSocial']['effects'])
        self.assertIs(revised['studioSocial']['future'], row['studioSocial']['future'])
        self.assertIs(revised['future'], row['future']); self.assertEqual(row, before)
        unresolved = {'studioSocial': {'conditions': [[7,9006,3,30]]}}
        self.assertIs(m.migrate_row(unresolved)[0], unresolved)
        kept, count, issues = m.migrate_row(unresolved, include_social=True)
        self.assertIs(kept, unresolved); self.assertEqual(count, 0)
        self.assertEqual(issues[0]['field'], 'studioSocial.conditions')


if __name__ == '__main__':
    unittest.main()
