import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import ingame_companion_worker as worker


class IngameCompanionWorkerTests(unittest.TestCase):
    def test_explicit_installation_does_not_use_development_paths(self):
        with tempfile.TemporaryDirectory(prefix="npv other installation ") as tmp:
            root = Path(tmp)
            project_id, config = self.make_project(root)
            def fake_build(project, supplied_config, output):
                self.assertEqual(supplied_config, config)
                self.assertTrue(project.is_relative_to(root / "game"))
                self.assertTrue(output.is_relative_to(root / "portable-data"))
                output.mkdir(parents=True)
                (output / "asset-review.json").write_text(json.dumps({"assets": []}))
            with patch.object(worker, "ROOT", root / "unavailable-development"), \
                 patch.object(worker, "CONFIG", root / "missing-development-config.json"), \
                 patch.object(worker, "build_candidate", side_effect=fake_build), \
                 patch.object(worker, "preview"):
                result = worker.run("build", project_id, config_file=config, root=root / "portable-data")
                self.assertTrue(result.is_relative_to(root / "portable-data"))
                status = worker.paths(project_id, config, root / "portable-data")["status"]
                self.assertEqual(json.loads(status.read_text())["stage"], "ready")

    def make_project(self, root: Path):
        game = root / "game"
        mod = game / "bin/x64/plugins/cyber_engine_tweaks/mods/NPVMaker"
        folder = mod / "projects"
        folder.mkdir(parents=True)
        project_id = "npv-20260923T120000Z-0001"
        project = {"format": "npv-maker-project", "schema_version": 1,
                   "name": "Lia", "body": "female", "voice": "female",
                   "dependencies": [], "dependency_status": "unresolved",
                   "npc_status": "not_generated", "options": [{
                       "body_part": "Head", "name": "eyes_color", "kind": "appearance",
                       "selected_name": "blue", "selected_index": 1, "choice_count": 3,
                       "active": True, "editable": True, "censored": False}]}
        (folder / f"{project_id}.npv.json").write_text(json.dumps(project), encoding="utf8")
        config = root / "config.json"
        config.write_text(json.dumps({"game": str(game), "body": "female"}), encoding="utf8")
        return project_id, config

    def test_paths_use_generated_revision_and_reject_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_id, config = self.make_project(root)
            found = worker.paths(project_id, config, root)
            self.assertEqual(found["project"].name, project_id + ".npv.json")
            self.assertIn(project_id, found["candidate"].name)
            self.assertEqual(found["zip"].parent, root / "releases")
            for bad in ("../other", "AGATHA", project_id + ".json"):
                with self.assertRaisesRegex(ValueError, "Invalid generated"):
                    worker.paths(bad, config, root)

    def test_build_and_private_package_are_separate_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_id, config = self.make_project(root)
            def fake_build(project, supplied_config, output):
                self.assertEqual(project.name, project_id + ".npv.json")
                output.mkdir(parents=True)
                (output / "asset-review.json").write_text(json.dumps({"assets": [{"resource": "head.mesh"}]}))
                (output / "companion-bridge-spec.json").write_text("{}")
            def fake_preview(project, spec, review, staged):
                staged.mkdir()
            def fake_package(project, spec, review, staged, destination, *, include_reviewed_assets):
                self.assertTrue(include_reviewed_assets)
                destination.parent.mkdir(parents=True)
                destination.write_bytes(b"private zip")
                return destination
            with patch.object(worker, "ROOT", root), patch.object(worker, "CONFIG", config), \
                 patch.object(worker, "build_candidate", side_effect=fake_build), \
                 patch.object(worker, "preview", side_effect=fake_preview), \
                 patch.object(worker, "package", side_effect=fake_package) as packaged:
                candidate = worker.run("build", project_id)
                self.assertTrue(candidate.is_dir())
                self.assertFalse((root / "releases").exists())
                packaged.assert_not_called()
                status = json.loads(worker.paths(project_id, config, root)["status"].read_text())
                self.assertEqual(status["stage"], "ready")
                result = worker.run("package", project_id)
                self.assertEqual(result.read_bytes(), b"private zip")
                self.assertEqual(json.loads(worker.paths(project_id, config, root)["status"].read_text())["stage"], "packaged")


if __name__ == "__main__":
    unittest.main()
