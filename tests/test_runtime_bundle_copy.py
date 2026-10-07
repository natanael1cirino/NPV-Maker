import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from runtime_resources import Resources, archive_xl_resources, path_hash

VANILLA_EYE_MORPH = 'base\\characters\\head\\player_base_heads\\player_female_average\\he_000_pwa__morphs.morphtarget'
FIXED_EYE_MORPH = ('archive_xl\\characters\\head\\player_base_heads\\player_female_average\\'
                   'he_000_pwa__morphs_normal_fix.morphtarget')
# Lines of the installed ArchiveXL bundle PlayerCustomizationEyesPatch.xl (28/09/2026).
BUNDLE_EYES_PATCH = ('resource:\n  copy:\n    ' + VANILLA_EYE_MORPH + ':\n      - ' + FIXED_EYE_MORPH + '\n'
                     '  patch:\n    archive_xl\\common\\null.morphtarget:\n      props: [ baseTexture, baseTextureParamName ]\n'
                     '      targets:\n        - ' + FIXED_EYE_MORPH + '\n'
                     '    axl\\he_patch.mesh:\n      - base\\he_000_pwa_c__basehead.mesh\n')
MOD_XL = 'resource:\n  copy:\n    bby\\app.app:\n      - bby\\app_2.app\n'


class BundleCopyTests(unittest.TestCase):
    def test_copies_come_from_mods_and_from_the_archivexl_bundle_but_bundle_patches_do_not(self):
        with tempfile.TemporaryDirectory() as mods, tempfile.TemporaryDirectory() as bundle:
            (Path(mods) / 'mod.xl').write_text(MOD_XL, encoding='utf8')
            (Path(bundle) / 'PlayerCustomizationEyesPatch.xl').write_text(BUNDLE_EYES_PATCH, encoding='utf8')
            props = {}
            copies, patches = archive_xl_resources([Path(mods)], props, scope_folders=[Path(bundle)])
        self.assertEqual(copies, {'bby\\app_2.app': 'bby\\app.app', FIXED_EYE_MORPH.lower(): VANILLA_EYE_MORPH})
        self.assertEqual((patches, props), ({}, {}))

    def test_copy_named_by_hash_resolves_to_its_vanilla_source(self):
        # The ArchiveXL eye template appearance references the copy by hash.
        with tempfile.TemporaryDirectory() as folder:
            game = Path(folder)
            (game / 'archive/pc/mod').mkdir(parents=True)
            (game / 'archive/pc/mod/mod.xl').write_text(MOD_XL, encoding='utf8')
            bundle = game / 'red4ext/plugins/ArchiveXL/Bundle'
            bundle.mkdir(parents=True)
            (bundle / 'PlayerCustomizationEyesPatch.xl').write_text(BUNDLE_EYES_PATCH, encoding='utf8')
            reader = Resources(game, game / 'WolvenKit.CLI.exe', game / 'cache')
            self.assertEqual(path_hash(FIXED_EYE_MORPH), '2971506501429392748')
            self.assertEqual(reader.source('2971506501429392748'), VANILLA_EYE_MORPH)
            self.assertEqual(reader.source(FIXED_EYE_MORPH), VANILLA_EYE_MORPH)
            self.assertEqual(reader.source('bby\\app_2.app'), 'bby\\app.app')
            self.assertEqual(reader.source('12345'), '12345')


if __name__ == '__main__':
    unittest.main()
