import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from package_private_companion_test import package
from preview_companion_test import preview


class PrivateCompanionPackageTests(unittest.TestCase):
    def test_requires_explicit_local_asset_authorization_and_preserves_review_status(self):
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
            canonical = hashlib.sha256(json.dumps(project, sort_keys=True,
                                                 ensure_ascii=False).encode()).hexdigest()
            archive = root / "npc.archive"
            archive.write_bytes(b"private game asset")
            archive_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
            spec = root / "spec.json"
            spec.write_text(json.dumps({
                "format": "npv-maker-companion-bridge-spec", "schema_version": 1,
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
                "private_validation_only": True, "project_digest": canonical,
                "archive_sha256": archive_hash,
                "assets": [{"resource": "head.mesh"}]}), encoding="utf8")
            staged = preview(source, spec, review, root / "preview")
            output = root / "releases" / "Elisa-private.zip"
            with self.assertRaisesRegex(ValueError, "Explicit local-test"):
                package(source, spec, review, staged, output,
                        include_reviewed_assets=False)
            self.assertFalse(output.exists())
            package(source, spec, review, staged, output,
                    include_reviewed_assets=True)
            with ZipFile(output) as bundle:
                self.assertIsNone(bundle.testzip())
                names = bundle.namelist()
                self.assertEqual(len(names), 5)
                archive_member = f"archive/pc/mod/NPVMaker_{raw[:16]}.archive"
                self.assertEqual(bundle.read(archive_member), archive.read_bytes())
                manifest = json.loads(bundle.read(
                    "NPV-Maker-Companion-private-test-manifest.json"))
                self.assertTrue(manifest["private_test_only"])
                self.assertFalse(manifest["approved_for_distribution"])
                self.assertFalse(manifest["in_game_spawn_tested"])
            self.assertFalse(json.loads(review.read_text())["approved_for_distribution"])
            self.assertFalse(json.loads((staged / "package-plan.json").read_text())["zip_created"])
            archive.write_bytes(b"changed after review")
            tampered = root / "releases" / "tampered.zip"
            with self.assertRaisesRegex(ValueError, "missing or changed"):
                package(source, spec, review, staged, tampered,
                        include_reviewed_assets=True)
            self.assertFalse(tampered.exists())


if __name__ == "__main__":
    unittest.main()
