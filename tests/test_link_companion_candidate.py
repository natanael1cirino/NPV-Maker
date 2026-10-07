import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from link_companion_candidate import link


class LinkCandidateTests(unittest.TestCase):
    def test_links_exact_project_archive_without_marking_visual_match(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = {"format": "npv-maker-project", "schema_version": 1,
                       "name": "Cora", "body": "female", "voice": "female",
                       "dependencies": [], "dependency_status": "unresolved",
                       "npc_status": "not_generated", "options": [{
                           "body_part": "Head", "name": "eyes_color", "kind": "appearance",
                           "selected_name": "blue", "selected_index": 1, "choice_count": 3,
                           "active": True, "editable": True, "censored": False}]}
            source = root / "cora.npv.json"
            source.write_text(json.dumps(project), encoding="utf8")
            archive = root / "npc.archive"
            archive.write_bytes(b"candidate")
            entity = r"npvmaker\npv\cora\cora.ent"
            appearance = r"npvmaker\npv\cora\cora.app"
            candidate = {"format": "npv-maker-local-npc-candidate", "body": "female",
                         "project_digest": hashlib.sha256(
                             json.dumps(project, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
                         "entity_path": entity, "appearance_path": appearance,
                         "appearance_name": "casual", "archive": str(archive)}
            manifest = root / "candidate.json"
            manifest.write_text(json.dumps(candidate), encoding="utf8")
            output = root / "spec.json"
            with patch("link_companion_candidate.check_archive", return_value=appearance):
                link(source, manifest, root / "cli.exe", "Character.bella", output)
            spec = json.loads(output.read_text())
            self.assertEqual(spec["display_name"], "Cora")
            self.assertEqual(spec["npc_archive_sha256"], hashlib.sha256(b"candidate").hexdigest())
            self.assertFalse(spec["visual_match_confirmed"])
            self.assertFalse(spec["in_game_spawn_tested"])


if __name__ == "__main__":
    unittest.main()
