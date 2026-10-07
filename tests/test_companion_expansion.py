from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from companion_expansion import check_archive, export, prepare, validate_spec


class CompanionBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.project = self.root / "agatha.npv.json"
        self.project.write_text(json.dumps({
            "format": "npv-maker-project", "schema_version": 1,
            "name": "AGATHA", "body": "female", "voice": "female",
            "options": [{"body_part": "Head", "name": "hair_color10", "kind": "appearance",
                         "selected_name": "09_blue_sapphire", "selected_index": 9,
                         "choice_count": 16, "active": True, "editable": True,
                         "censored": False}],
            "dependencies": [], "dependency_status": "unresolved",
            "npc_status": "not_generated",
        }), encoding="utf-8")
        self.spec_path = prepare(self.project, self.root / "bridge-spec.json")
        self.archive = self.root / "agatha.archive"
        self.archive.write_bytes(b"test-NPC-archive")

    def tearDown(self):
        self.tmp.cleanup()

    def ready_spec(self):
        spec = json.loads(self.spec_path.read_text(encoding="utf-8"))
        spec.update(base_record="Character.bella",
                    entity_path="npvmaker\\agatha\\agatha.ent",
                    appearance_name="agatha_default",
                    npc_archive_path=str(self.archive),
                    npc_archive_sha256=hashlib.sha256(self.archive.read_bytes()).hexdigest(),
                    visual_match_confirmed=True, asset_origin="self_authored")
        self.spec_path.write_text(json.dumps(spec), encoding="utf-8")
        return spec

    def test_agatha_prepare_is_not_an_installable_npc(self):
        spec = json.loads(self.spec_path.read_text(encoding="utf-8"))
        self.assertEqual(spec["display_name"], "AGATHA")
        self.assertEqual(spec["body"], "female")
        self.assertIsNone(spec["entity_path"])
        self.assertFalse(spec["visual_match_confirmed"])
        self.assertEqual(list(self.root.glob("*.zip")), [])

    def test_bridge_requires_visual_match_and_same_revision(self):
        spec = json.loads(self.spec_path.read_text(encoding="utf-8"))
        with self.assertRaisesRegex(ValueError, "visually matched"):
            validate_spec(json.loads(self.project.read_text()),
                          hashlib.sha256(self.project.read_bytes()).hexdigest(), spec)
        self.ready_spec()
        self.project.write_text(self.project.read_text().replace("AGATHA", "OTHER"))
        with self.assertRaisesRegex(ValueError, "another project revision"):
            export(self.project, self.spec_path, self.root / "cli.exe", self.root / "bridge.zip")
        self.assertFalse((self.root / "bridge.zip").exists())

    def test_bridge_validates_archive_hash_and_never_bundles_assets(self):
        self.ready_spec()
        self.archive.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "archive changed"):
            export(self.project, self.spec_path, self.root / "cli.exe", self.root / "bridge.zip")
        self.ready_spec()
        with patch("companion_expansion.check_archive", return_value="npvmaker\\agatha\\agatha.app"):
            package = export(self.project, self.spec_path, self.root / "cli.exe", self.root / "bridge.zip")
        with ZipFile(package) as bundle:
            self.assertIsNone(bundle.testzip())
            files = bundle.namelist()
            self.assertEqual(len(files), 4)
            self.assertFalse(any(f.endswith((".archive", ".ent", ".app")) for f in files))
            yaml = bundle.read(next(f for f in files if f.endswith(".yaml"))).decode()
            self.assertIn("tags: [CompanionFramework]", yaml)
            self.assertIn("visualTags: [WomanAverage]", yaml)
            self.assertIn("appearanceName: agatha_default", yaml)
            self.assertIn('displayName: "AGATHA"', yaml)
            script = bundle.read(next(f for f in files if f.endswith(".reds"))).decode()
            self.assertIn("Session/Ready", script)
            self.assertIn("UnlockCompanion", script)
            self.assertIn("CompanionFramework.Character.NPVMaker_", script)
            manifest = json.loads(bundle.read("NPV-Maker-Companion-manifest.json"))
            self.assertFalse(manifest["archive_bundled"])
            self.assertFalse(manifest["in_game_spawn_tested"])

    def test_bridge_rejects_path_traversal_and_incorrect_body(self):
        spec = self.ready_spec()
        project = json.loads(self.project.read_text())
        spec["entity_path"] = "..\\other.ent"
        with self.assertRaisesRegex(ValueError, "Invalid"):
            validate_spec(project, spec["project_sha256"], spec)
        spec["entity_path"] = "npvmaker\\agatha\\agatha.ent"
        spec["body"] = "male"
        with self.assertRaisesRegex(ValueError, "body differs"):
            validate_spec(project, spec["project_sha256"], spec)


if __name__ == "__main__":
    unittest.main()
