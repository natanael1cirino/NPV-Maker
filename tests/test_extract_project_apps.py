import sys
import unittest
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from extract_project_apps import wanted_paths, declared_mesh_paths, resolve_declared_meshes, archive_xl_material_sources


class ExtractProjectAppsTests(unittest.TestCase):
    def test_mesh_hash_is_resolved_only_from_matching_installed_declaration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = r"subleader\uuh4v_framework\heart_pt1.mesh"
            (root / "hair.xl").write_text("resource:\n  scope:\n    hair.mesh:\n      - " + path)
            paths = declared_mesh_paths([root])
            self.assertEqual(paths["14158563202883427014"], path)
            doc = [{"$type": "ResourcePath", "$storage": "uint64", "$value": "14158563202883427014"},
                   {"$type": "ResourcePath", "$storage": "uint64", "$value": "999"}]
            resolve_declared_meshes(doc, paths)
            self.assertEqual(doc[0]["$value"], path)
            self.assertEqual(doc[0]["$storage"], "string")
            self.assertEqual(doc[1]["$value"], "999")

    def test_framework_redirects_are_read_from_installed_fix_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, target = r"base\eyes.app", r"archive_xl\eyes.app"
            (root / "PlayerCustomizationEyesFix.xl").write_text(
                "resource:\n  fix:\n    creator:\n      paths:\n        " + source + ": " + target + "\n")
            self.assertEqual(archive_xl_material_sources(root), {target: source})

    def test_only_selected_appearance_resources_are_extracted(self):
        project = {"options": [
            {"name": "skin_color", "selected_name": "skin1", "resource_path": "ResourceAsyncRef[ ]",
             "kind": "appearance", "active": True, "editable": True},
            {"name": "unused_makeup", "selected_name": "None", "resource_path": "ResourceAsyncRef[ ]",
             "kind": "appearance", "active": True, "editable": True},
            {"name": "custom_hair", "selected_name": "28_blue_sky",
             "resource_path": r"custom\hair\looks.app", "kind": "appearance",
             "active": True, "editable": True},
        ]}
        self.assertEqual(wanted_paths(project), [r"custom\hair\looks.app"])


if __name__ == "__main__":
    unittest.main()
