import hashlib
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import adapters  # noqa: E402
import runtime_import  # noqa: E402
from runtime_resources import path_hash  # noqa: E402

THAI = [['h101', 'eyes'], ['h012', 'nose'], ['h133', 'mouth'], ['h134', 'jaw']]
SCRIPT = ROOT / 'src/redscript/NPVMakerMorphs.reds'


def code(text):
    return '\n'.join(line.split('//', 1)[0] for line in text.splitlines())


class MorphsBackTests(unittest.TestCase):
    """BUGS 82 (05/10/2026, author in game): the Thai remade with package 35 (no shapes in game) lost her Asian
    features and was right again with weight 1 (probe 80b). The shapes are applied again, and the photo mode puppet of
    PhotoMode-EX (its own photomode.ent) gets the same shape list."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        archive = Path(self.tmp.name) / 'test.archive'
        archive.write_bytes(b'generated-test-archive')
        self.digest = hashlib.sha256(b'thai').hexdigest()
        self.token = self.digest[:16]
        self.photo = 'npvmaker\\generated\\' + self.token + '\\photomode.ent'
        self.manifest = dict(format='npv-maker-runtime-npc', local_use_only=True, project_sha256=self.digest,
                             record_id='Character.NPVMaker_' + self.token,
                             entity_path='npvmaker\\generated\\' + self.token + '\\character.ent',
                             archive=str(archive), name='Thai', body='female', appearance_name='default',
                             base_record='Character.bella', runtime_morphs=THAI,
                             photomode={'entity': self.photo,
                                        'atlas': 'npvmaker\\generated\\' + self.token + '\\photomode_icon.inkatlas'})

    def files(self, photomode=True):
        chosen = adapters.clean({'photomode': photomode})
        return {k: v.decode('utf8') for k, v in runtime_import.npv_files(self.manifest, chosen).items()}

    def test_photo_mode_puppet_gets_the_shapes(self):
        text = self.files()['r6/tweaks/NPVMaker/generated_' + self.token + '_photomode.yaml']
        self.assertIn('NPVMaker.morphs_' + path_hash(self.photo) + ':', text)
        for target, region in THAI:
            self.assertIn('n"' + target + '", n"' + region + '"', text)

    def test_world_npv_keeps_its_shapes(self):
        text = self.files()['r6/tweaks/NPVMaker/generated_' + self.token + '.yaml']
        self.assertIn('NPVMaker.morphs_' + path_hash(self.manifest['entity_path']) + ':', text)

    def test_without_photo_mode_there_is_no_photo_file(self):
        self.assertNotIn('r6/tweaks/NPVMaker/generated_' + self.token + '_photomode.yaml', self.files(False))

    def test_npv_without_shapes_writes_no_flat(self):
        self.manifest['runtime_morphs'] = []
        for name, text in self.files().items():
            if name.endswith('.yaml'):
                self.assertNotIn('NPVMaker.morphs_', text, name)

    def test_script_applies_the_shapes_in_game(self):
        body = code(SCRIPT.read_text(encoding='utf-8'))
        self.assertIn('ApplyMorphTarget', body)
        self.assertIsNotNone(re.search(r'"NPVMaker\.morphs_"', body))

    def test_script_reaches_photo_mode_puppets_and_refreshes_through_zero(self):
        body = code(SCRIPT.read_text(encoding='utf-8'))
        self.assertIn('Entity/AfterAttach', body)
        self.assertIn('gameuiPhotoModeMenuController', body)
        self.assertIn('0.0', body)


if __name__ == '__main__':
    unittest.main()
