import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))

import runtime_npc


def part(kind, distance, **extra):
    return dict({'$type': kind, 'autoHideDistance': distance}, **extra)


class HideDistanceTests(unittest.TestCase):
    """Values of the generated app of THAILEND (26/09/2026)."""

    def selected(self):
        return {
            ('arm_l',): part('entGarmentSkinnedMeshComponent', 0, mesh={}),
            ('arm_r',): part('entGarmentSkinnedMeshComponent', 0, mesh={}),
            ('body',): part('entSkinnedMeshComponent', 200, mesh={}),
            ('hair',): part('entSkinnedMeshComponent', 50, mesh={}),
            ('back_tattoo',): part('entMorphTargetSkinnedMeshComponent', 0, morphResource={}),
            ('face_rig',): part('entAnimatedComponent', 0),
        }

    def test_parts_without_distance_get_the_farthest_one(self):
        selected = self.selected()
        runtime_npc.npc_hide_distance(selected)
        distances = {key[0]: value['autoHideDistance'] for key, value in selected.items()}
        self.assertEqual(distances, {'arm_l': 200, 'arm_r': 200, 'body': 200, 'hair': 50,
                                     'back_tattoo': 200, 'face_rig': 0})


if __name__ == '__main__':
    unittest.main()
