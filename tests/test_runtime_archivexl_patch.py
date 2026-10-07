import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from runtime_import import install
from runtime_npc import archive_xl_text, inherit_patches
from runtime_resources import archive_xl_resources

# Measured 26/09/2026 with NPV "asia": Beanie's CCXL Clinic patches the vanilla
# freckles mesh; the morph-baked copy lost bby_cyberware_01 (grey face patch).
FRECKLES = 'base\\characters\\head\\player_base_heads\\player_female_average\\h0_000_pwa_c__basehead\\hx_000_pwa_c__basehead_makeup_freckles_01.mesh'
PATCH = 'bby_xtra_face_cyberware\\xtra_cyberware.mesh'
COPY = 'npvmaker\\generated\\771926010ebfaaf1\\meshes\\abfce3a06fd4bef4.mesh'


class Reader:
    def __init__(self, patches):
        self.patches = patches

    def source(self, path):
        return path


class ArchiveXlPatchTests(unittest.TestCase):
    def test_baked_copy_inherits_the_mod_patch(self):
        targets = {}
        inherit_patches(Reader({FRECKLES.lower(): [PATCH]}), FRECKLES, COPY, targets)
        self.assertEqual(targets, {PATCH: [COPY]})

    def test_mesh_without_patch_needs_no_xl(self):
        targets = {}
        inherit_patches(Reader({}), FRECKLES, COPY, targets)
        self.assertEqual(targets, {})

    def test_generated_xl_is_read_back_as_the_same_patch(self):
        text = archive_xl_text({PATCH: [COPY]})
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'npvmaker_771926010ebfaaf1.archive.xl').write_text(text, encoding='utf8')
            copies, patches = archive_xl_resources([Path(folder)])
        self.assertEqual(copies, {})
        self.assertEqual(patches, {COPY.lower(): [PATCH]})

    def test_name_table_is_declared_for_every_language(self):
        names = 'npvmaker\\generated\\771926010ebfaaf1\\names.json'
        text = archive_xl_text({}, names)
        self.assertTrue(text.startswith('localization:\n  onscreens:\n'))
        for code in ('en-us', 'pt-br', 'es-es', 'zh-cn'):
            self.assertIn('    ' + code + ': ' + names + '\n', text)
        self.assertNotIn('resource:', text)

    def test_name_resource_matches_the_onscreens_layout(self):
        from runtime_npc import names_resource
        doc = names_resource({'DataType': 'CR2W'}, 'NPVMaker-771926010ebfaaf1-name', 'asia')
        root = doc['Data']['RootChunk']
        self.assertEqual(root['$type'], 'JsonResource')
        entries = root['root']['Data']['entries']
        self.assertEqual(root['root']['Data']['$type'], 'localizationPersistenceOnScreenEntries')
        self.assertEqual(entries, [{'$type': 'localizationPersistenceOnScreenEntry', 'femaleVariant': 'asia',
                                    'maleVariant': '', 'primaryKey': '0',
                                    'secondaryKey': 'NPVMaker-771926010ebfaaf1-name'}])

    def test_record_points_to_the_name_key(self):
        from companion_expansion import bridge_yaml
        yaml = bridge_yaml({'name': 'asia', 'body': 'female'}, 'Character.NPVMaker_771926010ebfaaf1',
                           'Character.bella', 'x.ent', 'default', 'NPVMaker-771926010ebfaaf1-name')
        self.assertIn('  displayName: "NPVMaker-771926010ebfaaf1-name"\n', yaml)
        self.assertIn('  fullDisplayName: "NPVMaker-771926010ebfaaf1-name"\n', yaml)
        self.assertNotIn('"asia"', yaml)

    def test_install_writes_the_xl_beside_the_archive(self):
        with tempfile.TemporaryDirectory() as temp:
            game = Path(temp) / 'game'
            companion = game / 'r6/scripts/Companion/AikoNPVFramework.reds'
            companion.parent.mkdir(parents=True)
            companion.write_text('public class AikoNPVRegistrySystem extends ScriptableSystem {}')
            archive = Path(temp) / 'npc.archive'
            archive.write_bytes(b'archive')
            digest = hashlib.sha256(b'asia').hexdigest()
            token = digest[:16]
            manifest = dict(format='npv-maker-runtime-npc', local_use_only=True, project_sha256=digest,
                            record_id='Character.NPVMaker_' + token,
                            entity_path='npvmaker\\generated\\' + token + '\\character.ent',
                            archive=str(archive), name='asia', body='female', appearance_name='default',
                            base_record='Character.bella', archive_xl=archive_xl_text({PATCH: [COPY]}))
            receipt = install(game, manifest)
            written = (game / 'archive/pc/mod' / ('npvmaker_' + token + '.archive.xl')).read_text(encoding='utf8')
        self.assertIn('archive/pc/mod/npvmaker_' + token + '.archive.xl', receipt['files'])
        self.assertIn('      - ' + COPY, written)


if __name__ == '__main__':
    unittest.main()
