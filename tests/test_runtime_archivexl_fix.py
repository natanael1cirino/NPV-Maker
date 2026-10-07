import copy
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from runtime_npc import archive_xl_text, copied_fixes
from runtime_resources import Resources, archive_xl_fixes

EYE = 'base\\characters\\head\\player_base_heads\\player_female_average\\h0_000_pwa_c__basehead\\he_000_pwa_c__basehead.mesh'
EYE_M = 'base\\characters\\head\\player_base_heads\\player_man_average\\h0_000_pma_c__basehead\\he_000_pma_c__basehead.mesh'
HAIR = 'base\\characters\\common\\hair\\hh_006_ma__demo\\hh_006_ma__demo.mesh'
FRECKLES = 'base\\characters\\head\\player_base_heads\\player_female_average\\h0_000_pwa_c__basehead\\hx_000_pwa_c__basehead_makeup_freckles_01.mesh'
# The NPC eye mesh of the 0.4.17 "olhos de galaxia" import (28/09/2026).
COPY = 'npvmaker\\generated\\02bccbc1ea2830a9\\meshes\\96a896042e78e09f.mesh'
COPY_2 = 'npvmaker\\generated\\02bccbc1ea2830a9\\meshes\\b7e1e67c1b37f900.mesh'
CCO = 'base\\gameplay\\gui\\fullscreen\\main_menu\\female_cco.inkcharcustomization'

# Excerpts of the installed ArchiveXL bundle (28/09/2026), anchors and aliases kept.
EYES_FIX = ('resource:\n  fix:\n'
            '    ' + CCO + ': &AppearanceFixF\n'
            '      paths:\n'
            '        base\\characters\\head\\player_base_heads\\appearances\\head\\he_000__basehead.app: '
            'archive_xl\\characters\\head\\player_base_heads\\appearances\\head\\he_000_pwa__basehead.app\n'
            '    ep1\\gameplay\\gui\\fullscreen\\main_menu\\female_cco_ep1.inkcharcustomization: *AppearanceFixF\n'
            '    ' + EYE + ':\n'
            '      names: &MaterialFix\n'
            '        blood_gradient_black: blood_gradient_black@eyes\n'
            '        cybereye: cyber_eye@eyes\n'
            '        gradient_red: gradient_red@eyes\n'
            '    ' + EYE_M + ':\n'
            '      names: *MaterialFix\n')
LASHES_FIX = ('resource:\n  fix:\n'
              '    ' + EYE + ':\n'
              '      context:\n'
              '        LashesBaseMaterial: archive_xl\\characters\\common\\eyes\\hel_pwa.mi\n'
              '        AppearanceExpansionSource: eyelashes__blonde_platinum\n'
              '      names:\n'
              '        eyelashes__black_carbon: black_carbon@lashes\n')
HAIR_FIX = ('resource:\n  fix:\n'
            '    ' + HAIR + ':\n'
            '      names:\n'
            '        phoenix_fire_cap: phoenix_fire@cap\n'
            '      context:\n'
            '        CapBaseMaterial: archive_xl\\characters\\common\\hair\\textures\\hair_profiles\\hh_006_ma__demo_cap.mi\n')
EYE_FIX = {'names': {'blood_gradient_black': 'blood_gradient_black@eyes', 'cybereye': 'cyber_eye@eyes',
                     'gradient_red': 'gradient_red@eyes', 'eyelashes__black_carbon': 'black_carbon@lashes'},
           'context': {'LashesBaseMaterial': 'archive_xl\\characters\\common\\eyes\\hel_pwa.mi',
                       'AppearanceExpansionSource': 'eyelashes__blonde_platinum'}}


TEMPORARY = []


def tearDownModule():
    for temporary in TEMPORARY:
        temporary.cleanup()


def game_with(bundle: dict, mods: dict) -> Resources:
    """Resources of a fake installation holding only these .xl files."""
    temporary = tempfile.TemporaryDirectory()
    TEMPORARY.append(temporary)
    folder = Path(temporary.name)
    for root, files in (('red4ext/plugins/ArchiveXL/Bundle', bundle), ('archive/pc/mod', mods)):
        (folder / root).mkdir(parents=True)
        for name, text in files.items():
            (folder / root / name).write_text(text, encoding='utf8')
    return Resources(folder, folder / 'WolvenKit.CLI.exe', folder / 'cache')


class ArchiveXlFixTests(unittest.TestCase):
    def test_fix_of_the_original_path_follows_the_copy(self):
        reader = game_with({'PlayerCustomizationEyesFix.xl': EYES_FIX,
                            'PlayerCustomizationLashesFix.xl': LASHES_FIX}, {})
        fixes = copied_fixes(reader, {COPY: EYE})
        self.assertEqual(fixes, {COPY: EYE_FIX})
        text = archive_xl_text({}, None, fixes)
        self.assertIn('resource:\n  fix:\n    ' + COPY + ':\n      names:\n'
                      '        blood_gradient_black: blood_gradient_black@eyes\n', text)
        self.assertIn('      context:\n        LashesBaseMaterial: archive_xl\\characters\\common\\eyes\\hel_pwa.mi\n', text)

    def test_copy_without_fix_adds_nothing(self):
        reader = game_with({'PlayerCustomizationEyesFix.xl': EYES_FIX}, {})
        self.assertEqual(copied_fixes(reader, {COPY_2: FRECKLES}), {})
        text = archive_xl_text({}, None, {})
        self.assertNotIn('resource:', text)
        self.assertNotIn('fix:', text)

    def test_only_the_fixes_of_copied_paths_travel(self):
        reader = game_with({'PlayerCustomizationEyesFix.xl': EYES_FIX, 'PlayerCustomizationLashesFix.xl': LASHES_FIX,
                            'PlayerCustomizationHairFix.xl': HAIR_FIX}, {})
        fixes = copied_fixes(reader, {COPY: EYE, COPY_2: FRECKLES})
        self.assertEqual(list(fixes), [COPY])
        # `paths` only changes the character creator file; a mesh copy never takes it.
        self.assertEqual(set(fixes[COPY]), {'names', 'context'})
        text = archive_xl_text({}, None, fixes)
        self.assertNotIn(HAIR, text)
        self.assertNotIn('phoenix_fire', text)
        self.assertNotIn('paths:', text)
        self.assertNotIn('inkcharcustomization', text)

    def test_original_path_keeps_its_fix(self):
        reader = game_with({'PlayerCustomizationEyesFix.xl': EYES_FIX,
                            'PlayerCustomizationLashesFix.xl': LASHES_FIX}, {})
        before = copy.deepcopy(reader.fixes)
        fixes = copied_fixes(reader, {COPY: EYE})
        fixes[COPY]['names']['gradient_red'] = 'changed'
        text = archive_xl_text({}, None, fixes)
        self.assertEqual(reader.fixes, before)
        self.assertNotIn(EYE, text)
        self.assertEqual(reader.fixes[EYE.lower()]['names']['gradient_red'], 'gradient_red@eyes')

    def test_mod_fix_merges_after_the_bundle_and_bad_entries_are_skipped(self):
        # ArchiveXL reads the bundle first, then the mod folders, and joins the
        # fixes of one path; an entry whose names are not a map is ignored.
        mod = ('resource:\n  fix:\n    ' + EYE + ':\n      names:\n        gradient_red: red_mod@eyes\n'
               '    ' + FRECKLES + ':\n      names: not_a_map\n')
        reader = game_with({'PlayerCustomizationEyesFix.xl': EYES_FIX}, {'mod.xl': mod})
        self.assertEqual(reader.fixes[EYE.lower()]['names']['gradient_red'], 'red_mod@eyes')
        self.assertEqual(reader.fixes[EYE.lower()]['names']['cybereye'], 'cyber_eye@eyes')
        self.assertNotIn(FRECKLES.lower(), reader.fixes)

    def test_dream_galaxy_eye_copy_gets_the_rule_that_makes_its_material(self):
        # MEDIDO EM 28/09/2026 (ArchiveXL log, 0.4.17): protoss_dg13 was expanded
        # from blood_gradient_black on the NPC copy and failed ("@material"); with
        # the fix it becomes protoss_dg13@eyes, whose template @eyes the patch has.
        reader = game_with({'PlayerCustomizationEyesFix.xl': EYES_FIX,
                            'PlayerCustomizationLashesFix.xl': LASHES_FIX},
                           {'DreamGalaxyEyesCCXL.archive.xl': 'resource:\n  patch:\n'
                            '    protossvoid\\dreamgalaxyeyesccxl\\meshes\\patch.mesh:\n      - player_wa_eyes.mesh\n'})
        text = archive_xl_text({'protossvoid\\dreamgalaxyeyesccxl\\meshes\\patch.mesh': [COPY]}, None,
                               copied_fixes(reader, {COPY: EYE}))
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'npvmaker_02bccbc1ea2830a9.archive.xl').write_text(text, encoding='utf8')
            read_back = archive_xl_fixes([Path(folder)])
        self.assertEqual(read_back, {COPY.lower(): EYE_FIX})
        self.assertIn('    protossvoid\\dreamgalaxyeyesccxl\\meshes\\patch.mesh:\n      - ' + COPY + '\n', text)

    def test_aliases_and_quoted_names_are_read_like_yaml(self):
        fixes = archive_xl_fixes_of({'b.xl': EYES_FIX + "    'x\\y.mesh':\n      names:\n"
                                             "        '@odd': \"quoted@eyes\"  # comment\n"})
        self.assertEqual(fixes[EYE_M.lower()]['names'], fixes[EYE.lower()]['names'])
        self.assertEqual(fixes['x\\y.mesh']['names'], {'@odd': 'quoted@eyes'})
        text = archive_xl_text({}, None, {COPY: {'names': {'@odd': "it's"}, 'context': {}}})
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'n.xl').write_text(text, encoding='utf8')
            self.assertEqual(archive_xl_fixes([Path(folder)])[COPY.lower()]['names'], {'@odd': "it's"})


def archive_xl_fixes_of(files: dict) -> dict:
    with tempfile.TemporaryDirectory() as folder:
        for name, text in files.items():
            (Path(folder) / name).write_text(text, encoding='utf8')
        return archive_xl_fixes([Path(folder)])


if __name__ == '__main__':
    unittest.main()
