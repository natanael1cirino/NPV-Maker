import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tests'))
import material_chain  # noqa: E402
import npv_package as pkg  # noqa: E402
from test_npv_package import FakeLocator, cname, depot, key  # noqa: E402

# Shape of peachu_y2kponytail_pt1.mesh (Y2K Ponytail CCXL) as the RED conversion serialized it, 05/10/2026.
HAIR = 'peachu_hairs\\peachu_y2kponytail\\meshes\\peachu_y2kponytail_pt1.mesh'
CAP_MI = 'peachu_hairs\\peachu_y2kponytail\\materials\\peachu_y2kponytail_cap.mi'
LONG_MI = 'peachu_hairs\\peachu_y2kponytail\\materials\\peachu_y2kponytail_long.mi'
TEX = 'base\\characters\\common\\hair\\textures\\'
GRADIENT = '*' + TEX + 'cap_gradiants\\hh_cap_grad__{material}.xbm'
PROFILE = '*' + TEX + 'hair_profiles\\{material}.hp'
BLACK_HP = TEX + 'hair_profiles\\black_carbon.hp'
GINGER_HP = TEX + 'hair_profiles\\ginger_strawberry.hp'
GINGER_GRAD = TEX + 'cap_gradiants\\hh_cap_grad__ginger_strawberry.xbm'
SKIN_TOKEN = '*' + TEX + 'skin\\{skin_color}.xbm'


def instance(base, **values):
    data = {'$type': 'CMaterialInstance', 'values': [{'$type': 'rRef:ITexture', k: depot(v)} for k, v in values.items()]}
    if base:
        data['baseMaterial'] = depot(base)
    return data


def appearance(name, *chunks):
    return {'HandleId': name, 'Data': {'name': cname(name), 'chunkMaterials': [cname(c) for c in chunks]}}


def hair_mesh(extra_appearances=(), extra_entries=(), extra_local=()):
    return {'Data': {'RootChunk': {
        'appearances': [appearance('black_carbon', 'black_carbon@cap', 'black_carbon@long'),
                        appearance('ginger_strawberry', 'ginger_strawberry@cap', 'ginger_strawberry@long')]
        + list(extra_appearances),
        'materialEntries': [{'index': 0, 'isLocalInstance': 1, 'name': cname('@context')},
                            {'index': 1, 'isLocalInstance': 1, 'name': cname('@cap')},
                            {'index': 2, 'isLocalInstance': 1, 'name': cname('@long')}] + list(extra_entries),
        'localMaterialBuffer': {'materials': [instance(None), instance(CAP_MI, GradientMap=GRADIENT),
                                              instance(LONG_MI, HairProfile=PROFILE)] + list(extra_local)}}}}


class Reader:
    def __init__(self, mesh):
        self.docs = {HAIR: mesh, CAP_MI: {'Data': {'RootChunk': {}}}, LONG_MI: {'Data': {'RootChunk': {}}}}

    def mesh(self, path):
        if path not in self.docs:
            raise ValueError('ausente: ' + path)
        return self.docs[path]

    def references(self, path):
        return material_chain.depot_paths(self.mesh(path).get('Data'), [])


def chain(appearance_name, mesh=None, fixes=None):
    return material_chain.npv_material_files(Reader(mesh or hair_mesh()), {'components': [
        {'name': 'hair', 'mesh': HAIR, 'material': appearance_name}]}, fixes)


def locator(**mods):
    return FakeLocator(mods={name + '.archive': {key(p) for p in paths} for name, paths in mods.items()},
                       base={key(BLACK_HP), key(GINGER_HP), key(GINGER_GRAD)}, frameworks={})


def detect(files, loc):
    return pkg.detect_dependencies(Path('.'), [{'resource': f, 'archive': None, 'via': 'material'} for f in files], loc, {})


class DynamicMaterialTests(unittest.TestCase):
    """BUGS 76 (author scope 05/10/2026): name@context, * paths and {material}; other tokens stay unresolved."""

    def test_material_token_and_context_entry(self):
        found = chain('ginger_strawberry')
        self.assertEqual(found['unresolved'], [])
        self.assertEqual(sorted(found['files']), sorted([CAP_MI, GINGER_GRAD, LONG_MI, GINGER_HP]))
        self.assertFalse(any('*' in f or '{' in f for f in found['files']))
        self.assertEqual(found['unresolved_paths'], [])

    def test_black_hair_color_only_for_black_carbon(self):
        loc = locator(**{'Black Hair Color': [BLACK_HP], 'peachu_y2kponytail_CCXL': [CAP_MI, LONG_MI]})
        black = {d['name']: d for d in detect(chain('black_carbon')['files'], loc)['dependencies']}
        self.assertIn('Black Hair Color', black)
        self.assertTrue(black['Black Hair Color']['required_for_rebuild'])
        self.assertEqual(black['Black Hair Color']['resources'], [{'path': BLACK_HP, 'kind': 'material_override'}])
        ginger = [d['name'] for d in detect(chain('ginger_strawberry')['files'], loc)['dependencies']]
        self.assertNotIn('Black Hair Color', ginger)
        self.assertEqual(ginger, ['peachu_y2kponytail_CCXL'])

    def test_vanilla_winner_makes_no_requirement(self):
        found = detect(chain('ginger_strawberry')['files'], locator())
        self.assertEqual(found['dependencies'], [])

    def test_unknown_token_never_makes_a_requirement(self):
        mesh = hair_mesh([appearance('pale', 'pale@skin')], [{'index': 3, 'isLocalInstance': 1, 'name': cname('@skin')}],
                         [instance(None, Diffuse=SKIN_TOKEN)])
        found = chain('pale', mesh)
        self.assertEqual(found['files'], [])
        self.assertEqual(found['unresolved_paths'], [SKIN_TOKEN])
        guess = TEX + 'skin\\03_senna.xbm'
        loc = locator(**{'Skin guess': [guess]})
        self.assertEqual(detect(found['files'], loc)['dependencies'], [])

    def test_missing_context_entry_is_unresolved(self):
        mesh = hair_mesh([appearance('odd', 'odd@nowhere')])
        self.assertEqual(chain('odd', mesh)['unresolved'], ['hair'])

    def test_fix_names_lead_to_the_dynamic_entry(self):
        mesh = hair_mesh([appearance('violet', 'violet_plain')])
        fixes = {HAIR.lower(): {'names': {'violet_plain': 'violet@long'}, 'context': {}}}
        self.assertEqual(chain('violet', mesh)['unresolved'], ['hair'])
        found = chain('violet', mesh, fixes)
        self.assertIn(TEX + 'hair_profiles\\violet.hp', found['files'])

    def test_renamed_entry_with_the_exact_name_wins_over_the_template(self):
        # Measured 05/10/2026: the ArchiveXL bundle fix of he_000_pwa_c__basehead.mesh renames chunk and entry names
        # (gradient_red -> gradient_red@eyes) and the mesh has no "@eyes" entry; the RED eye must keep its material.
        eye_mi = 'base\\characters\\common\\eyes\\gradient_red.mi'
        mesh = {'Data': {'RootChunk': {
            'appearances': [appearance('gradient_red', 'gradient_red')],
            'materialEntries': [{'index': 0, 'isLocalInstance': 0, 'name': cname('gradient_red')}],
            'externalMaterials': [depot(eye_mi)]}}}
        fixes = {HAIR.lower(): {'names': {'gradient_red': 'gradient_red@eyes'}, 'context': {}}}
        found = chain('gradient_red', mesh, fixes)
        self.assertEqual((found['unresolved'], found['files']), ([], [eye_mi]))

    def test_empty_appearance_uses_the_first_as_template(self):
        mesh = hair_mesh([appearance('platinum')])
        found = chain('platinum', mesh)
        self.assertIn(TEX + 'hair_profiles\\platinum.hp', found['files'])
        self.assertIn(TEX + 'cap_gradiants\\hh_cap_grad__platinum.xbm', found['files'])

    def test_generated_copy_takes_the_fix_of_its_original(self):
        copy = 'npvmaker\\generated\\abc\\meshes\\hair.mesh'
        mesh = hair_mesh([appearance('violet', 'violet_plain')])
        fixes = {HAIR.lower(): {'names': {'violet_plain': 'violet@long'}, 'context': {}}}
        found = material_chain.npv_material_files(Reader(mesh), {
            'embedded_copies': [{'resource': copy, 'source': HAIR, 'from_mod': True}],
            'components': [{'name': 'hair', 'mesh': copy, 'material': 'violet'}]}, fixes)
        self.assertIn(TEX + 'hair_profiles\\violet.hp', found['files'])


if __name__ == '__main__':
    unittest.main()
