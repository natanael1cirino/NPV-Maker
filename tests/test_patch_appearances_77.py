import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tests'))
import material_chain  # noqa: E402
import npv_package as pkg  # noqa: E402
from test_npv_package import FakeLocator, cname, depot, key  # noqa: E402

# Shape measured 05/10/2026 on the RED: Beanie's CCXL Clinic patches xtra_cyberware.mesh (no geometry, 6 appearances)
# onto the vanilla freckles mesh, which already has entries with the same material names. Names here are generic.
TARGET = 'base\\characters\\head\\target_makeup.mesh'
PATCH = 'some_mod\\patch_a.mesh'
OTHER_PATCH = 'other_mod\\patch_b.mesh'
COPY = 'npvmaker\\generated\\abc\\meshes\\copy.mesh'
NOSE_MI = 'base\\characters\\common\\makeup\\nose_05.mi'
DOT_MI = 'base\\characters\\common\\makeup\\dot_01.mi'
PATCH_ONLY_MI = 'some_mod\\materials\\shiny.mi'


def appearance(name, *chunks):
    return {'HandleId': name, 'Data': {'name': cname(name), 'chunkMaterials': [cname(c) for c in chunks]}}


def mesh(appearances, entries):
    """entries: [(name, path)], all local instances in order."""
    return {'Data': {'RootChunk': {
        'appearances': appearances,
        'materialEntries': [{'index': i, 'isLocalInstance': 1, 'name': cname(n)} for i, (n, _) in enumerate(entries)],
        'localMaterialBuffer': {'materials': [{'$type': 'CMaterialInstance', 'baseMaterial': depot(p)} for _, p in entries]}}}}


def target_mesh():
    return mesh([appearance('default', 'dot'), appearance('vanilla_05', 'nose', 'nose')],
                [('dot', DOT_MI), ('nose', NOSE_MI)])


def patch_mesh():
    return mesh([appearance('extra_01', 'nose', 'nose'), appearance('extra_02', 'shiny')],
                [('nose', NOSE_MI), ('shiny', PATCH_ONLY_MI)])


class Reader:
    def __init__(self, docs):
        self.docs = docs

    def mesh(self, path):
        if path not in self.docs:
            raise ValueError('ausente: ' + path)
        return self.docs[path]

    def references(self, path):
        return material_chain.depot_paths(self.mesh(path).get('Data'), []) if path in self.docs else []


def chain(appearance_name, patches, docs=None, mesh_path=TARGET, copies=()):
    docs = docs or {TARGET: target_mesh(), PATCH: patch_mesh()}
    return material_chain.npv_material_files(Reader(docs), {
        'embedded_copies': [{'resource': c, 'source': TARGET, 'from_mod': False} for c in copies],
        'components': [{'name': 'piece', 'mesh': mesh_path, 'material': appearance_name}]}, {}, patches)


def detect(files, **mods):
    loc = FakeLocator(mods={n + '.archive': {key(p) for p in ps} for n, ps in mods.items()},
                      base={key(NOSE_MI), key(DOT_MI)}, frameworks={})
    return [d['name'] for d in pkg.detect_dependencies(Path('.'), [{'resource': f, 'archive': None, 'via': 'material'}
                                                                   for f in files], loc, {})['dependencies']]


class PatchAppearanceTests(unittest.TestCase):
    """BUGS 77 (author scope 05/10/2026): appearance added by an ArchiveXL list patch mesh."""

    PATCHES = {TARGET.lower(): [PATCH]}

    def test_appearance_only_in_a_patch_resolves(self):
        found = chain('extra_01', self.PATCHES)
        self.assertEqual((found['unresolved'], found['files']), ([], [NOSE_MI]))
        self.assertEqual(chain('extra_01', {})['unresolved'], ['piece'])

    def test_vanilla_final_material_makes_no_requirement(self):
        self.assertEqual(detect(chain('extra_01', self.PATCHES)['files']), [])

    def test_mod_replacing_the_used_mi_is_a_requirement(self):
        self.assertEqual(detect(chain('extra_01', self.PATCHES)['files'], NoseMod=[NOSE_MI]), ['NoseMod'])

    def test_unselected_patch_appearance_makes_nothing(self):
        found = chain('vanilla_05', self.PATCHES)
        self.assertNotIn(PATCH_ONLY_MI, found['files'])
        self.assertEqual(detect(found['files'], ShinyMod=[PATCH_ONLY_MI]), [])
        self.assertEqual(detect(chain('extra_02', self.PATCHES)['files'], ShinyMod=[PATCH_ONLY_MI]), ['ShinyMod'])

    def test_two_patches_with_the_same_appearance_stay_unresolved(self):
        docs = {TARGET: target_mesh(), PATCH: patch_mesh(), OTHER_PATCH: patch_mesh()}
        found = chain('extra_01', {TARGET.lower(): [PATCH, OTHER_PATCH]}, docs)
        self.assertEqual((found['unresolved'], found['files']), (['piece'], []))

    def test_same_material_name_with_other_file_in_patch_and_target_stays_unresolved(self):
        ambiguous = mesh([appearance('extra_01', 'nose')], [('nose', 'some_mod\\materials\\other_nose.mi')])
        found = chain('extra_01', self.PATCHES, {TARGET: target_mesh(), PATCH: ambiguous})
        self.assertEqual(found['unresolved'], ['piece'])

    def test_appearance_in_the_mesh_keeps_the_previous_behaviour(self):
        with_patches = chain('vanilla_05', self.PATCHES)
        without = chain('vanilla_05', {})
        self.assertEqual(with_patches, without)
        self.assertEqual(with_patches['files'], [NOSE_MI])

    def test_generated_copy_uses_the_patches_of_its_original(self):
        found = chain('extra_01', self.PATCHES, mesh_path=COPY, copies=[COPY])
        self.assertEqual((found['unresolved'], found['files']), ([], [NOSE_MI]))

    def test_unreadable_patch_leaves_it_unresolved(self):
        found = chain('extra_01', self.PATCHES, {TARGET: target_mesh()})
        self.assertEqual(found['unresolved'], ['piece'])


if __name__ == '__main__':
    unittest.main()
