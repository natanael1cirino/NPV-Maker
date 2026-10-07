import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from finalize_npc_candidate import partition_assets, replace_resource_hashes


class CandidateAssetTests(unittest.TestCase):
    def test_selected_overlay_uses_vanilla_path_when_no_morph_shape_applies(self):
        overlay = r"head\i1_000_pwa_c__basehead_earring_01.mesh"
        other = r"head\he_000_pwa_c__basehead.mesh"
        report = {"resource_root": r"npvmaker\npv\example",
                  "required_custom_assets": [overlay, other],
                  "forced_custom_assets": [overlay]}
        morph = {"meshes": [{"mesh": overlay, "applied_shapes": []},
                            {"mesh": other, "applied_shapes": []}]}
        assets = {"vanilla_references": {overlay: r"base\earring.mesh",
                                         other: r"base\eyes.mesh"}}
        fallbacks, custom = partition_assets(report, morph, assets)
        self.assertEqual(custom, [])
        self.assertEqual(fallbacks[report["resource_root"] + "\\" + overlay],
                         r"base\earring.mesh")
        app = {"mesh": {"$type": "ResourcePath", "$storage": "string",
                        "$value": report["resource_root"] + "\\" + overlay}}
        self.assertEqual(replace_resource_hashes(app, fallbacks), 1)
        self.assertEqual(app["mesh"]["$value"], r"base\earring.mesh")


if __name__ == "__main__":
    unittest.main()
