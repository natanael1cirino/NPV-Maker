import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))

from runtime_npc import add_component


def component(name, plane):
    # Field shape copied from the generated app of the NPV "Thai" (26/09/2026).
    return {'$type': 'entGarmentSkinnedMeshComponent', 'name': {'$type': 'CName', '$storage': 'string', '$value': name},
            'renderingPlaneAnimationParam': {'$type': 'CName', '$storage': 'string', '$value': plane},
            'LODMode': 'AlwaysVisible', 'chunkMask': '9223372036854775807'}


class RenderPlaneTests(unittest.TestCase):
    """Player arms and tattoos must not keep the player's animated render plane."""

    def test_player_planes_become_the_npc_plane(self):
        selected = {}
        for name, plane in (('a0_001_pwa_base_hq__full', 'renderPlaneLeftArm'),
                            ('a0_001_pwa_base_hq__full8640', 'renderPlane'),
                            ('your_back_tattoo10', 'renderPlane')):
            add_component(selected, (name,), component(name, plane))
        planes = {key[0]: part['renderingPlaneAnimationParam']['$value'] for key, part in selected.items()}
        self.assertEqual(set(planes.values()), {'None'})

    def test_components_without_a_plane_are_unchanged(self):
        selected = {}
        part = component('t0_000_pwa_base__full', 'None')
        del part['renderingPlaneAnimationParam']
        add_component(selected, ('t0',), part)
        self.assertNotIn('renderingPlaneAnimationParam', selected[('t0',)])


if __name__ == '__main__':
    unittest.main()
