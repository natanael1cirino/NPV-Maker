import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from appearance_catalog import build_catalog, require_captured_choices, hair_mesh_variant


class AppearanceCatalogTests(unittest.TestCase):
    def test_color_variant_rejects_an_unresolved_hair_part(self):
        app = {"Data": {"RootChunk": {"appearances": [{"Data": {
            "name": {"$value": "01_blonde"}, "components": [
                {"$type": "entSkinnedMeshComponent", "name": {"$value": "hair_part"},
                 "mesh": {"DepotPath": {"$value": "99999"}},
                 "meshAppearance": {"$value": "blonde"}}]}}]}}}
        self.assertIsNone(hair_mesh_variant(app, "28_blue_sky", []))

    def test_runtime_redirect_keeps_capture_and_resolves_only_exact_legacy_choice(self):
        source, target = r"base\eyes.app", r"archive_xl\eyes.app"
        project = {"options": [{"name": "eyes_color", "kind": "appearance",
                                 "selected_name": "legacy_grey", "resource_path": target,
                                 "active": True, "editable": True}]}
        creator = {"Data": {"RootChunk": {key: [] for key in (
            "headCustomizationOptions", "bodyCustomizationOptions", "armsCustomizationOptions")}}}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for path, name in ((source, "legacy_grey"), (target, "generated_base")):
                file = root.joinpath(*path.split("\\"))
                file.parent.mkdir(parents=True)
                Path(str(file) + ".json").write_text(json.dumps({"Data": {"RootChunk": {
                    "appearances": [{"Data": {"name": {"$value": name}, "components": [
                        {"meshAppearance": {"$value": "gradient_grey"}}]}}]}}}))
            self.assertIn("eyes_color", build_catalog(project, creator, root)["unresolved"])
            result = build_catalog(project, creator, root, material_sources={target: source})
            self.assertEqual(result["choices"]["eyes_color"]["source_app"], target)
            self.assertEqual(result["choices"]["eyes_color"]["material_metadata_source"], source)
            project["options"][0]["selected_name"] = "unavailable_mod_eye"
            self.assertIn("eyes_color", build_catalog(project, creator, root,
                          material_sources={target: source})["unresolved"])

    def test_numbered_mod_hair_color_resolves_against_each_mesh(self):
        path = r"custom\hair\looks.app"
        meshes = [r"custom\hair\part1.mesh", r"custom\hair\part2.mesh"]
        creator = {"Data": {"RootChunk": {key: [] for key in (
            "headCustomizationOptions", "bodyCustomizationOptions", "armsCustomizationOptions")}}}
        project = {"options": [{"name": "custom_hair", "kind": "appearance",
                                 "selected_name": "28_blue_sky", "resource_path": path,
                                 "active": True, "editable": True}]}
        app = {"Data": {"RootChunk": {"appearances": [{"Data": {
            "name": {"$value": "01_blonde"},
            "components": [{"$type": "entSkinnedMeshComponent",
                            "name": {"$value": f"hair_part{index}"},
                            "mesh": {"DepotPath": {"$value": mesh}},
                            "meshAppearance": {"$value": "blonde"},
                            "chunkMask": "123"}
                           for index, mesh in enumerate(meshes, 1)]}}]}}}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app_file = root.joinpath(*path.split("\\"))
            app_file.parent.mkdir(parents=True)
            Path(str(app_file) + ".json").write_text(json.dumps(app), encoding="utf8")
            for mesh in meshes:
                file = root.joinpath(*mesh.split("\\"))
                file.parent.mkdir(parents=True, exist_ok=True)
                Path(str(file) + ".json").write_text(json.dumps({"Data": {"RootChunk": {
                    "appearances": [{"Data": {"name": {"$value": "blue_sky"}}}]}}}), encoding="utf8")
            catalog = build_catalog(project, creator, root)
            self.assertEqual([part["mesh_appearance"] for part in
                              catalog["choices"]["custom_hair"]["components"][:2]],
                             ["blue_sky", "blue_sky"])
            self.assertEqual(catalog["unresolved"], {})
            second = root.joinpath(*meshes[1].split("\\"))
            Path(str(second) + ".json").unlink()
            catalog = build_catalog(project, creator, root)
            self.assertIn("custom_hair", catalog["unresolved"])

    def test_internal_choice_resolves_exact_material_from_source_app(self):
        resource = r"base\characters\head\makeup.app"
        creator = {"Data": {"RootChunk": {
            "headCustomizationOptions": [{"Data": {
                "name": {"$value": "makeupCheeks_02"},
                "resource": {"DepotPath": {"$value": resource}}}}],
            "bodyCustomizationOptions": [], "armsCustomizationOptions": []}}}
        project = {"options": [{"name": "makeupCheeks_02", "kind": "appearance",
                                 "selected_name": "hx__04_brown", "active": True,
                                 "editable": True}]}
        app = {"Data": {"RootChunk": {"appearances": [{"Data": {
            "name": {"$value": "hx__04_brown"},
            "components": [{"meshAppearance": {"$value": "frecles_brown_06"},
                            "chunkMask": "12345",
                            "name": {"$value": "hx_freckles"}}]}}]}}}
        with tempfile.TemporaryDirectory() as temp:
            file = Path(temp).joinpath(*resource.split("\\"))
            file.parent.mkdir(parents=True)
            Path(str(file) + ".json").write_text(json.dumps(app), encoding="utf8")
            catalog = build_catalog(project, creator, Path(temp))
        self.assertEqual(catalog["choices"]["makeupCheeks_02"]["components"][0]
                         ["mesh_appearance"], "frecles_brown_06")
        self.assertEqual(catalog["choices"]["makeupCheeks_02"]["components"][0]
                         ["chunk_mask"], "12345")
        self.assertEqual(catalog["unresolved"], {})

    def test_captured_mod_resource_takes_priority_over_vanilla_creator(self):
        creator = {"Data": {"RootChunk": {
            "headCustomizationOptions": [{"Data": {
                "name": {"$value": "eyes_color"},
                "resource": {"DepotPath": {"$value": r"base\vanilla.app"}}}}],
            "bodyCustomizationOptions": [], "armsCustomizationOptions": []}}}
        project = {"options": [{"name": "eyes_color", "kind": "appearance",
                                 "selected_name": "mod_blue", "resource_path": r"mod\eyes.app",
                                 "active": True, "editable": True}]}
        app = {"Data": {"RootChunk": {"appearances": [{"Data": {
            "name": {"$value": "mod_blue"},
            "components": [{"meshAppearance": {"$value": "blue_glow"}}]}}]}}}
        with tempfile.TemporaryDirectory() as temp:
            file = Path(temp) / "mod" / "eyes.app.json"
            file.parent.mkdir()
            file.write_text(json.dumps(app), encoding="utf8")
            catalog = build_catalog(project, creator, Path(temp))
        self.assertEqual(catalog["choices"]["eyes_color"]["source_app"], r"mod\eyes.app")
        self.assertEqual(catalog["choices"]["eyes_color"]["components"][0]
                         ["mesh_appearance"], "blue_glow")
        require_captured_choices(project, catalog)

    def test_missing_captured_mod_resource_cannot_fall_back_to_vanilla(self):
        project = {"options": [{"name": "hair_color12", "kind": "appearance",
                                 "selected_name": "mod_blue", "resource_path": r"mod\hair.app",
                                 "active": True, "editable": True}]}
        catalog = {"choices": {}, "unresolved": {"hair_color12": "Missing serialized mod\\hair.app"}}
        with self.assertRaisesRegex(ValueError, "hair_color12.*Missing serialized"):
            require_captured_choices(project, catalog)


if __name__ == "__main__":
    unittest.main()
