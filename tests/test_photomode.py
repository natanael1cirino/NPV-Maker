import hashlib
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import photomode
from runtime_import import install

TOKEN = "8357e654f65cc7f2"
APP = "npvmaker\\generated\\" + TOKEN + "\\character.app"
ENT = "npvmaker\\generated\\" + TOKEN + "\\photomode.ent"
ATLAS = "npvmaker\\generated\\" + TOKEN + "\\photomode_icon.inkatlas"


def template():
    return {"Header": {}, "Data": {"RootChunk": {"$type": "entEntityTemplate", "appearances": [
        {"$type": "entTemplateAppearance", "name": photomode.cname("judy_photomode_default"),
         "appearanceName": photomode.cname("default"), "appearanceResource": photomode.ref("base\\judy.app")}],
        "defaultAppearance": photomode.cname("judy_photomode_default"), "components": [{"name": photomode.cname("root")}]}}}


class FilesTest(unittest.TestCase):
    def test_icon_is_a_256_png(self):
        data = photomode.icon_png("Thai")
        self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"))
        width, height = struct.unpack(">II", data[16:24])
        self.assertEqual((width, height), (256, 256))
        # Every chunk CRC is right (WolvenKit refuses a damaged PNG).
        offset = 8
        while offset < len(data):
            length = struct.unpack(">I", data[offset:offset + 4])[0]
            kind = data[offset + 4:offset + 8]
            body = data[offset + 8:offset + 8 + length]
            self.assertEqual(struct.unpack(">I", data[offset + 8 + length:offset + 12 + length])[0],
                             zlib.crc32(kind + body) & 0xFFFFFFFF)
            offset += 12 + length
        self.assertEqual(photomode.initial("  thai"), "T")
        self.assertEqual(photomode.initial("123"), "?")

    def test_entity_keeps_the_template_and_uses_the_npv_appearance(self):
        doc = photomode.entity(template(), APP)
        root = doc["Data"]["RootChunk"]
        self.assertEqual(len(root["components"]), 1)
        self.assertEqual([a["appearanceResource"]["DepotPath"]["$value"] for a in root["appearances"]], [APP])
        self.assertEqual(root["defaultAppearance"]["$value"], "default")

    def test_record_and_scope_follow_the_published_npvs(self):
        text = photomode.record_yaml(TOKEN, ENT, "NPVMaker-" + TOKEN + "-name", ATLAS)
        self.assertIn("Character.NPVMaker_" + TOKEN + "_Photomode_Puppet:", text)
        self.assertIn("persistentName: PhotomodePuppet", text)
        self.assertIn("$type: PhotoModeSticker", text)
        self.assertIn("imagePartName: npv_icon", text)
        self.assertIn('entityTemplatePath: "npvmaker\\\\generated\\\\' + TOKEN + '\\\\photomode.ent"', text)
        self.assertEqual(photomode.scope_xl("female", ENT), "resource:\n  scope:\n    photomode_wa.ent:\n      - " + ENT + "\n")
        self.assertIn("photomode_ma.ent", photomode.scope_xl("male", ENT))


class InstallTest(unittest.TestCase):
    def manifest(self, photo):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        archive = Path(temp.name) / "npv.archive"
        archive.write_bytes(b"archive")
        digest = hashlib.sha256(b"pm").hexdigest()
        self.game = Path(temp.name) / "game"
        self.token = digest[:16]
        return dict(format="npv-maker-runtime-npc", local_use_only=True, project_sha256=digest,
                    record_id="Character.NPVMaker_" + digest[:16],
                    entity_path="npvmaker\\generated\\" + digest[:16] + "\\character.ent", archive=str(archive),
                    name="Thai", body="male", appearance_name="default", base_record="Character.bella",
                    name_key="NPVMaker-" + digest[:16] + "-name", photomode=photo)

    def test_written_only_when_marked(self):
        photo = {"entity": ENT, "atlas": ATLAS, "scope": "photomode_ma.ent"}
        manifest = self.manifest(photo)
        result = install(self.game, manifest, require_companion=False, integrations={"photomode": True})
        files = set(result["files"])
        self.assertIn("r6/tweaks/NPVMaker/generated_" + self.token + "_photomode.yaml", files)
        xl = (self.game / ("archive/pc/mod/npvmaker_" + self.token + "_photomode.xl")).read_text(encoding="utf8")
        self.assertIn("photomode_ma.ent", xl)

    def test_not_marked_or_missing_files_install_without_photo_mode(self):
        manifest = self.manifest({"entity": ENT, "atlas": ATLAS})
        result = install(self.game, manifest, require_companion=False, integrations={"nca": True})
        self.assertFalse(any("photomode" in f for f in result["files"]))
        manifest = self.manifest(None)
        result = install(self.game, manifest, require_companion=False, integrations={"photomode": True})
        self.assertFalse(any("photomode" in f for f in result["files"]))


if __name__ == "__main__":
    unittest.main()
