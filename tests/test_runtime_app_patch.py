import copy
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from runtime_npc import collect_components
from runtime_resources import ResourceMissing, archive_xl_resources, path_hash

HEAD_APP = 'base\\characters\\head\\player_base_heads\\appearances\\head\\h0_000__basehead_d04.app'
PATCH_APP = 'author\\slots\\fem_head.app'
SLOT_MESH, EMPTY_SLOT_MESH = '11865089616013082354', '5448179688850809445'


def cname(name):
    return {'$type': 'CName', '$storage': 'string', '$value': name}


def mesh_part(name, mesh, cid='1', appearance='default'):
    return {'$type': 'entSkinnedMeshComponent', 'name': cname(name), 'id': cid,
            'mesh': {'DepotPath': {'$type': 'ResourcePath', '$value': mesh}}, 'meshAppearance': cname(appearance)}


def app(*appearances):
    return {'Data': {'RootChunk': {'appearances': [{'Data': {'name': cname(name), 'components': list(parts)}}
                                                   for name, parts in appearances]}}}


class Reader:
    """Installed files; `shipped` are the paths some mounted archive ships."""

    def __init__(self, resources, patches, shipped, failing=()):
        self.resources, self.patches, self.shipped, self.failing = resources, patches, set(shipped), set(failing)

    def read(self, path):
        if path in self.failing:
            raise ResourceMissing(path, 'no archive ships it')
        return copy.deepcopy(self.resources[path])

    def register(self, value, suffix):
        return value

    def source(self, path):
        return path

    def owners(self, path):
        return ['mod.archive'] if path in self.shipped else []

    def base_owner(self, path):
        return None


def head_option():
    return dict(name='skin_type_04', resource_path=HEAD_APP, selected_name='h0_000_pwa__basehead__01_ca_pale',
                body_part='head')


def names(result):
    return sorted(p['name']['$value'] for p in result['selected'].values())


class ScopeTests(unittest.TestCase):
    def xl(self, folder, name, text):
        (Path(folder) / name).write_text(text, encoding='utf8')

    def test_patch_on_a_scope_reaches_every_file_of_the_scope(self):
        # Shape of the installed nims_more_everything_axl.xl.
        with tempfile.TemporaryDirectory() as folder:
            self.xl(folder, 'nims.xl', 'resource:\n  scope:\n    player_head.app:\n'
                                       '      - base\\h\\h0_000__basehead.app\n      - base\\h\\h0_000__basehead_d04.app\n'
                                       '  patch:\n    author\\slots\\fem_head.app:\n      - player_head.app\n')
            copies, patches = archive_xl_resources([Path(folder)])
        self.assertEqual(patches, {'base\\h\\h0_000__basehead.app': ['author\\slots\\fem_head.app'],
                                   'base\\h\\h0_000__basehead_d04.app': ['author\\slots\\fem_head.app']})

    def test_bundle_scopes_nest_and_bundle_patches_stay_out(self):
        # ArchiveXL's bundle names player_wa_eyes.mesh through another scope;
        # Lithium Flower eyes patch that name.
        with tempfile.TemporaryDirectory() as mods, tempfile.TemporaryDirectory() as bundle:
            self.xl(mods, 'lfeyes.xl', 'resource:\n  patch:\n    lf\\patch.mesh:\n      - player_wa_eyes.mesh\n')
            self.xl(bundle, 'EyesScope.xl', 'resource:\n  scope:\n    player_wa_eyes.mesh:\n      - player_wa_base_eyes.mesh\n'
                                            '    player_wa_base_eyes.mesh:\n      - base\\he_000_pwa_c__basehead.mesh\n')
            self.xl(bundle, 'EyesPatch.xl', 'resource:\n  patch:\n    axl\\he_patch.mesh:\n      - base\\he_000_pwa_c__basehead.mesh\n')
            copies, patches = archive_xl_resources([Path(mods)], scope_folders=[Path(bundle)])
        self.assertEqual(patches, {'base\\he_000_pwa_c__basehead.mesh': ['lf\\patch.mesh']})

    def test_property_patch_on_a_scope_defined_in_a_later_file(self):
        with tempfile.TemporaryDirectory() as folder:
            self.xl(folder, 'a.xl', 'resource:\n  patch:\n    m\\lashes_source.mesh:\n      props: [ appearances ]\n'
                                    '      targets: [ player_wa_lashes.mesh ]\n')
            self.xl(folder, 'b.xl', 'resource:\n  scope:\n    player_wa_lashes.mesh:\n      - m\\lashes.mesh\n')
            props = {}
            archive_xl_resources([Path(folder)], props)
        self.assertEqual(props, {int(path_hash('m\\lashes.mesh')): ('m\\lashes_source.mesh', ['appearances'])})

    def test_scopes_that_name_each_other_end(self):
        with tempfile.TemporaryDirectory() as folder:
            self.xl(folder, 'a.xl', 'resource:\n  scope:\n    one.app:\n      - two.app\n      - x\\real.app\n'
                                    '    two.app:\n      - one.app\n  patch:\n    p.app:\n      - one.app\n')
            copies, patches = archive_xl_resources([Path(folder)])
        self.assertEqual(patches, {'x\\real.app': ['p.app']})


class AppPatchTests(unittest.TestCase):
    def reader(self, patch_doc, failing=()):
        resources = {HEAD_APP: app(('h0_000_pwa__basehead__01_ca_pale', [mesh_part('head', 'base\\head.mesh')])),
                     PATCH_APP: patch_doc}
        return Reader(resources, {HEAD_APP.lower(): [PATCH_APP]}, {SLOT_MESH, 'base\\head.mesh', 'b\\other.mesh'},
                      failing)

    def test_patch_slot_with_a_shipped_mesh_joins_the_head(self):
        # Mariko 3.0 (28/09/2026): the jaw plates of Sedth Cyber Jaw sit in
        # slots Nim's More Everything patches into the head .app.
        reader = self.reader(app(('h0_000_pwa__basehead__01_ca_pale',
                                  [mesh_part('Nim_Head_Bits_01', EMPTY_SLOT_MESH, '7'),
                                   mesh_part('Nim_Head_Bits_02', SLOT_MESH, '7')]),
                                 ('h0_000_pwa__basehead__02_ca_limestone', [mesh_part('other_tone', SLOT_MESH, '7')])))
        result = collect_components(reader, [head_option()], {})
        self.assertEqual(names(result), ['Nim_Head_Bits_02', 'head'])
        self.assertEqual(result['used'][0]['archivexl_patch'],
                         {'patches': [PATCH_APP], 'added': ['Nim_Head_Bits_02'], 'without_mesh': ['Nim_Head_Bits_01']})
        self.assertEqual(result['diagnostics'], [])

    def test_patch_appearance_without_name_applies_to_every_appearance(self):
        reader = self.reader(app(('None', [mesh_part('slot', SLOT_MESH, '7')])))
        self.assertEqual(names(collect_components(reader, [head_option()], {})), ['head', 'slot'])

    def test_same_name_and_id_replaces_and_other_id_adds(self):
        reader = self.reader(app(('h0_000_pwa__basehead__01_ca_pale',
                                  [mesh_part('head', 'b\\other.mesh', '1'), mesh_part('head', SLOT_MESH, '2')])))
        result = collect_components(reader, [head_option()], {})
        meshes = sorted(p['mesh']['DepotPath']['$value'] for p in result['selected'].values())
        self.assertEqual(meshes, sorted(['b\\other.mesh', SLOT_MESH]))
        self.assertEqual(result['used'][0]['archivexl_patch']['replaced'], ['head'])

    def test_replacement_without_a_mesh_removes_the_piece(self):
        reader = self.reader(app(('h0_000_pwa__basehead__01_ca_pale', [mesh_part('head', '0', '1')])))
        result = collect_components(reader, [head_option()], {})
        self.assertEqual(names(result), [])
        self.assertEqual(result['used'][0]['archivexl_patch']['removed'], ['head'])

    def test_unreadable_patch_keeps_the_head_and_warns(self):
        reader = self.reader(app(), failing={PATCH_APP})
        result = collect_components(reader, [head_option()], {})
        self.assertEqual(names(result), ['head'])
        self.assertEqual([d['code'] for d in result['diagnostics']], ['NPVM-PATCH-001'])
        self.assertEqual(result['skipped'], [])


class RuntimeMissingTests(unittest.TestCase):
    def project(self, *components):
        return {'runtime_manifest': {'schema': 1, 'status': 'captured', 'components': [
            dict(name=name, type='entSkinnedMeshComponent', field='mesh', hash=value, state=state)
            for name, value, state in components]}}

    def test_piece_the_editor_drew_and_the_npc_lacks_is_reported(self):
        from runtime_npc import runtime_missing
        project = self.project(('head', '1', 'LOADED'), ('Nim_Head_Bits_02', SLOT_MESH, 'LOADED'),
                               ('Nim_Head_Bits_01', '0', 'NONE'), ('maybe', '9', 'UNOBSERVED'),
                               ('a0_001_pwa_base_hq__full', '5', 'LOADED'))
        selected = {1: mesh_part('head', 'base\\head.mesh'),
                    2: mesh_part('a0_001_pwa_base_hq__full__npv_rt1', 'base\\arms.mesh')}
        self.assertEqual(runtime_missing(project, selected), ['Nim_Head_Bits_02'])
        self.assertEqual(runtime_missing({}, selected), [])


if __name__ == '__main__':
    unittest.main()
