import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from eye_lashes import change_material


class EyelashMaterialTests(unittest.TestCase):
    def setUp(self):
        self.mesh = {"Data": {"RootChunk": {
            "materialEntries": [{"name": {"$value": "eyelashes__brown_liquorice"}}],
            "appearances": [
                {"Data": {"name": {"$value": "blue_eyes"},
                          "chunkMaterials": [{"$value": "eyelashes_MAT"},
                                             {"$value": "blue_eyes"}]}},
                {"Data": {"name": {"$value": "green_eyes"},
                          "chunkMaterials": [{"$value": "eyelashes_MAT"},
                                             {"$value": "green_eyes"}]}}]}}}

    def test_changes_only_selected_eye_appearance(self):
        before = copy.deepcopy(self.mesh["Data"]["RootChunk"]["appearances"][1])
        self.assertEqual(change_material(self.mesh, "blue_eyes", "eyelashes__brown_liquorice"),
                         "eyelashes_MAT")
        appearances = self.mesh["Data"]["RootChunk"]["appearances"]
        self.assertEqual(appearances[0]["Data"]["chunkMaterials"][0]["$value"],
                         "eyelashes__brown_liquorice")
        self.assertEqual(appearances[1], before)

    def test_male_eye_mesh_keeps_lashes_in_own_appearances(self):
        # Shape of he_000_pma_c__basehead.mesh (vanilla and SedthS 3D Eyes V2), measured 02/10/2026.
        mesh = {"Data": {"RootChunk": {
            "materialEntries": [{"name": {"$value": "eyeMat3"}},
                                {"name": {"$value": "gradient_violet"}},
                                {"name": {"$value": "eyelashes__brown_liquorice"}}],
            "appearances": [
                {"Data": {"name": {"$value": "gradient_violet"},
                          "chunkMaterials": [{"$value": "eyeMat3"}, {"$value": "eyeWetness_MAT3"},
                                             {"$value": "gradient_violet"}]}},
                {"Data": {"name": {"$value": "eyelashes__brown_liquorice"},
                          "chunkMaterials": [{"$value": "eyelashes__brown_liquorice"},
                                             {"$value": "eyeWetness_MAT3"},
                                             {"$value": "blood_gradient_black"}]}}]}}}
        self.assertEqual(change_material(mesh, "gradient_violet", "eyelashes__brown_liquorice"), "eyeMat3")
        self.assertEqual(mesh["Data"]["RootChunk"]["appearances"][0]["Data"]["chunkMaterials"][0]["$value"],
                         "eyelashes__brown_liquorice")

    def test_rejects_chunk_zero_without_lash_evidence(self):
        mesh = copy.deepcopy(self.mesh)
        root = mesh["Data"]["RootChunk"]
        root["materialEntries"].append({"name": {"$value": "eyeMat3"}})
        root["appearances"][0]["Data"]["chunkMaterials"][0]["$value"] = "eyeMat3"
        with self.assertRaisesRegex(ValueError, "lacks an eyelash material chunk"):
            change_material(mesh, "blue_eyes", "eyelashes__brown_liquorice")

    def test_rejects_missing_material_or_eye_appearance(self):
        with self.assertRaisesRegex(ValueError, "absent from eye mesh"):
            change_material(self.mesh, "blue_eyes", "unknown")
        with self.assertRaisesRegex(ValueError, "exactly one"):
            change_material(self.mesh, "missing", "eyelashes__brown_liquorice")


if __name__ == "__main__":
    unittest.main()
