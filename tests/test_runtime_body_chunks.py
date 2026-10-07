import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from runtime_npc import add_component

BODY = 'base\\characters\\common\\player_base_bodies\\player_female_average\\t0_000_pwa_base__full.morphtarget'
# Values read from the installed t0_000_base__full.app (body_color) and
# l0_000_base__full.app (lifted_feet) for 01_ca_pale_00_warm_ivory.
TORSO_TO_THIGH = '18446744073709551391'
CALF_TO_FOOT = '18446744073709551584'


def body(mask):
    return {'$type': 'entMorphTargetSkinnedMeshComponent',
            'name': {'$type': 'CName', '$storage': 'string', '$value': 't0_000_pwa_base__full'},
            'id': '2010036977180426240', 'chunkMask': mask,
            'morphResource': {'DepotPath': {'$value': BODY}}}


def key(part):
    return (part['name']['$value'], part['$type'], part['id'], BODY, '')


class RuntimeBodyChunkTests(unittest.TestCase):
    def test_body_and_lifted_feet_keep_every_body_chunk_visible(self):
        selected = {}
        for part in (body(TORSO_TO_THIGH), body(CALF_TO_FOOT)):
            add_component(selected, key(part), part)
        self.assertEqual(len(selected), 1)
        mask = next(iter(selected.values()))['chunkMask']
        self.assertIsInstance(mask, str)
        for chunk in range(8):
            self.assertTrue(int(mask) >> chunk & 1, 'body chunk %d hidden' % chunk)

    def test_order_of_captured_options_does_not_matter(self):
        selected = {}
        for part in (body(CALF_TO_FOOT), body(TORSO_TO_THIGH)):
            add_component(selected, key(part), part)
        self.assertEqual(int(next(iter(selected.values()))['chunkMask']) & 0xff, 0xff)

    def test_single_option_keeps_its_own_mask(self):
        selected = {}
        part = body(TORSO_TO_THIGH)
        add_component(selected, key(part), part)
        self.assertEqual(selected[key(part)]['chunkMask'], TORSO_TO_THIGH)

    def test_distinct_components_are_not_merged(self):
        selected = {}
        first, second = body(TORSO_TO_THIGH), body(CALF_TO_FOOT)
        second['id'] = '1'
        add_component(selected, key(first), first)
        add_component(selected, key(second), second)
        self.assertEqual(len(selected), 2)
        self.assertEqual(selected[key(first)]['chunkMask'], TORSO_TO_THIGH)
        self.assertEqual(selected[key(second)]['chunkMask'], CALF_TO_FOOT)


if __name__ == '__main__':
    unittest.main()
