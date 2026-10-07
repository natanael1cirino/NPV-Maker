import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from runtime_npc import collect_components
from runtime_resources import ResourceMissing


EYE_MASK = '18446744073709551614'
LASH_MASK = '18446744073709551609'
ALL_MASK = '18446744073709551615'
MORPH = 'base\\characters\\head\\player_base_heads\\player_female_average\\he_000_pwa__morphs.morphtarget'
EYE_APP = 'archive_xl\\characters\\head\\player_base_heads\\appearances\\head\\he_000_pwa__basehead.app'
LASH_APP = 'archive_xl\\characters\\head\\player_base_heads\\appearances\\head\\hel_000_pwa__basehead.app'


def cname(name):
    return {'$type': 'CName', '$storage': 'string', '$value': name}


def morph_part(name, cid, mask, mesh_appearance, morph=MORPH):
    return {'$type': 'entMorphTargetSkinnedMeshComponent', 'name': cname(name), 'id': cid,
            'morphResource': {'DepotPath': {'$value': morph}}, 'meshAppearance': cname(mesh_appearance),
            'chunkMask': mask}


def app(*looks):
    return {'Data': {'RootChunk': {'appearances': [
        {'Data': {'name': cname(name), 'components': list(parts)}} for name, parts in looks]}}}


class Reader:
    def __init__(self, resources):
        self.resources = resources

    def read(self, path):
        if path not in self.resources:
            raise ResourceMissing('Recurso nao encontrado nos mods instalados: ' + path)
        return copy.deepcopy(self.resources[path])


def option(name, resource, selected):
    return dict(name=name, resource_path=resource, selected_name=selected)


def eye_component(result):
    found = [p for k, p in result['selected'].items() if k[0] == 'MorphTargetSkinnedMesh3637']
    assert len(found) == 1, found
    return found[0]


class EyelashChunkTests(unittest.TestCase):
    """Item 39. Values measured on the Mako capture (job 7eaacab2227a5e4c) and on
    he_000/hel_000 .app of the base game and of the ArchiveXL bundle."""

    def setUp(self):
        eye = morph_part('MorphTargetSkinnedMesh3637', '2133220414002642944', EYE_MASK, 'gradient_grey')
        lash_carbon = morph_part('MorphTargetSkinnedMesh3637', '2133220414002642944', LASH_MASK,
                                 'eyelashes__black_carbon')
        lash_blonde = morph_part('MorphTargetSkinnedMesh3637', '2133220414002642944', LASH_MASK,
                                 'eyelashes__blonde_platinum')
        self.reader = Reader({
            EYE_APP: app(('he_000_pwa__basehead__14_gradient_grey', [eye])),
            LASH_APP: app(('female__06_black_carbon', [lash_carbon]),
                          ('female__01_blonde_platinum', [lash_blonde])),
        })
        self.eyes = option('eyes_color', EYE_APP, 'he_000_pwa__basehead__14_gradient_grey')
        self.lash = option('eyelash_color', LASH_APP, 'female__06_black_carbon')

    def test_active_lash_shows_the_chunk_v_draws(self):
        result = collect_components(self.reader, [self.eyes, self.lash], {})
        eye = eye_component(result)
        self.assertEqual(eye['chunkMask'], ALL_MASK)
        self.assertEqual(int(eye['chunkMask']) & 1, 1)
        self.assertEqual(eye['meshAppearance']['$value'], 'gradient_grey')
        self.assertEqual(result['lash_material'], 'eyelashes__black_carbon')
        self.assertIs(result['eye_part'], eye)
        self.assertEqual(len(result['selected']), 1)

    def test_order_of_options_does_not_matter(self):
        result = collect_components(self.reader, [self.lash, self.eyes], {})
        self.assertEqual(eye_component(result)['chunkMask'], ALL_MASK)

    def test_without_lash_option_chunk_zero_stays_hidden(self):
        result = collect_components(self.reader, [self.eyes], {})
        eye = eye_component(result)
        self.assertEqual(eye['chunkMask'], EYE_MASK)
        self.assertEqual(int(eye['chunkMask']) & 1, 0)
        self.assertIsNone(result['lash_material'])

    def test_lash_choice_that_hides_chunk_zero_adds_nothing(self):
        hidden = morph_part('MorphTargetSkinnedMesh3637', '2133220414002642944', EYE_MASK, 'eyelashes__none')
        self.reader.resources[LASH_APP]['Data']['RootChunk']['appearances'].append(
            {'Data': {'name': cname('female__00_none'), 'components': [hidden]}})
        result = collect_components(self.reader, [self.eyes, option('eyelash_color', LASH_APP,
                                                                     'female__00_none')], {})
        self.assertEqual(eye_component(result)['chunkMask'], EYE_MASK)

    def test_lash_colour_changes_material_not_mask(self):
        carbon = collect_components(self.reader, [self.eyes, self.lash], {})
        blonde = collect_components(self.reader, [self.eyes, option('eyelash_color', LASH_APP,
                                                                    'female__01_blonde_platinum')], {})
        self.assertEqual(eye_component(carbon)['chunkMask'], eye_component(blonde)['chunkMask'])
        self.assertEqual(blonde['lash_material'], 'eyelashes__blonde_platinum')
        self.assertEqual(eye_component(blonde)['meshAppearance']['$value'], 'gradient_grey')

    def test_lash_on_other_geometry_leaves_the_eye_alone(self):
        own = morph_part('MorphTargetSkinnedMesh3637', '2133220414002642944', LASH_MASK,
                         'eyelashes__black_carbon', morph='mod\\lashes\\lashes.morphtarget')
        self.reader.resources[LASH_APP] = app(('female__06_black_carbon', [own]))
        result = collect_components(self.reader, [self.eyes, self.lash], {})
        self.assertEqual(eye_component(result)['chunkMask'], EYE_MASK)

    def test_mod_lashes_in_their_own_option_keep_the_eye_mask(self):
        # Soft Natural (icxrus) lashes: own option and own mesh; the eye keeps
        # chunk 0 hidden and the mod piece is its own component.
        mod = {'$type': 'entSkinnedMeshComponent', 'name': cname('softnatural_eyelashes'), 'id': '7',
               'mesh': {'DepotPath': {'$value': 'icxrus\\lashes.mesh'}}, 'meshAppearance': cname('black_carbon'),
               'chunkMask': ALL_MASK}
        self.reader.resources['icxrus.app'] = app(('black_carbon', [mod]))
        result = collect_components(self.reader, [self.eyes, option('icxrus_softnaturaleyelashes', 'icxrus.app',
                                                                    'black_carbon')], {})
        self.assertEqual(eye_component(result)['chunkMask'], EYE_MASK)
        self.assertEqual(sorted(k[0] for k in result['selected']),
                         ['MorphTargetSkinnedMesh3637', 'softnatural_eyelashes'])

    def test_male_vanilla_identity_works_the_same(self):
        eye = morph_part('he_000_pma__basehead', '2024510947074064384', EYE_MASK, 'blue')
        lash = morph_part('he_000_pma__basehead', '2024510947074064384', LASH_MASK, 'eyelashes__black_carbon')
        reader = Reader({'eye.app': app(('look', [eye])), 'lash.app': app(('male__06_black_carbon', [lash]))})
        result = collect_components(reader, [option('eyes_color', 'eye.app', 'look'),
                                             option('eyelash_color', 'lash.app', 'male__06_black_carbon')], {})
        found = [p for k, p in result['selected'].items() if k[0] == 'he_000_pma__basehead']
        self.assertEqual(found[0]['chunkMask'], ALL_MASK)

    def test_mako_npc_mask_matches_the_editor_puppet(self):
        # runtime_manifest of the Mako project: the two LOADED rows of this
        # component; V shows the union of their chunks.
        editor = [EYE_MASK, LASH_MASK]
        drawn = 0
        for mask in editor:
            drawn |= int(mask)
        result = collect_components(self.reader, [self.eyes, self.lash], {})
        self.assertEqual(int(eye_component(result)['chunkMask']), drawn)


if __name__ == '__main__':
    unittest.main()
