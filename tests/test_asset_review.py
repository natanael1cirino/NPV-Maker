import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from asset_review import review


class AssetReviewTests(unittest.TestCase):
    def test_reports_external_copies_and_modifications_without_approving_them(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            template = root / "template"
            candidate = root / "candidate"
            archive = candidate / "npc.archive"
            archive.parent.mkdir()
            archive.write_bytes(b"archive")
            assets = [r"head\head.mesh", r"head\eyes.mesh"]
            for name, content in zip(assets, (b"head", b"eyes")):
                source = template.joinpath(*name.split("\\"))
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(content)
                packed = candidate / "archive_source" / "npvmaker" / "npv" / "example"
                packed = packed.joinpath(*name.split("\\"))
                packed.parent.mkdir(parents=True, exist_ok=True)
                packed.write_bytes(content + (b" changed" if "eyes" in name else b""))
            (candidate / "candidate-manifest.json").write_text(json.dumps({
                "format": "npv-maker-local-npc-candidate", "private_validation_only": True,
                "project_digest": "abc", "entity_path": r"npvmaker\npv\example\npc.ent",
                "custom_assets": assets, "archive": str(archive)}), encoding="utf8")
            provenance = root / "provenance.json"
            provenance.write_text(json.dumps({
                "purpose": "local NPC development input; not licensed for automatic redistribution",
                "source_zip": "tutorial.zip", "source_sha256": "abc"}), encoding="utf8")
            result = review(candidate, template, provenance)
            self.assertEqual([item["transformed"] for item in result["assets"]], [False, True])
            self.assertFalse(result["approved_for_distribution"])
            self.assertTrue(result["contains_external_assets"])


if __name__ == "__main__":
    unittest.main()
