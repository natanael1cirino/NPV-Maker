import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, r'D:\NPVMaker\tools')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from runtime_npc import read_selection


def cname(name):
    return {'$type': 'CName', '$storage': 'string', '$value': name}


def appearance(name, components):
    return {'Data': {'name': cname(name), 'components': components}}


def hair_part(name, mesh, material):
    return {'$type': 'entSkinnedMeshComponent', 'name': cname(name),
            'mesh': {'DepotPath': {'$value': mesh}}, 'meshAppearance': cname(material)}


def mesh_doc(*names):
    return {'Data': {'RootChunk': {'appearances': [appearance(name, []) for name in names]}}}


class Reader:
    def __init__(self, app, meshes):
        self.resources = {'hair.app': app, **meshes}

    def read(self, path):
        return copy.deepcopy(self.resources[path])


class RuntimeHairColorTests(unittest.TestCase):
    def setUp(self):
        self.option = {'name': 'bunny_hair', 'selected_name': '15_pink_magenta',
                       'resource_path': 'hair.app'}
        self.doc = {'Data': {'RootChunk': {'appearances': [appearance('01_blonde_platinum', [
            hair_part('hair_1', 'base\\hair\\pt1.mesh', 'blonde_platinum'),
            hair_part('hair_2', 'base\\hair\\pt2.mesh', 'blonde_platinum'),
            hair_part('hair_shadow', 'base\\hair\\shadow.mesh', 'default')])]} }}
        self.reader = Reader(self.doc, {
            'base\\hair\\pt1.mesh': mesh_doc('blonde_platinum', 'pink_magenta'),
            'base\\hair\\pt2.mesh': mesh_doc('blonde_platinum', 'pink_magenta'),
            'base\\hair\\shadow.mesh': mesh_doc('default', 'pink', 'pink_black')})

    def test_recolors_hair_parts_but_preserves_neutral_shadow(self):
        _, selected = read_selection(self.reader, self.option, {})
        parts = selected['components']
        self.assertEqual([p['meshAppearance']['$value'] for p in parts],
                         ['pink_magenta', 'pink_magenta', 'default'])

    def test_piece_without_the_color_keeps_its_own_and_is_recorded(self):
        # Decided 26/09/2026: one piece lacking the color no longer blocks the
        # import (0.4.1 failed here); it keeps its captured appearance.
        self.reader.resources['base\\hair\\pt2.mesh'] = mesh_doc('blonde_platinum')
        _, selected = read_selection(self.reader, self.option, {})
        self.assertEqual([p['meshAppearance']['$value'] for p in selected['components']],
                         ['pink_magenta', 'blonde_platinum', 'default'])
        self.assertEqual(selected['_npv_kept'], ['hair_2=blonde_platinum', 'hair_shadow=default'])

    def test_color_missing_from_every_mesh_still_explains_failure(self):
        for mesh in ('pt1', 'pt2'):
            self.reader.resources['base\\hair\\%s.mesh' % mesh] = mesh_doc('blonde_platinum')
        with self.assertRaisesRegex(ValueError, 'pink_magenta ausente em todas as malhas de bunny_hair'):
            read_selection(self.reader, self.option, {})


if __name__ == '__main__':
    unittest.main()
