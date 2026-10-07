import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from npc_transform import fnv1a64, transform


def option(name, value, index, kind="appearance"):
    return {"body_part": "Head", "name": name, "kind": kind, "selected_name": value,
            "selected_index": index, "choice_count": 50, "active": True,
            "editable": True, "censored": False}


def component(name, mesh="base\\template.mesh"):
    return {"Data": {"name": {"$value": name}, "mesh": {"DepotPath": {
        "$type": "ResourcePath", "$storage": "string", "$value": mesh}},
        "meshAppearance": {"$value": "old"}}}


class TransformTests(unittest.TestCase):
    def setUp(self):
        self.source_root = "template\\npc"
        self.head = self.source_root + "\\head.mesh"
        names = ["h0_head", "t0_body", "he_eyes", "heb_eyebrows", "hh_hair", "hh_hair_shadow"]
        comps = [component(name) for name in names]
        comps[0]["Data"]["mesh"]["DepotPath"]["$value"] = fnv1a64(self.head)
        self.app = {"Data": {"RootChunk": {"appearances": [{"Data": {
            "components": copy.deepcopy(comps),
            "compiledData": {"Data": {"Chunks": copy.deepcopy(comps)}}}}]}}}
        self.ent = {"Data": {"RootChunk": {"appearances": [{
            "appearanceResource": {"DepotPath": {"$type": "ResourcePath", "$storage": "string",
                                                 "$value": self.source_root + "\\npc.app"}}}]}}}
        self.catalog = {"format": "npv-maker-hair-catalog", "schema_version": 1, "entries": {}}
        for slot, color in [(9, "09_blue_sapphire"), (3, "02_red_merlot")]:
            self.catalog["entries"][f"female:{slot}"] = {
                "body": "female", "slot_index": slot, "app_path": f"base\\hair\\slot{slot}.app",
                "colors": {color: {
                    "hair_components": [{"name": "hair", "mesh": f"base\\hair\\slot{slot}.mesh",
                                         "mesh_appearance": color}],
                    "shadow_components": [{"name": "shadow", "mesh": "base\\hair\\shadow.mesh",
                                           "mesh_appearance": "default"}]}}}

    def project(self, name, slot, color):
        return {"format": "npv-maker-project", "schema_version": 1, "name": name,
                "body": "female", "voice": "female", "dependency_status": "unresolved",
                "dependencies": [], "npc_status": "not_generated", "options": [
                    option("hairstyle", "", slot, "switcher"), option("hair_color10", color, 0),
                    option("skin_color", "h0__03_ca_senna", 4),
                    option("eyes_color", "he__15_gradient_light_blue", 5),
                    option("eyebrows", "", 6, "switcher"),
                    option("eyebrows_color7", "female__09_blue_sapphire", 8),
                    option("nose", "h012", 1, "morph"),
                ]}

    def test_two_named_projects_get_distinct_resources_and_hair(self):
        original = copy.deepcopy(self.app)
        results = []
        for name, slot, color in [("Ada", 9, "09_blue_sapphire"),
                                  ("Bea", 3, "02_red_merlot")]:
            app, ent, report = transform(self.project(name, slot, color), self.catalog,
                                         self.app, self.ent, self.source_root,
                                         ["head.mesh", "npc.app"])
            head = app["Data"]["RootChunk"]["appearances"][0]["Data"]["components"][0]["Data"]
            self.assertEqual(head["mesh"]["DepotPath"]["$value"],
                             fnv1a64(report["resource_root"] + "\\head.mesh"))
            self.assertEqual(ent["Data"]["RootChunk"]["appearances"][0]
                             ["appearanceResource"]["DepotPath"]["$value"], report["appearance_path"])
            self.assertEqual(report["morphs"][0]["shape_key"], "h012_nose")
            components = app["Data"]["RootChunk"]["appearances"][0]["Data"]["compiledData"]["Data"]["Chunks"]
            hair = next(c["Data"] for c in components if c["Data"]["name"]["$value"] == "hh_hair")
            self.assertIn(f"slot{slot}.mesh", hair["mesh"]["DepotPath"]["$value"])
            results.append(report["resource_root"])
        self.assertNotEqual(*results)
        self.assertEqual(self.app, original)

    def test_vanilla_resource_is_reused_when_no_morph_needs_baking(self):
        project = self.project("Cora", 9, "09_blue_sapphire")
        project["options"] = [x for x in project["options"] if x["name"] != "nose"]
        assets = {"format": "npv-maker-template-asset-map", "schema_version": 1,
                  "body": "female", "vanilla_references": {
                      "head.mesh": "base\\characters\\head\\head.mesh"}}
        app, _, report = transform(project, self.catalog, self.app, self.ent,
                                    self.source_root, ["head.mesh", "npc.app"], assets=assets)
        head = app["Data"]["RootChunk"]["appearances"][0]["Data"]["components"][0]["Data"]
        self.assertEqual(head["mesh"]["DepotPath"]["$value"],
                         fnv1a64("base\\characters\\head\\head.mesh"))
        self.assertEqual(report["required_custom_assets"], [])

    def test_eyelash_choice_keeps_eye_mesh_private_even_without_face_morphs(self):
        project = self.project("Dina", 9, "09_blue_sapphire")
        project["options"] = [x for x in project["options"] if x["name"] != "nose"]
        project["options"].append(option("eyelash_color", "female__brown", 2))
        eye = r"head\he_000_pwa_c__basehead.mesh"
        old = self.source_root + "\\" + eye
        app = copy.deepcopy(self.app)
        for components in (app["Data"]["RootChunk"]["appearances"][0]["Data"]["components"],
                           app["Data"]["RootChunk"]["appearances"][0]["Data"]["compiledData"]["Data"]["Chunks"]):
            eyes = next(x["Data"] for x in components if x["Data"]["name"]["$value"] == "he_eyes")
            eyes["mesh"]["DepotPath"]["$value"] = fnv1a64(old)
        assets = {"format": "npv-maker-template-asset-map", "schema_version": 1,
                  "body": "female", "vanilla_references": {eye: "base\\eyes.mesh"}}
        appearances = {"format": "npv-maker-appearance-catalog", "schema_version": 1,
                       "choices": {"eyelash_color": {"components": [
                           {"mesh_appearance": "eyelashes__brown"}]}}}
        changed, _, report = transform(project, self.catalog, app, self.ent,
                                       self.source_root, [eye, "npc.app"], appearances, assets)
        self.assertIn(eye, report["required_custom_assets"])
        self.assertEqual(changed["Data"]["RootChunk"]["appearances"][0]["Data"]["components"][2]
                         ["Data"]["mesh"]["DepotPath"]["$value"],
                         fnv1a64(report["resource_root"] + "\\" + eye))

    def test_selected_pimples_and_piercings_add_distinct_baked_components(self):
        project = self.project("Elisa", 9, "09_blue_sapphire")
        project["options"].extend([
            option("makeupPimples_03", "pimples_black", 2),
            option("piercings_11", "pearl", 7),
        ])
        app = copy.deepcopy(self.app)
        for group in (app["Data"]["RootChunk"]["appearances"][0]["Data"]["components"],
                      app["Data"]["RootChunk"]["appearances"][0]["Data"]["compiledData"]["Data"]["Chunks"]):
            group.extend([component("hx_makeup_freckles"), component("i1_earring")])
        base = r"base\characters\head\player_base_heads\player_female_average"
        appearances = {"format": "npv-maker-appearance-catalog", "schema_version": 1,
                       "choices": {
                           "makeupPimples_03": {"components": [{
                               "morph_resource": base + r"\hx_000_pwa__morphs_pimples_01.morphtarget",
                               "mesh_appearance": "pimples__black_02", "chunk_mask": "71"}]},
                           "piercings_11": {"components": [{
                               "morph_resource": base + rf"\i1_000_pwa__morphs_earring_{i:02d}.morphtarget",
                               "mesh_appearance": "pearl", "chunk_mask": str(100 + i)}
                               for i in (1, 2, 3)]},
                       }}
        overlays = [r"head\hx_000_pwa_c__basehead_pimples_01.mesh"] + [
            rf"head\i1_000_pwa_c__basehead_earring_{i:02d}.mesh" for i in (1, 2, 3)]
        changed, _, report = transform(project, self.catalog, app, self.ent,
                                       self.source_root, ["head.mesh", "npc.app", *overlays],
                                       appearances)
        components = changed["Data"]["RootChunk"]["appearances"][0]["Data"]["components"]
        by_name = {part["Data"]["name"]["$value"]: part["Data"] for part in components}
        self.assertEqual(by_name["hx_makeup_pimples_01"]["meshAppearance"]["$value"],
                         "pimples__black_02")
        self.assertEqual(by_name["i1_earring_02"]["chunkMask"], "102")
        self.assertEqual(by_name["i1_earring_03"]["mesh"]["DepotPath"]["$value"],
                         report["resource_root"] + "\\" + overlays[3])
        self.assertTrue(set(overlays).issubset(set(report["required_custom_assets"])))
        self.assertEqual(set(report["forced_custom_assets"]), set(overlays))
        self.assertEqual(report["catalog_pending"], [])

    def test_unselected_template_makeup_tattoo_and_earring_are_disabled(self):
        app = copy.deepcopy(self.app)
        optional = ("i1_earring", "hx_makeup_eyes", "hx_makeup_freckles",
                    "hx_makeup_lips_01", "h0_tattoo", "h0_cyberware_face")
        for group in (app["Data"]["RootChunk"]["appearances"][0]["Data"]["components"],
                      app["Data"]["RootChunk"]["appearances"][0]["Data"]["compiledData"]["Data"]["Chunks"]):
            group.extend(component(name) for name in optional)
        changed, _, _ = transform(self.project("Elisa", 9, "09_blue_sapphire"),
                                  self.catalog, app, self.ent, self.source_root,
                                  ["head.mesh", "npc.app"])
        for group in (changed["Data"]["RootChunk"]["appearances"][0]["Data"]["components"],
                      changed["Data"]["RootChunk"]["appearances"][0]["Data"]["compiledData"]["Data"]["Chunks"]):
            for name in optional:
                part = next(x["Data"] for x in group if x["Data"]["name"]["$value"] == name)
                self.assertEqual(part["isEnabled"], 0, name)

    def test_mod_hair_uses_captured_app_without_known_slot_index(self):
        project = self.project("Dara", 9, "09_blue_sapphire")
        project["options"][0]["selected_index"] = 77
        project["options"][0]["choice_count"] = 100
        project["options"][1]["selected_name"] = "mod_blue"
        appearances = {"format": "npv-maker-appearance-catalog", "schema_version": 1,
                       "choices": {"hair_color10": {"source_app": "mod\\hair.app",
                           "components": [
                               {"name": "custom_hair", "mesh": "mod\\hair.mesh",
                                "mesh_appearance": "blue_glow"},
                               {"name": "custom_shadow", "mesh": "mod\\shadow.mesh",
                                "mesh_appearance": "default"}]}}}
        app, _, report = transform(project, self.catalog, self.app, self.ent,
                                    self.source_root, ["head.mesh", "npc.app"], appearances)
        hair = app["Data"]["RootChunk"]["appearances"][0]["Data"]["components"][4]["Data"]
        self.assertEqual(hair["mesh"]["DepotPath"]["$value"], "mod\\hair.mesh")
        self.assertEqual(report["hair"]["source_app"], "mod\\hair.app")

    def test_mod_hair_with_two_meshes_and_no_shadow(self):
        project = self.project("Lena", 9, "09_blue_sapphire")
        project["options"][1]["name"] = "custom_hair"
        project["options"][1]["selected_name"] = "28_blue_sky"
        appearances = {"format": "npv-maker-appearance-catalog", "schema_version": 1,
                       "choices": {"custom_hair": {"source_app": "mod\\looks.app",
                           "components": [{"name": f"hair_part{i}",
                                           "mesh": f"mod\\hair_part{i}.mesh",
                                           "mesh_appearance": "blue_sky", "chunk_mask": "7"}
                                          for i in (1, 2)]}}}
        changed, _, report = transform(project, self.catalog, self.app, self.ent,
                                       self.source_root, ["head.mesh", "npc.app"], appearances)
        for group in (changed["Data"]["RootChunk"]["appearances"][0]["Data"]["components"],
                      changed["Data"]["RootChunk"]["appearances"][0]["Data"]["compiledData"]["Data"]["Chunks"]):
            parts = {item["Data"]["name"]["$value"]: item["Data"] for item in group}
            self.assertEqual(parts["hh_hair"]["meshAppearance"]["$value"], "blue_sky")
            self.assertEqual(parts["hh_hair_extra_02"]["mesh"]["DepotPath"]["$value"],
                             "mod\\hair_part2.mesh")
            self.assertEqual(parts["hh_hair_shadow"]["isEnabled"], 0)
        self.assertNotIn("custom_hair", report["catalog_pending"])


if __name__ == "__main__":
    unittest.main()
