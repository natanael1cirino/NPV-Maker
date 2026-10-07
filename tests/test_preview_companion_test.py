import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from preview_companion_test import preview


class CompanionPreviewTests(unittest.TestCase):
    def test_stages_only_code_and_plan_for_unapproved_external_archive(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = {"format": "npv-maker-project", "schema_version": 1,
                       "name": "Elisa", "body": "female", "voice": "female",
                       "dependencies": [], "dependency_status": "unresolved",
                       "npc_status": "not_generated", "options": [{
                           "body_part": "Head", "name": "eyes_color", "kind": "appearance",
                           "selected_name": "blue", "selected_index": 1, "choice_count": 3,
                           "active": True, "editable": True, "censored": False}]}
            source = root / "project.npv.json"
            source.write_text(json.dumps(project), encoding="utf8")
            raw = hashlib.sha256(source.read_bytes()).hexdigest()
            canonical = hashlib.sha256(json.dumps(project, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            archive = root / "npc.archive"
            archive.write_bytes(b"private game asset")
            archive_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
            spec = root / "spec.json"
            spec.write_text(json.dumps({
                "project_sha256": raw, "display_name": "Elisa", "body": "female",
                "visual_match_confirmed": False, "in_game_spawn_tested": False,
                "npc_archive_sha256": archive_hash, "npc_archive_path": str(archive),
                "record_id": "Character.NPVMaker_1234567890abcdef",
                "base_record": "Character.bella",
                "entity_path": r"npvmaker\npv\example\npc.ent",
                "appearance_name": "casual"}), encoding="utf8")
            review = root / "review.json"
            review.write_text(json.dumps({
                "format": "npv-maker-candidate-asset-review",
                "contains_external_assets": True, "approved_for_distribution": False,
                "project_digest": canonical, "archive_sha256": archive_hash,
                "assets": [{"resource": "head.mesh"}]}), encoding="utf8")
            output = preview(source, spec, review, root / "preview")
            plan = json.loads((output / "package-plan.json").read_text())
            self.assertFalse(plan["zip_created"])
            self.assertFalse(plan["asset_bundling_approved"])
            self.assertTrue((output / plan["staged_code_files"][0]).is_file())
            self.assertTrue((output / plan["staged_code_files"][1]).is_file())
            self.assertEqual(list(output.rglob("*.archive")), [])
            self.assertEqual(list(output.rglob("*.zip")), [])
            archive.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "missing or changed"):
                preview(source, spec, review, root / "refused")
            self.assertFalse((root / "refused").exists())


if __name__ == "__main__":
    unittest.main()
