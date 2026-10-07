import json
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from hair_catalog import build_catalog, resolve_hair


def component(name, mesh, appearance):
    return {"Data": {"name": {"$value": name},
                     "mesh": {"DepotPath": {"$value": mesh}},
                     "meshAppearance": {"$value": appearance}}}


class HairCatalogTests(unittest.TestCase):
    def test_resolves_multiple_characters_without_character_specific_rules(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "base/characters/head/player_base_heads/appearances/hairs"
            root.mkdir(parents=True)
            entries = [
                ("hh_009_pwa__hairs_079.app.json", "base\\characters\\common\\hair\\denny.mesh", "09_blue_sapphire"),
                ("hh_003_pma__hairs_028.app.json", "base\\characters\\common\\hair\\bun.mesh", "02_red_merlot"),
            ]
            for filename, mesh, color in entries:
                doc = {"Data": {"RootChunk": {"appearances": [
                    {"Data": {"name": {"$value": color}, "components": [
                        component("hair", mesh, "blue_sapphire"),
                        component("shadow", "base\\characters\\common\\hair\\shadow_meshes\\s.mesh", "default"),
                    ]}}]}}}
                (root / filename).write_text(json.dumps(doc), encoding="utf8")
            catalog = build_catalog(list(root.glob("*.json")))
            for body, slot, color, expected_mesh in [
                ("female", 9, "09_blue_sapphire", "denny.mesh"),
                ("male", 3, "02_red_merlot", "bun.mesh"),
            ]:
                project = {"body": body, "options": [
                    {"name": "hairstyle", "active": True, "editable": True, "selected_index": slot},
                    {"name": "hair_color10", "active": True, "editable": True, "selected_name": color},
                ]}
                self.assertTrue(resolve_hair(project, catalog)["hair_components"][0]["mesh"].endswith(expected_mesh))

    def test_unknown_modded_slot_is_explicitly_unresolved(self):
        project = {"body": "female", "options": [
            {"name": "hairstyle_cyberware", "active": True, "editable": True, "selected_index": 77},
            {"name": "hair_color77", "active": True, "editable": True, "selected_name": "custom"},
        ]}
        with self.assertRaisesRegex(ValueError, "female:77 is missing"):
            resolve_hair(project, {"format": "npv-maker-hair-catalog", "schema_version": 1, "entries": {}})


if __name__ == "__main__":
    unittest.main()
