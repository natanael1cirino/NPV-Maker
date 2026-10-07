import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import runtime_npc
from bake_morph_glb import unpack_glb

VANILLA = 'base\\characters\\head\\player_base_heads\\player_female_average\\h0_000_pwa_c__basehead\\ht_000_pwa_c__basehead.mesh'
MOD = 'icxrus\\ccxl\\teethpack1\\meshes\\icxrus_pwa_teeth.mesh'
MORPH = 'icxrus\\ccxl\\teethpack1\\meshes\\icxrus_pwa_vamp2teeth.morphtarget'


def glb(skinned: bool) -> bytes:
    """One vertex, one morph target h123_mouth; with skin: a joint and JOINTS_0/WEIGHTS_0."""
    parts = [('<fff', (0.0, 1.6, 0.0), 5126, 'VEC3'), ('<fff', (0.0, 0.01, 0.0), 5126, 'VEC3')]
    if skinned:
        parts += [('<4H', (0, 0, 0, 0), 5123, 'VEC4'), ('<4f', (1.0, 0.0, 0.0, 0.0), 5126, 'VEC4')]
    binary, views, accessors = b'', [], []
    for fmt, values, component, kind in parts:
        payload = struct.pack(fmt, *values)
        views.append({'buffer': 0, 'byteOffset': len(binary), 'byteLength': len(payload)})
        accessor = {'bufferView': len(views) - 1, 'componentType': component, 'count': 1, 'type': kind}
        if len(accessors) == 0:
            accessor.update(min=[0.0, 1.6, 0.0], max=[0.0, 1.6, 0.0])
        accessors.append(accessor)
        binary += payload
    attributes = {'POSITION': 0}
    doc = {'asset': {'version': '2.0'}, 'buffers': [{'byteLength': len(binary)}], 'bufferViews': views,
           'accessors': accessors, 'nodes': [{'name': 'mid_J_jaw_JNT'}, {'mesh': 0}],
           'meshes': [{'extras': {'targetNames': ['h123_mouth']},
                       'primitives': [{'attributes': attributes, 'targets': [{'POSITION': 1}]}]}]}
    if skinned:
        attributes.update(JOINTS_0=2, WEIGHTS_0=3)
        doc['skins'] = [{'joints': [0]}]
    data = json.dumps(doc).encode()
    data += b' ' * ((-len(data)) % 4)
    binary += b'\0' * ((-len(binary)) % 4)
    return (struct.pack('<4sII', b'glTF', 2, 28 + len(data) + len(binary)) + struct.pack('<I4s', len(data), b'JSON')
            + data + struct.pack('<I4s', len(binary), b'BIN\0') + binary)


class WolvenKit:
    """Fake CLI with the measured behaviour: the export sees only archives in content/ep1 of
    --gamepath; a base mesh it cannot see gives a warning and a GLB without skin."""

    def __init__(self, game: Path, bones: dict, never_skins=()):
        self.game, self.bones, self.never_skins, self.calls, self.packed, self.imported = game, bones, never_skins, [], {}, []

    def __call__(self, cli, command, *args):
        self.calls.append((command,) + tuple(map(str, args)))
        if command == 'pack':
            staged, out = Path(args[0]), Path(args[2])
            files = ['\\'.join(p.relative_to(staged).parts) for p in staged.rglob('*') if p.is_file()]
            (out / (staged.name + '.archive')).write_text(json.dumps(files))
            self.packed[staged.name] = files
            return ''
        if command == 'export':
            morph, out, gamepath = Path(args[0]), Path(args[2]), Path(args[4])
            base = self.base
            visible = (gamepath == self.game and base == VANILLA) or any(
                base in json.loads(a.read_text()) for a in (gamepath / 'archive/pc/content').glob('basegame_*.archive'))
            (out / (morph.name + '.glb')).write_bytes(
                glb(visible and bool(self.bones.get(base)) and base not in self.never_skins))
            return ('' if visible else '[ 0: Warning ] - The file "%s" could not be found!\n' % base) + 'Successfully exported'
        if command == 'import':
            meta, _ = unpack_glb(Path(args[0]).read_bytes())
            self.imported.append(bool(meta.get('skins')))
            return ''
        raise AssertionError(command)


class Reader:
    def __init__(self, folder: Path, bones: dict, donor=None):
        self.folder, self.bones, self.donor = folder, bones, donor

    def props_donor(self, morph):
        return self.donor

    def source(self, resource):
        return resource

    def fetch(self, resources):
        for resource in resources:
            self.path(resource).write_bytes(b'file ' + resource.encode())

    def path(self, resource):
        return self.folder / resource.split('\\')[-1]

    def read(self, resource):
        return {'Data': {'RootChunk': {'boneNames': [{'$value': b} for b in self.bones.get(resource, [])]}}}

    def patched(self, resource):
        return False


class BakeSkinTests(unittest.TestCase):
    def bake(self, base, bones, never_skins=(), donor=None):
        temp = Path(tempfile.mkdtemp())
        self.addCleanup(__import__('shutil').rmtree, temp, True)
        game, cache, folder = temp / 'game', temp / 'cache', temp / 'morphs' / '1aaff9db882e7644'
        for path in (game, cache, folder):
            path.mkdir(parents=True)
        tool = WolvenKit(game, bones, never_skins)
        tool.base = base
        reader = Reader(cache, bones, donor)
        reader.fetch([base])  # build() fetches every base mesh before baking
        doc = {'Data': {'RootChunk': {'baseMesh': {'DepotPath': {'$value': base}},
                                      'targets': [{'name': {'$value': 'h123'}, 'regionName': {'$value': 'mouth'}}]}}}
        original = runtime_npc.cli_run
        runtime_npc.cli_run = tool
        try:
            result = runtime_npc.bake_morph(reader, Path('WolvenKit.CLI.exe'), game, MORPH, doc, ['h123_mouth'], folder,
                                            'npvmaker\\generated\\x', temp / 'source', {})
        finally:
            runtime_npc.cli_run = original
        return result, tool, folder

    def test_vanilla_base_mesh_keeps_the_single_export(self):
        result, tool, _ = self.bake(VANILLA, {VANILLA: ['Head', 'mid_J_jaw_JNT']})
        self.assertIsNone(result['error'])
        self.assertEqual(result['applied_shapes'], ['h123_mouth'])
        self.assertEqual([c[0] for c in tool.calls], ['export', 'import'])
        self.assertEqual(tool.imported, [True])

    def test_mod_only_base_mesh_is_exported_through_a_depot_with_its_skin(self):
        result, tool, folder = self.bake(MOD, {MOD: ['Head', 'mid_J_jaw_JNT']})
        self.assertIsNone(result['error'])
        self.assertEqual(result['resource'], 'npvmaker\\generated\\x\\meshes\\1aaff9db882e7644.mesh')
        self.assertEqual([c[0] for c in tool.calls], ['export', 'pack', 'export', 'import'])
        self.assertEqual(tool.imported, [True])
        depot_export = tool.calls[2]
        self.assertEqual(Path(depot_export[-1]), folder.with_name(folder.name + '-depot') / 'game')
        self.assertTrue((Path(depot_export[-1]) / 'bin/x64').is_dir())

    def test_depot_keeps_the_exact_resource_path(self):
        _, tool, _ = self.bake(MOD, {MOD: ['Head']})
        self.assertEqual(tool.packed, {'basegame_npvmaker_depot': [MOD]})

    def test_successful_export_without_skin_is_rejected_and_the_original_mesh_stays(self):
        result, tool, _ = self.bake(MOD, {MOD: ['Head']}, never_skins=(MOD,))
        self.assertIn('esqueleto nao preservado', str(result['error']))
        self.assertEqual((result['resource'], result['applied_shapes']), (MOD, []))
        self.assertEqual(tool.imported, [])

    def test_missing_resource_warning_is_rejected_when_no_depot_can_be_made(self):
        # The export of an ArchiveXL donor file is not the morph itself, so no depot is built.
        result, tool, _ = self.bake(MOD, {MOD: ['Head']}, donor='base\\donor.morphtarget')
        self.assertIn('esqueleto nao preservado', str(result['error']))
        self.assertEqual(result['resource'], MOD)
        self.assertNotIn('pack', [c[0] for c in tool.calls])
        self.assertEqual(tool.imported, [])

    def test_piece_without_bones_is_not_an_error(self):
        result, tool, _ = self.bake(VANILLA, {VANILLA: []})
        self.assertIsNone(result['error'])
        self.assertEqual(result['applied_shapes'], ['h123_mouth'])
        self.assertEqual(tool.imported, [False])


if __name__ == '__main__':
    unittest.main()
