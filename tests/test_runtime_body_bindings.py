import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))

import runtime_body


def binding(field_type, name):
    return {"HandleId": "1", "Data": {"$type": field_type, "bindName": {"$type": "CName", "$value": name}}}


def mesh(name, bound_to):
    return {"$type": "entSkinnedMeshComponent", "name": {"$value": name},
            "mesh": {"DepotPath": {"$value": "base\\x\\" + name + ".mesh"}},
            "skinning": binding("entSkinningBinding", bound_to),
            "parentTransform": binding("entHardTransformBinding", bound_to)}


def animated(name, controlled_by):
    return {"$type": "entAnimatedComponent", "name": {"$value": name},
            "rig": {"DepotPath": {"$value": "base\\x\\" + name + ".rig"}},
            "controlBinding": binding("entAnimationControlBinding", controlled_by),
            "parentTransform": binding("entHardTransformBinding", "root")}


class BoundSupportsTest(unittest.TestCase):
    """Shape of the AFT body under SELECTED_TPP, 02/10/2026: penis mesh bound to penis_dangles."""

    def test_runtime_body_keeps_the_rig_its_mesh_binds_to(self):
        penis = mesh("penis", "penis_dangles")
        dangles = animated("penis_dangles", "root")
        unrelated = animated("other_dangles", "root")
        body = mesh("body", "root")
        carried = runtime_body.bound_supports([penis, body], [penis, dangles, unrelated, body])
        self.assertEqual([p["name"]["$value"] for p in carried], ["penis_dangles"])

    def test_follows_chains_and_skips_geometry_and_present_parts(self):
        piece = mesh("piece", "outer")
        outer = animated("outer", "inner")
        inner = animated("inner", "root")
        other_mesh = mesh("outer_mesh_named_like_nothing", "root")
        carried = runtime_body.bound_supports([piece], [piece, outer, inner, other_mesh])
        self.assertEqual(sorted(p["name"]["$value"] for p in carried), ["inner", "outer"])
        self.assertEqual(runtime_body.bound_supports([piece, outer], [outer]), [])


if __name__ == '__main__':
    unittest.main()
