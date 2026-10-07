"""Pieces from mods are referenced, never copied (BUGS items 67b/67c/71/72, author decision 03/10/2026)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import runtime_import
import runtime_npc
from runtime_resources import Resources, path_hash
from test_runtime_eyelash_chunks import (EYE_APP, EYE_MASK, LASH_APP, LASH_MASK, MORPH, Reader, app, morph_part,
                                         option)

HEAD_MORPH = 'base\\characters\\head\\player_base_heads\\player_man_average\\h0_000_pma__morphs.morphtarget'
HEAD_MESH = 'base\\characters\\head\\player_base_heads\\player_man_average\\h0_000_pma_c__basehead\\h0_000_pma_c__basehead.mesh'


def morph_doc(base, targets=()):
    return {'Data': {'RootChunk': {'baseMesh': {'DepotPath': {'$value': base}},
                                   'targets': [{'name': {'$value': n}, 'regionName': {'$value': r}} for n, r in targets]}}}


class ModReader:
    def __init__(self, mods=(), donors=None):
        self.mods, self.donors = set(mods), donors or {}

    def from_mod(self, path):
        return path in self.mods

    def props_donor(self, path):
        return self.donors.get(path)


def resources(mod_paths=(), copies=None, patched=()):
    reader = Resources.__new__(Resources)
    reader.hash_types, reader.copies = {}, copies or {}
    reader.prop_patches = {int(path_hash(p)): ('donor', ['blob']) for p in patched}
    reader.mod_index = {int(path_hash(p)): [Path('mod.archive')] for p in mod_paths}
    return reader


class FromModTests(unittest.TestCase):
    def test_file_a_mod_archive_ships(self):
        self.assertTrue(resources([HEAD_MORPH]).from_mod(HEAD_MORPH))

    def test_game_file_is_not_from_a_mod(self):
        self.assertFalse(resources([]).from_mod(HEAD_MORPH))

    def test_archivexl_copy_of_a_mod_file(self):
        copy_target = 'archive_xl\\copied.morphtarget'
        self.assertTrue(resources([HEAD_MORPH], copies={copy_target: HEAD_MORPH}).from_mod(copy_target))

    def test_file_a_mod_patches_properties_into(self):
        self.assertTrue(resources([], patched=[HEAD_MORPH]).from_mod(HEAD_MORPH))


class ExternalMorphTests(unittest.TestCase):
    def test_morphtarget_from_a_head_mod(self):
        # AFT (03/10/2026): base mesh from the game, morphtarget from Dante (kinda).
        self.assertTrue(runtime_npc.external_morph(ModReader([HEAD_MORPH]), HEAD_MORPH, morph_doc(HEAD_MESH)))

    def test_base_mesh_from_a_mod(self):
        self.assertTrue(runtime_npc.external_morph(ModReader([HEAD_MESH]), HEAD_MORPH, morph_doc(HEAD_MESH)))

    def test_props_filled_from_a_mod_file(self):
        reader = ModReader(['arkhe\\brow.morphtarget'], {HEAD_MORPH: 'arkhe\\brow.morphtarget'})
        self.assertTrue(runtime_npc.external_morph(reader, HEAD_MORPH, morph_doc(HEAD_MESH)))

    def test_game_piece_is_still_baked(self):
        self.assertFalse(runtime_npc.external_morph(ModReader(), HEAD_MORPH, morph_doc(HEAD_MESH)))

    def test_reader_without_origin_keeps_the_old_path(self):
        self.assertFalse(runtime_npc.external_morph(object(), HEAD_MORPH, morph_doc(HEAD_MESH)))


class RuntimeMorphTests(unittest.TestCase):
    def options(self):
        return [dict(name='eyes', kind='morph', active=True, selected_name='None'),
                dict(name='nose', kind='morph', active=True, selected_name='h142'),
                dict(name='mouth', kind='morph', active=True, selected_name='h183'),
                dict(name='jaw', kind='morph', active=False, selected_name='h134'),
                dict(name='breast', kind='morph', active=True, selected_name='breast_big'),
                dict(name='hair', kind='appearance', active=True, selected_name='h142')]

    def test_pairs_the_kept_pieces_declare_in_editor_order(self):
        shapes = runtime_npc.declared_shapes(morph_doc(HEAD_MESH, [('h183', 'mouth'), ('h142', 'nose'), ('h134', 'jaw')]))
        self.assertEqual(runtime_npc.runtime_morphs(self.options(), shapes), [['h142', 'nose'], ['h183', 'mouth']])

    def test_body_shape_of_a_body_mod(self):
        self.assertEqual(runtime_npc.runtime_morphs(self.options(), {'breast_big_breast'}), [['breast_big', 'breast']])

    def test_manager_component(self):
        manager = runtime_npc.morph_manager()
        self.assertEqual(manager['$type'], 'entMorphTargetManagerComponent')
        self.assertEqual(manager['name']['$value'], runtime_npc.MORPH_MANAGER_NAME)


class EyeCompositionTests(unittest.TestCase):
    """Item 72: an eye from a mod is drawn like V, eye and lashes as two components on the original file."""

    def setUp(self):
        eye = morph_part('MorphTargetSkinnedMesh3637', '2133220414002642944', EYE_MASK, 'gradient_grey')
        lash = morph_part('MorphTargetSkinnedMesh3637', '2133220414002642944', LASH_MASK, 'black_carbon')
        self.reader = Reader({EYE_APP: app(('he_000_pwa__basehead__14_gradient_grey', [eye])),
                              LASH_APP: app(('female__06_black_carbon', [lash]))})
        self.options = [option('eyes_color', EYE_APP, 'he_000_pwa__basehead__14_gradient_grey'),
                        option('eyelash_color', LASH_APP, 'female__06_black_carbon')]

    def test_collect_keeps_the_eye_mask_and_the_lash_draw(self):
        result = runtime_npc.collect_components(self.reader, self.options, {})
        self.assertEqual(result['eye_mask'], EYE_MASK)
        self.assertEqual(len(result['eye_lashes']), 1)
        self.assertEqual(result['eye_lashes'][0]['chunkMask'], LASH_MASK)
        self.assertEqual(result['eye_lashes'][0]['meshAppearance']['$value'], 'black_carbon')

    def test_lash_component_has_its_own_name_and_id(self):
        result = runtime_npc.collect_components(self.reader, self.options, {})
        lash = runtime_npc.lash_component(result['eye_part'], result['eye_lashes'][0])
        self.assertEqual(lash['name']['$value'], 'MorphTargetSkinnedMesh3637_lashes')
        self.assertNotEqual(lash['id'], result['eye_part']['id'])
        self.assertEqual(lash['morphResource']['DepotPath']['$value'], MORPH)
        self.assertEqual((lash['chunkMask'], lash['meshAppearance']['$value']), (LASH_MASK, 'black_carbon'))


class MorphFlatTests(unittest.TestCase):
    ENTITY = 'npvmaker\\generated\\c1832f642e51643e\\character.ent'

    def test_flat_keyed_by_the_entity_file(self):
        flat = runtime_import.morph_flat({'runtime_morphs': [['h142', 'nose'], ['h183', 'mouth']]}, self.ENTITY)
        self.assertEqual(flat, 'NPVMaker.morphs_' + path_hash(self.ENTITY) + ': [ n"h142", n"nose", n"h183", n"mouth" ]\n')

    def test_nothing_without_kept_shapes(self):
        self.assertEqual(runtime_import.morph_flat({}, self.ENTITY), '')
        self.assertEqual(runtime_import.morph_flat({'runtime_morphs': []}, self.ENTITY), '')

    def test_names_that_are_not_plain_identifiers_are_left_out(self):
        flat = runtime_import.morph_flat({'runtime_morphs': [['h142', 'nose'], ['a"b', 'x'], ['h1']]}, self.ENTITY)
        self.assertEqual(flat, 'NPVMaker.morphs_' + path_hash(self.ENTITY) + ': [ n"h142", n"nose" ]\n')


if __name__ == '__main__':
    unittest.main()
