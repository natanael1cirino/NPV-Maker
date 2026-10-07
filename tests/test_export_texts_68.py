import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tests'))
import npv_package as pkg  # noqa: E402
from test_npv_package import FakeLocator, Fixture, form, key  # noqa: E402

UST = '##_Arkhe_UniversalSkinTone_HEAD_VANILLA_Natural.archive'
UST_ZIP = '10 - HEAD - NATURAL-15426-3-0-1720411510.zip'
HAIR_ZIP = 'Vessnelle hair collection pack 2-5406-1-0-1664135678.zip'
D01 = 'base\\characters\\head\\player_base_heads\\player_female_average\\h0_000_pwa_c__basehead\\textures\\h0_000_pwa_c__basehead_d01.xbm'
HAIR1 = 'vessnelle\\hair_1.mesh'
HAIR2 = 'vessnelle\\hair_2.mesh'
MANAGER = ROOT / 'src/redscript/NPVMakerManager.reds'


def write_zip(folder, name, members):
    with zipfile.ZipFile(folder / name, 'w') as bundle:
        for member in members:
            bundle.writestr(member, b'x')


class NexusDownloadTests(unittest.TestCase):
    """BUGS 68 (04/10/2026): mods extracted by hand have no Vortex record, so they came without Nexus ID. The
    .zip downloaded from Nexus keeps the Nexus name with the mod id (measured in the author's Downloads)."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        write_zip(self.root, UST_ZIP, ['archive/pc/mod/' + UST])
        write_zip(self.root, HAIR_ZIP, ['archive/pc/mod/vessnelle_hair_1.archive', 'archive/pc/mod/vessnelle_hair_2.archive'])
        write_zip(self.root, 'renomeado.zip', ['archive/pc/mod/other.archive'])

    def test_archive_found_in_a_nexus_download(self):
        found = pkg.download_sources([self.root], {UST.lower(), 'other.archive', 'nowhere.archive'})
        self.assertEqual(found, {UST.lower(): UST_ZIP[:-4]})

    def test_downloads_of_different_mods_give_no_id(self):
        write_zip(self.root, 'Outro mod-999-1-0-1700000000.zip', ['archive/pc/mod/' + UST])
        self.assertEqual(pkg.download_sources([self.root], {UST.lower()}), {})

    def test_requirement_gets_name_id_and_one_entry_per_download(self):
        locator = FakeLocator(mods={UST: {key(D01)}, 'vessnelle_hair_1.archive': {key(HAIR1)},
                                    'vessnelle_hair_2.archive': {key(HAIR2)}}, base={key(D01)}, frameworks={})
        entries = [{'resource': D01, 'archive': None, 'via': 'material'},
                   {'resource': HAIR1, 'archive': None, 'via': 'reference'},
                   {'resource': HAIR2, 'archive': None, 'via': 'reference'}]
        roots = [self.root]
        found = pkg.detect_dependencies(Path('.'), entries, locator, {}, lambda names: pkg.download_sources(roots, names))
        by_name = {d['name']: d for d in found['dependencies']}
        self.assertEqual(sorted(by_name), ['10 - HEAD - NATURAL', 'Vessnelle hair collection pack 2'])
        self.assertEqual((by_name['10 - HEAD - NATURAL']['nexus_mod_id'], by_name['10 - HEAD - NATURAL']['url']),
                         (15426, 'https://www.nexusmods.com/cyberpunk2077/mods/15426'))
        self.assertEqual(by_name['10 - HEAD - NATURAL']['detected_from'], 'nexus download')
        self.assertEqual(sorted(by_name['Vessnelle hair collection pack 2']['archives']),
                         ['vessnelle_hair_1.archive', 'vessnelle_hair_2.archive'])
        plain = pkg.detect_dependencies(Path('.'), entries[:1], locator, {})
        self.assertEqual((plain['dependencies'][0]['name'], plain['dependencies'][0]['nexus_mod_id']),
                         (UST[:-8], None))


class IntegrationTextTests(unittest.TestCase):
    """BUGS 68: photo mode needs PhotoMode-EX (18839); the NCA command needs GetMod; NEXUS.txt notice in English."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.fx = Fixture(Path(temp.name))

    def export(self, integrations, version='1.0.0'):
        draft = self.fx.draft()
        deps = [dict(d, author='', include=True, detected=i) for i, d in enumerate(draft['dependencies'])]
        done = pkg.export(self.fx.plugin, self.fx.projects, self.fx.token,
                          {'fields': form(version), 'dependencies': deps, 'integrations': integrations},
                          draft, self.fx.exports)
        return ((done['folder'] / 'Seila-REQUIREMENTS.txt').read_text(encoding='utf8'),
                (done['folder'] / 'Seila-NEXUS.txt').read_text(encoding='utf8'))

    def test_photo_mode_names_photomode_ex(self):
        requirements, nexus = self.export({'photomode': True})
        for text in (requirements, nexus):
            self.assertIn('PhotoMode-EX', text)
            self.assertIn('https://www.nexusmods.com/cyberpunk2077/mods/18839', text)
            self.assertNotIn('Photo mode (base game)', text)

    def test_nca_command_with_getmod_for_a_companion_only(self):
        record = 'Character.NPVMaker_' + self.fx.token
        command = 'NCA = GetMod("NightCityAllies"); NCA:ForceSpawnCharacter("' + record + '")'
        requirements, nexus = self.export({'nca': True})
        self.assertEqual(requirements.count(command), 3)
        self.assertIn('no console do CET', requirements)
        self.assertIn(command, nexus)
        merc_requirements, merc_nexus = self.export({'nca': True, 'nca_merc': True}, '1.0.1')
        self.assertNotIn('ForceSpawnCharacter', merc_requirements + merc_nexus)

    def test_window_flags_missing_id_and_photo_mode(self):
        text = MANAGER.read_text(encoding='utf8')
        self.assertIn('if dep.detected >= 0 && StrLen(dep.nexus) == 0 { label += NPVText.T("  [sem Nexus ID: use EDITAR]"); };', text)
        mods = text[text.index('private func RenderMods'):]
        mods = mods[:mods.index('\n  }\n')]
        self.assertIn('if this.withPhoto {', mods)
        self.assertIn('PhotoMode-EX (Nexus 18839)', mods)


if __name__ == '__main__':
    unittest.main()
